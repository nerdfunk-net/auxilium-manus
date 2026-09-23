#!/usr/bin/env python3
"""Apply an AI-authored patch to a workflow's canvas — the only way the
ai-assistant service account touches the database. See doc/ai_workflows/PROCESS.md.

Deliberately dumb infrastructure: identity, gating, persistence, validation,
reporting. It does not choose steps, resolve AI_DEFAULTS.md names, or lay out
node positions — that reasoning belongs to whatever calls this script.

Usage (from backend/, with the project venv)::

    python scripts/ai_workflow_apply.py --workflow-id 42 --patch-file patch.json

patch.json is a JSON object with any of "canvas_nodes", "canvas_edges",
"canvas_groups", "static_attributes" — each a full replacement of that field
(not a diff). Build it from a FRESH read of the workflow (this script always
re-fetches before applying; never trust a previous invocation's output).

Two gates must both pass before anything is written:
1. The ai-assistant user must be active (an admin flips this on in
   Settings -> Users — the global kill-switch).
2. An active (non-expired) workflow_ai_sessions row must exist for this
   workflow (the human enables this from the canvas toolbar — the
   per-workflow, time-boxed consent flag).

Prints a JSON report to stdout: the resulting workflow id/updated_at and the
Tier 1-2 validation findings for the applied state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


def _load_patch(patch_file: Path) -> dict[str, Any]:
    data = json.loads(patch_file.read_text())
    if not isinstance(data, dict):
        raise ValueError("Patch file must contain a JSON object")
    allowed = {"canvas_nodes", "canvas_edges", "canvas_groups", "static_attributes"}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"Patch file has unsupported field(s): {sorted(unknown)}")
    return data


def _fail(message: str) -> int:
    print(json.dumps({"error": message}))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-id", type=int, required=True)
    parser.add_argument("--patch-file", type=Path, required=True)
    args = parser.parse_args()

    try:
        patch = _load_patch(args.patch_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _fail(f"Could not read patch file: {exc}")

    from core.config import settings
    from core.database import SessionLocal
    from models.workflows import WorkflowUpdate
    from repositories.plugin_repository import PluginRepository
    from repositories.user_repository import UserRepository
    from repositories.workflow_ai_session_repository import WorkflowAiSessionRepository
    from repositories.workflow_repository import WorkflowRepository
    from services.auth.rbac_seed import AI_ASSISTANT_USERNAME
    from services.plugin_registry.plugin_registry_service import PluginRegistryService
    from services.workflow.workflow_service import WorkflowService
    from services.workflow.workflow_validation_service import WorkflowValidationService

    with SessionLocal() as db:
        ai_user = UserRepository(db).get_by_username(AI_ASSISTANT_USERNAME)
        if ai_user is None:
            return _fail(
                f"'{AI_ASSISTANT_USERNAME}' user does not exist — has the app been started "
                f"at least once since this feature was deployed?"
            )
        if not ai_user.is_active:
            return _fail(
                f"'{AI_ASSISTANT_USERNAME}' is disabled — an admin must activate it in "
                f"Settings -> Users before this script can run."
            )

        session_repo = WorkflowAiSessionRepository(db)
        active_session = session_repo.get_active_for_workflow(args.workflow_id)
        if active_session is None:
            return _fail(
                f"No active AI-updates session for workflow {args.workflow_id} — enable it "
                f"from the canvas toolbar first."
            )

        wf_result = WorkflowRepository(db).get_by_id(args.workflow_id)
        if wf_result is None:
            return _fail(f"Workflow {args.workflow_id} not found.")
        current_workflow, _ = wf_result

        plugin_service = PluginRegistryService(
            PluginRepository(plugins_file=settings.plugins_file)
        )
        registry = plugin_service.load_registry()
        merged_canvas_nodes = patch.get("canvas_nodes", current_workflow.canvas_nodes)
        validator = WorkflowValidationService(db, registry)
        validation = validator.validate(merged_canvas_nodes, acting_user_id=ai_user.id)

        try:
            data = WorkflowUpdate(**patch)
            updated = WorkflowService(db).update_workflow_for_ai_session(
                args.workflow_id,
                data,
                ai_user_id=ai_user.id,
                actor_username=AI_ASSISTANT_USERNAME,
            )
        except Exception as exc:
            return _fail(f"Failed to apply patch: {exc}")

        print(
            json.dumps(
                {
                    "workflow_id": updated.id,
                    "updated_at": updated.updated_at.isoformat(),
                    "validation": {
                        "has_errors": validation.has_errors,
                        "findings": [f.model_dump() for f in validation.findings],
                    },
                },
                indent=2,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
