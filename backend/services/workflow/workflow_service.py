from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from core.config import settings
from core.domain_exceptions import (
    AccessDeniedError,
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationFailedError,
)
from core.models.workflows import Workflow
from models.workflow_changes import WorkflowChangeListResponse
from models.workflows import (
    StaticAttributeDef,
    WorkflowCreate,
    WorkflowGitDiffResponse,
    WorkflowGitHistoryResponse,
    WorkflowGitSyncStatus,
    WorkflowListResponse,
    WorkflowNameCheckResponse,
    WorkflowNotesResponse,
    WorkflowResponse,
    WorkflowSummary,
    WorkflowUpdate,
)
from repositories.run_repository import RunRepository
from repositories.workflow_repository import WorkflowRepository
from services.artifacts import FilesystemArtifactService
from services.execution.background_tier_service import BackgroundTierService
from services.execution.fan_out_topology import validate_fan_out_topology
from services.execution.graph import (
    GraphCycleError,
    child_node_ids,
    find_join_node_id,
    topological_order,
)
from services.execution.log_attribute_files import delete_run_dir
from services.execution.schedule_service import ScheduleService
from services.workflow.ai_write_gate import AiWriteGate
from services.workflow.child_run_inputs import validate_start_workflow_secret_inputs
from services.workflow.config_normalisation import normalise_canvas_nodes
from services.workflow.workflow_change_service import WorkflowChangeService
from services.workflow.workflow_git_service import WorkflowGitService, WorkflowGitSyncResult

logger = logging.getLogger(__name__)


def _validate_no_cycle(canvas_nodes: list[dict], canvas_edges: list[dict]) -> None:
    """Raise HTTP 400 if the canvas graph contains a cycle.

    Without this, a cyclic graph is accepted
    at save time and then silently loses the cyclic nodes at run time (they
    never reach in-degree 0 in StepRunner's topological sort).
    """
    try:
        topological_order(canvas_nodes, canvas_edges)
    except GraphCycleError as exc:
        raise ValidationFailedError(str(exc)) from exc


def _validate_stop_here_not_in_fan_out(canvas_nodes: list[dict], canvas_edges: list[dict]) -> None:
    """Raise HTTP 400 if a ``stop-here`` node sits inside a fan-out branch.

    Fan-out children walk the resolved graph (``StepRunner.load_execution_graph``), but
    a stop-here inside a branch would only truncate that one child while the parent
    carries on, which no author means — reject it at save time.
    """
    stop_here_ids = {
        n["id"]
        for n in canvas_nodes
        if "id" in n and (n.get("data") or {}).get("kind") == "stop-here"
    }
    if not stop_here_ids:
        return

    for node in canvas_nodes:
        node_id = node.get("id", "")
        fan_out = (node.get("data", {}) or {}).get("pluginConfig", {}).get("fan_out") or {}
        if not fan_out.get("enabled"):
            continue
        join_node_id = find_join_node_id(node_id, canvas_nodes, canvas_edges)
        branch_ids = child_node_ids(node_id, join_node_id, canvas_nodes, canvas_edges)
        offending = stop_here_ids & branch_ids
        if offending:
            raise ValidationFailedError(
                "Stop Here is not supported inside a fan-out branch "
                f"(node(s): {', '.join(sorted(offending))})"
            )


def _validate_fan_out_topology(canvas_nodes: list[dict], canvas_edges: list[dict]) -> None:
    """Raise HTTP 400 when a fan-out workflow has nodes the engine would never run (C1-01)."""
    violations = validate_fan_out_topology(canvas_nodes, canvas_edges)
    if violations:
        raise ValidationFailedError(" ".join(v.message for v in violations))


def _validate_static_attributes(static_attributes: list[dict] | list[StaticAttributeDef]) -> None:
    """Raise HTTP 400 on a duplicate attribute name or a default value that
    doesn't match its declared type — the same shape checks a hand-typed
    canvas config field never gets, but this schema drives a generated form
    (the run-inputs dialog), so a bad row there breaks every future run."""
    seen: set[str] = set()
    for raw in static_attributes:
        attr = (
            raw if isinstance(raw, StaticAttributeDef) else StaticAttributeDef.model_validate(raw)
        )
        if attr.name in seen:
            raise ValidationFailedError(f"Duplicate static attribute name: {attr.name!r}")
        seen.add(attr.name)
        if attr.default is None:
            continue
        is_number = isinstance(attr.default, (int, float)) and not isinstance(attr.default, bool)
        is_int = isinstance(attr.default, int) and not isinstance(attr.default, bool)
        type_ok = (
            (attr.type == "string" and isinstance(attr.default, str))
            or (attr.type == "number" and is_number)
            or (attr.type == "boolean" and isinstance(attr.default, bool))
            or (
                attr.type == "reference"
                and (
                    (attr.ref_kind == "inventory" and is_int)
                    or (attr.ref_kind == "credential" and isinstance(attr.default, str))
                )
            )
        )
        if not type_ok:
            raise ValidationFailedError(
                f"Static attribute {attr.name!r}: default does not match type {attr.type!r}"
            )


def _repair_orphan_groups(canvas_nodes: list[dict], canvas_groups: list[dict]) -> list[dict]:
    """Drop dangling member ids and dissolve selection groups left with < 2 members.

    Container groups (``isContainer: true``, created from the palette's "Step
    Group") are never dissolved — they are allowed to be empty.

    Mirrors the frontend's client-side repair (frontend/.../utils/
    canvas-group-projection.ts::repairOrphanGroups), which only runs when a
    human deletes a node through the canvas UI (use-canvas-node-changes.ts's
    removeRealNodes already keeps canvas_groups in sync at that point). An
    AI-authored patch (backend/scripts/ai_workflow_apply.py) — or any other
    caller writing canvas_nodes/canvas_groups directly — bypasses that path
    entirely, so this backend-side repair is the only thing that catches a
    group left referencing a node that no longer exists. Boundary ports are
    derived from membership and edges on the frontend, so nothing else needs
    repairing here.
    """
    node_ids = {n["id"] for n in canvas_nodes if "id" in n}
    repaired: list[dict] = []
    for group in canvas_groups:
        surviving_ids = [nid for nid in group.get("nodeIds", []) if nid in node_ids]
        if len(surviving_ids) < 2 and group.get("isContainer") is not True:
            continue
        repaired.append({**group, "nodeIds": surviving_ids})
    return repaired


def _to_summary(workflow: Workflow, creator_username: str | None) -> WorkflowSummary:
    return WorkflowSummary(
        id=workflow.id,
        uuid=workflow.uuid,
        name=workflow.name,
        creator_id=workflow.creator_id,
        creator_username=creator_username,
        description=workflow.description,
        folder=workflow.folder,
        visibility=workflow.visibility,
        is_version_controlled=workflow.is_version_controlled,
        notes=workflow.notes,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def _to_git_sync_status(result: WorkflowGitSyncResult | None) -> WorkflowGitSyncStatus | None:
    if result is None:
        return None
    return WorkflowGitSyncStatus(
        status=result.status,
        commit_sha=result.commit_sha,
        pushed=result.pushed,
        message=result.message,
    )


def _as_utc(value: datetime) -> datetime:
    """A timezone-aware UTC instant (a naive value, as SQLite returns, is taken as UTC)."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _normalised_nodes(nodes: list[dict], *, strict: bool) -> list[dict]:
    """Node configuration booleans as real booleans (see ``config_normalisation``)."""
    try:
        return normalise_canvas_nodes(nodes or [], strict=strict)
    except ValueError as exc:
        if strict:
            raise ValidationFailedError(str(exc)) from exc
        raise


def _to_response(
    workflow: Workflow,
    creator_username: str | None,
    git_sync: WorkflowGitSyncResult | None = None,
) -> WorkflowResponse:
    return WorkflowResponse(
        id=workflow.id,
        uuid=workflow.uuid,
        name=workflow.name,
        creator_id=workflow.creator_id,
        creator_username=creator_username,
        description=workflow.description,
        folder=workflow.folder,
        visibility=workflow.visibility,
        is_version_controlled=workflow.is_version_controlled,
        notes=workflow.notes,
        canvas_nodes=_normalised_nodes(workflow.canvas_nodes or [], strict=False),
        canvas_edges=workflow.canvas_edges,
        canvas_groups=workflow.canvas_groups,
        static_attributes=workflow.static_attributes,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
        git_sync=_to_git_sync_status(git_sync),
    )


class WorkflowService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = WorkflowRepository(db)
        self.git = WorkflowGitService(db)
        self.changes = WorkflowChangeService(db)
        self.ai_gate = AiWriteGate(db)

    def list_workflows(self, user_id: int) -> WorkflowListResponse:
        logger.debug("Listing accessible workflows user_id=%s", user_id)
        rows = self.repo.list_accessible(user_id)
        summaries = [_to_summary(wf, username) for wf, username in rows]
        logger.debug("Listed accessible workflows user_id=%s total=%s", user_id, len(summaries))
        return WorkflowListResponse(workflows=summaries, total=len(summaries))

    def _may_manage(self, workflow: Workflow, user_id: int) -> bool:
        """The creator, or an administrator (the only way to remove a leaver's workflow, S2-11)."""
        if workflow.creator_id == user_id:
            return True
        from services.auth.rbac_service import RBACService

        return RBACService(self.db).has_role(user_id, "admin")

    def _validate_child_run_secret_inputs(self, canvas_nodes: list[dict], user_id: int) -> None:
        """A Run Workflow step must not hold a secret input value in the saved canvas.

        Only workflows the saving user may see are looked at: for any other id the check is
        skipped (the run refuses it later), so a save never confirms that someone else's private
        workflow exists, nor reveals its name or input names.
        """

        def visible(workflow_id: int) -> Workflow | None:
            found = self.repo.get_by_id(workflow_id)
            if found is None:
                return None
            workflow = found[0]
            if workflow.visibility == "private" and workflow.creator_id != user_id:
                return None
            return workflow

        def lookup(workflow_id: int) -> list[dict] | None:
            workflow = visible(workflow_id)
            return None if workflow is None else list(workflow.static_attributes or [])

        def name_of(workflow_id: int) -> str:
            workflow = visible(workflow_id)
            return workflow.name if workflow else str(workflow_id)

        validate_start_workflow_secret_inputs(canvas_nodes, lookup, target_names=name_of)

    def get_workflow(self, workflow_id: int, user_id: int) -> WorkflowResponse:
        logger.debug("Getting workflow id=%s user_id=%s", workflow_id, user_id)
        result = self.repo.get_by_id(workflow_id)
        if result is None:
            raise NotFoundError("Workflow not found")
        workflow, creator_username = result
        if workflow.visibility == "private" and workflow.creator_id != user_id:
            raise AccessDeniedError("Access denied")
        return _to_response(workflow, creator_username)

    def create_workflow(
        self, data: WorkflowCreate, user_id: int, actor_username: str | None = None
    ) -> WorkflowResponse:
        logger.info("Creating workflow name=%r user_id=%s", data.name, user_id)
        canvas_nodes = _normalised_nodes(data.canvas_nodes, strict=True)
        _validate_no_cycle(canvas_nodes, data.canvas_edges)
        _validate_stop_here_not_in_fan_out(canvas_nodes, data.canvas_edges)
        _validate_fan_out_topology(canvas_nodes, data.canvas_edges)
        self._validate_child_run_secret_inputs(canvas_nodes, user_id)
        _validate_static_attributes(data.static_attributes)
        repaired_groups = _repair_orphan_groups(canvas_nodes, data.canvas_groups)
        try:
            workflow = self.repo.create(
                name=data.name,
                creator_id=user_id,
                description=data.description,
                folder=data.folder,
                visibility=data.visibility,
                canvas_nodes=canvas_nodes,
                canvas_edges=data.canvas_edges,
                canvas_groups=repaired_groups,
                static_attributes=[attr.model_dump() for attr in data.static_attributes],
                is_version_controlled=data.is_version_controlled,
            )
            result = self.repo.get_by_id(workflow.id)
            if result is None:
                logger.error(
                    "Workflow created but could not be retrieved id=%s user_id=%s",
                    workflow.id,
                    user_id,
                )
                raise RuntimeError("Workflow created but could not be retrieved")
            wf, creator_username = result
            logger.info("Workflow created id=%s name=%r user_id=%s", wf.id, wf.name, user_id)
            git_result = self.git.sync_workflow_to_git(
                wf, action="create", actor_username=actor_username
            )
            self.changes.record_change(
                wf.id,
                action="created",
                actor_id=user_id,
                actor_username=actor_username,
                git_result=git_result,
            )
            return _to_response(wf, creator_username, git_result)
        except DomainError:
            raise
        except Exception:
            logger.info(
                "Failed to create workflow name=%r user_id=%s", data.name, user_id, exc_info=True
            )
            raise

    def update_workflow(
        self,
        workflow_id: int,
        data: WorkflowUpdate,
        user_id: int,
        actor_username: str | None = None,
    ) -> WorkflowResponse:
        logger.info("Updating workflow id=%s user_id=%s", workflow_id, user_id)
        try:
            result = self.repo.get_by_id(workflow_id)
            if result is None:
                raise NotFoundError("Workflow not found")
            workflow, creator_username = result
            if not self._may_manage(workflow, user_id):
                raise AccessDeniedError("Access denied")
            return self._apply_update(
                workflow, creator_username, data, actor_id=user_id, actor_username=actor_username
            )
        except DomainError:
            raise
        except Exception:
            logger.info(
                "Failed to update workflow id=%s user_id=%s", workflow_id, user_id, exc_info=True
            )
            raise

    def update_workflow_for_ai_session(
        self,
        workflow_id: int,
        data: WorkflowUpdate,
        ai_user_id: int,
        actor_username: str,
    ) -> WorkflowResponse:
        """Same as update_workflow but skips the creator_id ownership check.

        Used only by backend/scripts/ai_workflow_apply.py. The time-boxed,
        human-granted workflow_ai_sessions row IS the authorization for this
        path, and it is verified here (AiWriteGate), not by the caller: the
        actor must be the active ai-assistant account, the workflow must have an
        unexpired consent row, and it must not have an enabled schedule.
        Ownership isn't checked because the whole point of the feature is the AI
        actor editing a workflow it doesn't own, on the human owner's explicit
        say-so.
        """
        logger.info("Updating workflow (AI session) id=%s ai_user_id=%s", workflow_id, ai_user_id)
        try:
            result = self.repo.get_by_id(workflow_id)
            if result is None:
                raise NotFoundError("Workflow not found")
            workflow, creator_username = result
            self.ai_gate.assert_may_write(workflow_id, ai_user_id, canvas=True)
            return self._apply_update(
                workflow,
                creator_username,
                data,
                actor_id=ai_user_id,
                actor_username=actor_username,
            )
        except DomainError:
            raise
        except Exception:
            logger.info(
                "Failed to update workflow (AI session) id=%s ai_user_id=%s",
                workflow_id,
                ai_user_id,
                exc_info=True,
            )
            raise

    def _apply_update(
        self,
        workflow: Workflow,
        creator_username: str | None,
        data: WorkflowUpdate,
        *,
        actor_id: int,
        actor_username: str | None,
    ) -> WorkflowResponse:
        updated_fields = data.model_dump(exclude_unset=True)
        expected = updated_fields.pop("expected_updated_at", None)
        if "folder" in updated_fields:
            # Same rule as create and the name check: no folder means the root.
            updated_fields["folder"] = updated_fields["folder"] or "/"
        self._assert_identity_free(workflow, updated_fields)
        if expected is not None and _as_utc(workflow.updated_at) != _as_utc(expected):
            raise ConflictError(
                "The workflow was changed by someone else (or by an AI session) after you opened it"
            )
        if updated_fields.get("canvas_nodes") is not None:
            updated_fields["canvas_nodes"] = _normalised_nodes(
                updated_fields["canvas_nodes"], strict=True
            )
        if "canvas_nodes" in updated_fields or "canvas_edges" in updated_fields:
            new_nodes = updated_fields.get("canvas_nodes", workflow.canvas_nodes)
            new_edges = updated_fields.get("canvas_edges", workflow.canvas_edges)
            _validate_no_cycle(new_nodes, new_edges)
            _validate_stop_here_not_in_fan_out(new_nodes, new_edges)
            _validate_fan_out_topology(new_nodes, new_edges)
        if "canvas_nodes" in updated_fields:
            self._validate_child_run_secret_inputs(updated_fields["canvas_nodes"], actor_id)
        if "static_attributes" in updated_fields:
            _validate_static_attributes(updated_fields["static_attributes"] or [])
        if "canvas_nodes" in updated_fields or "canvas_groups" in updated_fields:
            updated_fields["canvas_groups"] = _repair_orphan_groups(
                updated_fields.get("canvas_nodes", workflow.canvas_nodes),
                updated_fields.get("canvas_groups", workflow.canvas_groups),
            )
        workflow = self.repo.update(workflow, updated_fields)
        logger.info("Workflow updated id=%s actor_id=%s", workflow.id, actor_id)
        git_result = self.git.sync_workflow_to_git(
            workflow, action="update", actor_username=actor_username
        )
        self.changes.record_change(
            workflow.id,
            action="updated",
            actor_id=actor_id,
            actor_username=actor_username,
            git_result=git_result,
        )
        return _to_response(workflow, creator_username, git_result)

    def restore_workflow_version(
        self,
        workflow_id: int,
        commit_sha: str,
        user_id: int,
        actor_username: str | None = None,
    ) -> WorkflowResponse:
        logger.info(
            "Restoring workflow id=%s to commit=%s user_id=%s", workflow_id, commit_sha, user_id
        )
        result = self.repo.get_by_id(workflow_id)
        if result is None:
            raise NotFoundError("Workflow not found")
        workflow, _creator_username = result
        if not self._may_manage(workflow, user_id):
            raise AccessDeniedError("Access denied")
        if not workflow.is_version_controlled:
            raise ValidationFailedError("Workflow is not version controlled")
        update_data = self.git.restore_version(workflow, commit_sha)
        return self.update_workflow(workflow_id, update_data, user_id, actor_username)

    def get_workflow_git_history(
        self, workflow_id: int, user_id: int
    ) -> WorkflowGitHistoryResponse:
        workflow = self._get_readable_workflow(workflow_id, user_id)
        history = self.git.get_history(workflow)
        return WorkflowGitHistoryResponse(
            commits=history["commits"], repository_name=history["repository_name"]
        )

    def get_workflow_git_diff(
        self, workflow_id: int, commit_a: str, commit_b: str, user_id: int
    ) -> WorkflowGitDiffResponse:
        workflow = self._get_readable_workflow(workflow_id, user_id)
        diff = self.git.get_diff(workflow, commit_a, commit_b)
        return WorkflowGitDiffResponse(
            diff_lines=diff["diff_lines"],
            left_lines=diff["left_lines"],
            right_lines=diff["right_lines"],
            stats=diff["stats"],
        )

    def get_workflow_changes(self, workflow_id: int, user_id: int) -> WorkflowChangeListResponse:
        self._get_readable_workflow(workflow_id, user_id)
        return self.changes.list_changes(workflow_id)

    def update_notes(
        self, workflow_id: int, user_id: int, notes: str | None
    ) -> WorkflowNotesResponse:
        result = self.repo.get_by_id(workflow_id)
        if result is None:
            raise NotFoundError("Workflow not found")
        workflow, _creator_username = result
        if not self._may_manage(workflow, user_id):
            raise AccessDeniedError("Access denied")
        return self._apply_notes_update(workflow, notes)

    def update_notes_for_ai_session(
        self, workflow_id: int, notes: str | None, ai_user_id: int
    ) -> WorkflowNotesResponse:
        """Same as update_notes but skips the creator_id ownership check.

        Used only by backend/scripts/ai_workflow_apply.py, under the same active
        workflow_ai_sessions gate as update_workflow_for_ai_session, enforced
        here via AiWriteGate (see doc/ai_collaboration/PROCESS.md). Unlike a
        canvas edit, a notes edit has no actor/attribution tracking at all --
        update_notes doesn't record one for a human either (no WorkflowChange
        row, no git-mirror sync; notes are explicitly never synced to git), so
        ai_user_id exists only for logging symmetry with the canvas path, not
        because anything downstream reads it.
        """
        logger.info(
            "Updating workflow notes (AI session) id=%s ai_user_id=%s", workflow_id, ai_user_id
        )
        result = self.repo.get_by_id(workflow_id)
        if result is None:
            raise NotFoundError("Workflow not found")
        workflow, _creator_username = result
        self.ai_gate.assert_may_write(workflow_id, ai_user_id, canvas=False)
        return self._apply_notes_update(workflow, notes)

    def _apply_notes_update(self, workflow: Workflow, notes: str | None) -> WorkflowNotesResponse:
        workflow = self.repo.update(workflow, {"notes": notes})
        return WorkflowNotesResponse(notes=workflow.notes, updated_at=workflow.updated_at)

    def _get_readable_workflow(self, workflow_id: int, user_id: int) -> Workflow:
        result = self.repo.get_by_id(workflow_id)
        if result is None:
            raise NotFoundError("Workflow not found")
        workflow, _creator_username = result
        if workflow.visibility == "private" and workflow.creator_id != user_id:
            raise AccessDeniedError("Access denied")
        return workflow

    def _assert_identity_free(self, workflow: Workflow, fields: dict[str, Any]) -> None:
        """Refuse an update that moves the workflow onto another one's name, folder and visibility.

        Only a change is checked: a row that already shares its identity with another (a legacy
        ``""`` folder read as ``/``) can still be edited without touching the identity.
        """
        if not {"name", "folder", "visibility"} & fields.keys():
            return
        current = (workflow.name, workflow.folder or "/", workflow.visibility)
        target = (
            fields.get("name", workflow.name),
            fields.get("folder", workflow.folder) or "/",
            fields.get("visibility", workflow.visibility),
        )
        if target == current:
            return
        name, folder, visibility = target
        if self.repo.name_exists(
            name=name,
            folder=folder,
            visibility=visibility,
            creator_id=workflow.creator_id,
            exclude_id=workflow.id,
        ):
            raise ConflictError(f'A workflow named "{name}" already exists in folder "{folder}".')

    def check_name_available(
        self,
        *,
        name: str,
        folder: str,
        visibility: str,
        user_id: int,
        exclude_id: int | None = None,
    ) -> WorkflowNameCheckResponse:
        existing_id = self.repo.find_id_by_name(
            name=name,
            folder=folder or "/",
            visibility=visibility,
            creator_id=user_id,
        )
        if existing_id is None or existing_id == exclude_id:
            return WorkflowNameCheckResponse(available=True)
        if visibility == "public":
            msg = f'A public workflow named "{name}" already exists in folder "{folder or "/"}".'
        else:
            msg = f'You already have a private workflow named "{name}" in folder "{folder or "/"}".'
        return WorkflowNameCheckResponse(available=False, message=msg, existing_id=existing_id)

    def delete_workflow(self, workflow_id: int, user_id: int) -> None:
        result = self.repo.get_by_id(workflow_id)
        if result is None:
            raise NotFoundError("Workflow not found")
        workflow, _ = result
        if not self._may_manage(workflow, user_id):
            raise AccessDeniedError("Access denied")
        if RunRepository(self.db).has_active_runs(workflow_id):
            # Deleting would cascade-delete rows a worker is still writing (C1-06).
            raise ConflictError("The workflow has runs in progress; cancel or wait for them first")
        ScheduleService(self.db).delete_schedules_for_workflow_unchecked(workflow_id)
        BackgroundTierService(self.db).unpublish_for_workflow_unchecked(workflow_id)
        # The rows of its runs go with the workflow (ON DELETE CASCADE); their files do not.
        run_uuids = RunRepository(self.db).list_uuids_for_workflow(workflow_id)
        self.repo.delete(workflow)
        self._delete_run_files(workflow_id, run_uuids)

    @staticmethod
    def _delete_run_files(workflow_id: int, run_uuids: list[str]) -> None:
        """Remove artifacts and log-attribute files of deleted runs. The workflow is already gone,
        so a failure here is logged and left to the retention sweep, never raised."""
        if not run_uuids:
            return
        try:
            FilesystemArtifactService(settings.data_directory).delete_for_runs(set(run_uuids))
            for run_uuid in run_uuids:
                delete_run_dir(workflow_id, run_uuid)
        except OSError:
            logger.warning(
                "Could not remove the files of %s run(s) of deleted workflow %s",
                len(run_uuids),
                workflow_id,
                exc_info=True,
            )
