"""Validates a workflow's canvas beyond the structural checks WorkflowService
already runs (cycle detection, stop-here placement, static attributes) — see
doc/ai_workflows/VALIDATION_PLAN.md. Tiers 1-4 in this pass:

- Tier 1 (schema conformance): a step's pluginConfig has every field its registry
  entry marks required — unless that field has a real default (registry
  `default:`, or the step's own `config.py::get_config()`), in which case
  leaving it blank is not an error: the step falls back to that default at
  save/run time. Never re-declares those defaults a third time here.
- Tier 2 (reference existence): credential_reference/git_repository_id/*_source_id
  values resolve for the acting user. Existing resolvers are reused, never
  re-implemented — CredentialsService, git_repository_loader, SettingsRepository.
- Tier 3 (capability flow): a static DAG walk checking every step's declared
  `requires`/`requires_parsed` is satisfiable from some upstream path, reusing
  the same rules the runtime guards enforce (services/workflow_context/guards.py)
  — `effective_produces` (config-aware, e.g. get-device-configs' produces
  depends on `config_format`), `consumes`, and graph resolution
  (services/execution/step_runner/graph_resolution.py: funnels, author-disabled
  steps, stop-here truncation, canvas-decoration filtering) so the walked graph
  matches exactly what StepRunner would execute.
- Tier 4 (named attribute-path wiring, advisory): a best-effort scan for
  `parsed.<node-id>...` references (services/workflow_context/node_result.py's
  addressing scheme) whose `<node-id>` is a real canvas node that is NOT
  upstream of the referencing step — the flat-key/stale-reference class of bug
  described in that module's docstring. Warnings only, never errors: dynamic
  keys and a coincidental output_key match make this provably incomplete.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from models.plugins import PluginDefinition
from models.workflow_context import Capability
from models.workflow_validation import ValidationFinding, WorkflowValidationResult
from repositories.settings_repository import SettingsRepository
from services.credentials.credentials_service import CredentialsService
from services.execution.graph import GraphCycleError, downstream_node_ids, topological_order
from services.execution.step_runner import graph_resolution as _gr
from services.git.repository_service import GitRepositoryService
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from services.workflow_context.guards import StepCapabilitySpec, effective_produces
from services.workflow_context.registry import capability_spec_from_plugin

# Outcome names whose branch only ever carries devices a step could NOT
# process — mirrors frontend/.../utils/capability-graph.ts's
# FAILURE_CLASS_OUTCOMES exactly (same reasoning: "mismatch" is deliberately
# excluded, it's a normal successful result like compare-data's
# comparison_diff, not a per-device failure). A finding on such an outcome's
# downstream path must not be silenced by capabilities the step only
# guarantees on its success path.
_FAILURE_CLASS_OUTCOMES = frozenset({"failure", "fail", "error"})


@dataclass(frozen=True)
class _CapabilityState:
    capabilities: frozenset[Capability]
    parsed_keys: frozenset[str]


_EMPTY_CAPABILITY_STATE = _CapabilityState(frozenset(), frozenset())


def _is_failure_class_outcome(name: str) -> bool:
    return name.strip().lower() in _FAILURE_CLASS_OUTCOMES


def _intersect_capability_states(states: list[_CapabilityState]) -> _CapabilityState:
    """Meet operation at a join (multiple parents): only what EVERY incoming
    branch guarantees survives. Deliberately conservative — a capability
    produced on only one branch of an unresolved fork isn't guaranteed for a
    device that could have arrived via the other one. See
    doc/ai_workflows/VALIDATION_PLAN.md's Tier 3 section."""
    if not states:
        return _EMPTY_CAPABILITY_STATE
    capabilities = states[0].capabilities
    parsed_keys = states[0].parsed_keys
    for state in states[1:]:
        capabilities = capabilities & state.capabilities
        parsed_keys = parsed_keys & state.parsed_keys
    return _CapabilityState(capabilities, parsed_keys)


# Matches "parsed.<candidate>" wherever it appears in a config string —
# standalone (route-on-attribute's attribute_path, update-attribute's
# source_path/destination_path, list-contains, ...) or inside a Jinja
# placeholder (render-jinja-template, run-command's command template: both
# expose "parsed" as a top-level namespace — see
# services/workflow_context/device_template.py::build_template_context and
# workflow_steps/common/jinja_render.py::build_jinja_context, neither of
# which nests it under "device."). `\b` matches equally after a space, "{",
# or "." (e.g. inside "device.parsed.x", if that spelling is ever used), so
# this needs no separate Jinja-aware branch.
_PARSED_PATH_CANDIDATE_RE = re.compile(r"\bparsed\.([A-Za-z0-9_-]+)")

# Step kinds whose executor nests its own per-run result under its own canvas
# node id via services.workflow_context.node_result.set_node_result — i.e.
# `parsed.<node_id>.<key>` only resolves to something real when `<node_id>`
# is THAT step's own id. Built from `grep -rl set_node_result
# workflow_steps/*/executor.py`, not the registry (registry.yaml's
# `output_key` field is reused, ambiguously, for both this node-id-keyed
# convention and a plain user-chosen `parsed.<output_key>` namespace with no
# node-id prefix — e.g. parse-cisco-config — so it can't tell the two apart;
# the executor import is the one unambiguous, current signal). Keep this in
# sync if a new step starts/stops calling set_node_result.
_NODE_SCOPED_PARSED_STEP_KINDS = frozenset(
    {
        "batfish-validate-facts",
        "compare-data",
        "compare-pyats-snapshot",
        "configure-replace-config",
        "filter-output",
        "list-contains",
        "login-successful",
        "merge-content",
        "reachable",
        "route-on-content",
        "update-content",
    }
)


def _iter_config_strings(value: Any) -> Iterator[str]:
    """Recursively yield every string leaf in a pluginConfig-shaped value
    (dicts, lists, and nested combinations thereof — e.g. update-attribute's
    `attributes: [{...}, {...}]`)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_config_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_config_strings(item)


# Mirrors frontend/.../workflow-import.ts's SHARED_SECRET_STEP_KINDS/GENERIC_STEP_KINDS —
# which Credential.type a step's credential_reference resolves against. Unlisted
# kinds default to "ssh", matching that module's documented default.
_SHARED_SECRET_STEP_KINDS = frozenset({"encrypt-attribute", "decrypt-attribute"})
_GENERIC_STEP_KINDS = frozenset({"add-pyats-testbed"})

# Credential.type values each inferred credential_type accepts — mirrors
# services/credentials/manager.py's _SSH_TYPES/_GENERIC_TYPES/_SHARED_SECRET_TYPES.
_ACCEPTED_CREDENTIAL_TYPES: dict[str, frozenset[str]] = {
    "ssh": frozenset({"ssh"}),
    "generic": frozenset({"ssh", "generic"}),
    "shared_secret": frozenset({"shared_secret"}),
}

# pluginConfig key -> Settings row prefix, for the four `*_source_id` fields.
_SOURCE_ID_FIELDS: dict[str, str] = {
    "nautobot_source_id": "nautobot",
    "mattermost_source_id": "mattermost",
    "batfish_source_id": "batfish",
    "pyats_source_id": "pyats",
}


def _infer_credential_type(step_kind: str) -> str:
    if step_kind in _SHARED_SECRET_STEP_KINDS:
        return "shared_secret"
    if step_kind in _GENERIC_STEP_KINDS:
        return "generic"
    return "ssh"


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


class WorkflowValidationService:
    def __init__(self, db: Session, plugin_registry_service: PluginRegistryService) -> None:
        self.db = db
        self._plugin_registry_service = plugin_registry_service
        self._plugins_by_id: dict[str, PluginDefinition] = {
            plugin.id: plugin for plugin in plugin_registry_service.get_registry().plugins
        }
        self._settings_repo = SettingsRepository(db)
        # get_plugin_config() dynamically imports each step's config.py on
        # every call — memoize per plugin id so a workflow with many nodes of
        # the same kind (e.g. several run-command steps) only pays that cost
        # once per validate() call, not once per node.
        self._config_defaults_cache: dict[str, dict[str, Any]] = {}

    def _config_default(self, plugin_id: str, field_name: str) -> Any:
        if plugin_id not in self._config_defaults_cache:
            # None means "unknown plugin id" (never true here — the caller
            # already resolved `plugin` from the same registry); {} means "no
            # config.py / no get_config() default", equally fine to cache.
            self._config_defaults_cache[plugin_id] = (
                self._plugin_registry_service.get_plugin_config(plugin_id) or {}
            )
        return self._config_defaults_cache[plugin_id].get(field_name)

    def validate(
        self,
        canvas_nodes: list[dict[str, Any]],
        canvas_edges: list[dict[str, Any]] | None = None,
        *,
        acting_user_id: int | None,
    ) -> WorkflowValidationResult:
        findings: list[ValidationFinding] = []

        for node in canvas_nodes:
            node_id = node.get("id")
            data = node.get("data")
            if not isinstance(data, dict):
                continue
            kind = data.get("kind")
            if not isinstance(kind, str):
                continue

            plugin = self._plugins_by_id.get(kind)
            if plugin is None:
                findings.append(
                    ValidationFinding(
                        node_id=node_id,
                        tier=1,
                        severity="error",
                        code="unknown_step_kind",
                        message=f"Step kind '{kind}' is not in the registry.",
                    )
                )
                continue

            plugin_config = data.get("pluginConfig")
            plugin_config = plugin_config if isinstance(plugin_config, dict) else {}

            findings.extend(self._tier1_schema(node_id, plugin, plugin_config))
            findings.extend(
                self._tier2_references(node_id, kind, plugin_config, acting_user_id)
            )

        findings.extend(self._tier3_capability_flow(canvas_nodes, canvas_edges or []))
        findings.extend(self._tier4_attribute_path_wiring(canvas_nodes, canvas_edges or []))

        return WorkflowValidationResult(
            findings=findings, has_errors=any(f.severity == "error" for f in findings)
        )

    def _tier1_schema(
        self, node_id: str | None, plugin: PluginDefinition, plugin_config: dict[str, Any]
    ) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        for field in plugin.metadata.configuration_input:
            if not field.required:
                continue
            if not _is_blank(plugin_config.get(field.name)):
                continue
            if not _is_blank(field.default):
                continue  # registry-declared default — the step falls back to it
            if not _is_blank(self._config_default(plugin.id, field.name)):
                continue  # config.py's get_config() default — same reasoning
            findings.append(
                ValidationFinding(
                    node_id=node_id,
                    tier=1,
                    severity="error",
                    code="missing_required_field",
                    message=(
                        f"'{field.name}' is required for step '{plugin.name}' "
                        f"but is missing or empty."
                    ),
                )
            )
        return findings

    def _tier2_references(
        self,
        node_id: str | None,
        step_kind: str,
        plugin_config: dict[str, Any],
        acting_user_id: int | None,
    ) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []

        credential_reference = plugin_config.get("credential_reference")
        if isinstance(credential_reference, str) and credential_reference.strip():
            findings.extend(
                self._check_credential_reference(
                    node_id, step_kind, credential_reference, acting_user_id
                )
            )

        git_repository_id = plugin_config.get("git_repository_id")
        if git_repository_id not in (None, ""):
            findings.extend(self._check_git_repository(node_id, git_repository_id))

        for config_key, source_type in _SOURCE_ID_FIELDS.items():
            source_id = plugin_config.get(config_key)
            if isinstance(source_id, str) and source_id.strip():
                findings.extend(self._check_source_id(node_id, source_type, source_id))

        return findings

    def _check_credential_reference(
        self,
        node_id: str | None,
        step_kind: str,
        name: str,
        acting_user_id: int | None,
    ) -> list[ValidationFinding]:
        # Metadata existence check only — never decrypts. CredentialManager's
        # .ssh()/.generic()/.shared_secret() decrypt the secret as a side
        # effect of resolving it, which POST /workflows/{id}/validate must not
        # trigger: that endpoint is gated on workflows:read, not
        # credentials:read/credentials:reveal. Mirrors
        # services/execution/reference_resolver.py's
        # _CredentialReferenceResolver (existence/type/status via
        # CredentialsService.list_credentials, private-over-global
        # precedence), generalized from "ssh only" to the three credential
        # types a step kind can require.
        def _finding(code: str, message: str) -> list[ValidationFinding]:
            return [
                ValidationFinding(
                    node_id=node_id, tier=2, severity="error", code=code, message=message
                )
            ]

        credential_type = _infer_credential_type(step_kind)
        accepted_types = _ACCEPTED_CREDENTIAL_TYPES[credential_type]

        credentials = CredentialsService(self.db).list_credentials(
            include_expired=True, source="general", acting_user_id=acting_user_id
        )
        matches = [item for item in credentials if item["name"] == name]
        if not matches:
            return _finding(
                "credential_reference_not_found",
                f"No credential named '{name}' is visible to you.",
            )

        match = next((c for c in matches if c.get("visibility") == "private"), matches[0])
        if match["type"] not in accepted_types:
            return _finding(
                "credential_reference_wrong_type",
                f"Credential '{name}' is type '{match['type']}', "
                f"expected one of {sorted(accepted_types)}.",
            )
        if match["status"] == "expired":
            return _finding("credential_reference_expired", f"Credential '{name}' is expired.")
        return []

    def _check_git_repository(
        self, node_id: str | None, git_repository_id: Any
    ) -> list[ValidationFinding]:
        # Deliberately calls GitRepositoryService directly rather than
        # workflow_steps.common.git_repository_loader.load_git_repository — R9
        # forbids services/* from importing workflow_steps.* (see
        # tests/unit/test_production_hardening.py::TestR9StepBoundary), so this
        # replicates that helper's three existence checks against the same
        # underlying service instead of importing it.
        def _finding(message: str) -> list[ValidationFinding]:
            return [
                ValidationFinding(
                    node_id=node_id,
                    tier=2,
                    severity="error",
                    code="git_repository_not_found",
                    message=message,
                )
            ]

        try:
            repository_id = int(git_repository_id)
        except (TypeError, ValueError):
            return _finding(f"Git repository id {git_repository_id!r} is not a valid integer.")

        repository = GitRepositoryService(self.db).get_repository(repository_id)
        if repository is None:
            return _finding(f"Git repository {repository_id} not found.")
        if not repository.get("is_active", True):
            return _finding(f"Git repository '{repository['name']}' is not active.")
        if not str(repository.get("url") or "").strip():
            return _finding(f"Git repository '{repository['name']}' has no URL configured.")
        return []

    def _check_source_id(
        self, node_id: str | None, source_type: str, source_id: str
    ) -> list[ValidationFinding]:
        key = f"sources.{source_type}.{source_id}"
        if self._settings_repo.get_by_key(key) is None:
            return [
                ValidationFinding(
                    node_id=node_id,
                    tier=2,
                    severity="error",
                    code="source_not_found",
                    message=f"{source_type} source '{source_id}' is not configured.",
                )
            ]
        return []

    def _is_executable_node(self, node: dict[str, Any]) -> bool:
        """Mirrors graph_resolution.is_executable_node without constructing a
        PluginRegistryService — this class already indexes plugins by id.
        Unknown kinds stay executable (Tier 1 already flags them separately;
        dropping them here would just hide the node from the Tier 3 walk)."""
        data = node.get("data") or {}
        kind = data.get("kind")
        if not isinstance(kind, str) or not kind:
            return True
        plugin = self._plugins_by_id.get(kind)
        if plugin is None:
            return True
        return plugin.executable

    def _tier3_capability_flow(
        self, canvas_nodes: list[dict[str, Any]], canvas_edges: list[dict[str, Any]]
    ) -> list[ValidationFinding]:
        try:
            nodes, edges = _gr.resolve_funnels(canvas_nodes, canvas_edges)
            nodes, edges = _gr.resolve_disabled_steps(nodes, edges)
            nodes, edges = _gr.resolve_stop_here(nodes, edges)
        except ValueError as exc:
            # Malformed funnel wiring (wrong outgoing-edge count, funnel
            # chaining) — a real problem, but structural, not a capability
            # one; report it rather than silently dropping Tier 3 entirely.
            return [
                ValidationFinding(
                    node_id=None, tier=3, severity="error", code="graph_resolution_failed",
                    message=str(exc),
                )
            ]

        executable_nodes = [n for n in nodes if self._is_executable_node(n)]
        executable_ids = {n["id"] for n in executable_nodes if "id" in n}
        executable_edges = [
            e
            for e in edges
            if e.get("source") in executable_ids and e.get("target") in executable_ids
        ]

        try:
            order = topological_order(executable_nodes, executable_edges)
        except GraphCycleError:
            # Cycles are a save-time hard error (WorkflowService._validate_no_cycle)
            # for anything actually saved; an unsaved draft sent straight to
            # this endpoint could still contain one. Capability flow is
            # undefined over a cycle, so report it plainly instead of
            # attempting a walk that can't terminate meaningfully.
            return [
                ValidationFinding(
                    node_id=None, tier=3, severity="error", code="graph_cycle",
                    message="Workflow graph contains a cycle — capability-flow validation skipped.",
                )
            ]

        incoming_by_target: dict[str, list[dict[str, Any]]] = {}
        for edge in executable_edges:
            incoming_by_target.setdefault(edge.get("target", ""), []).append(edge)

        # (node_id, outcome_handle) -> capability state guaranteed on that
        # outgoing edge, filled in as the walk proceeds in dependency order.
        outcome_state: dict[tuple[str, str], _CapabilityState] = {}
        findings: list[ValidationFinding] = []

        for node in order:
            node_id = node.get("id", "")
            data = node.get("data") or {}
            kind = data.get("kind")
            plugin = self._plugins_by_id.get(kind) if isinstance(kind, str) else None
            if plugin is None:
                continue  # unknown kind — Tier 1 already flags this node

            parent_edges = incoming_by_target.get(node_id, [])
            if parent_edges:
                parent_states = [
                    outcome_state.get(
                        (edge.get("source", ""), edge.get("sourceHandle") or "success"),
                        _EMPTY_CAPABILITY_STATE,
                    )
                    for edge in parent_edges
                ]
                input_state = _intersect_capability_states(parent_states)
            else:
                input_state = _EMPTY_CAPABILITY_STATE

            spec: StepCapabilitySpec = capability_spec_from_plugin(plugin)
            plugin_config = data.get("pluginConfig")
            plugin_config = plugin_config if isinstance(plugin_config, dict) else {}

            missing_capabilities = set(spec.requires) - input_state.capabilities
            if missing_capabilities:
                findings.append(
                    ValidationFinding(
                        node_id=node_id,
                        tier=3,
                        severity="error",
                        code="missing_capability",
                        message=(
                            f"Step '{plugin.name}' requires "
                            f"{sorted(c.value for c in missing_capabilities)}, but no upstream "
                            f"step on every path reaching it guarantees that."
                        ),
                    )
                )
            missing_parsed = set(spec.requires_parsed) - input_state.parsed_keys
            if missing_parsed:
                findings.append(
                    ValidationFinding(
                        node_id=node_id,
                        tier=3,
                        severity="error",
                        code="missing_parsed_key",
                        message=(
                            f"Step '{plugin.name}' requires parsed key(s) "
                            f"{sorted(missing_parsed)}, but no upstream step on every path "
                            f"reaching it guarantees producing them."
                        ),
                    )
                )

            produces = effective_produces(spec=spec, step_type=plugin.id, config=plugin_config)
            success_state = _CapabilityState(
                (input_state.capabilities - spec.consumes) | produces,
                input_state.parsed_keys | frozenset(plugin.produces_parsed),
            )

            outgoing_handles = {
                edge.get("sourceHandle") or "success"
                for edge in executable_edges
                if edge.get("source") == node_id
            }
            handle_names = {outcome.name for outcome in plugin.outcomes} | outgoing_handles
            if not handle_names:
                handle_names = {"success"}
            for handle in handle_names:
                outcome_state[(node_id, handle)] = (
                    input_state if _is_failure_class_outcome(handle) else success_state
                )

        return findings

    def _tier4_attribute_path_wiring(
        self, canvas_nodes: list[dict[str, Any]], canvas_edges: list[dict[str, Any]]
    ) -> list[ValidationFinding]:
        """Best-effort, advisory only (see module docstring). Deliberately
        does NOT resolve funnels/disabled-steps/stop-here first, unlike Tier
        3 — a reference from inside a currently-disabled step is still worth
        flagging, and "ancestor on the raw canvas" is what a human editing by
        hand actually sees. Only checks `parsed.<node-id>` references (the
        node_result.py addressing scheme); attribute_bags bag names are
        free-form user strings unrelated to node ids, so there is no
        equivalent structural check for those — see the module docstring's
        Tier 4 scoping note."""
        node_kind_by_id: dict[str, str] = {}
        for node in canvas_nodes:
            node_id = node.get("id")
            kind = (node.get("data") or {}).get("kind")
            if isinstance(node_id, str) and isinstance(kind, str):
                node_kind_by_id[node_id] = kind

        findings: list[ValidationFinding] = []
        for node in canvas_nodes:
            node_id = node.get("id")
            if not isinstance(node_id, str):
                continue
            plugin_config = (node.get("data") or {}).get("pluginConfig")
            if not isinstance(plugin_config, dict):
                continue

            candidates: set[str] = set()
            for text in _iter_config_strings(plugin_config):
                candidates.update(_PARSED_PATH_CANDIDATE_RE.findall(text))

            for candidate in sorted(candidates):
                if candidate == node_id:
                    continue  # a step reading its own node-scoped result is fine
                referenced_kind = node_kind_by_id.get(candidate)
                if referenced_kind is None or referenced_kind not in _NODE_SCOPED_PARSED_STEP_KINDS:
                    # Not a node-id reference at all (an ordinary output_key
                    # namespace, e.g. parse-cisco-config) — never guess.
                    continue

                if node_id not in downstream_node_ids(candidate, canvas_nodes, canvas_edges):
                    findings.append(
                        ValidationFinding(
                            node_id=node_id,
                            tier=4,
                            severity="warning",
                            code="stale_node_output_reference",
                            message=(
                                f"References 'parsed.{candidate}…', which is step "
                                f"'{candidate}''s own result, but that step is not "
                                f"upstream of this one on any path — this reference "
                                f"will resolve to nothing at run time."
                            ),
                        )
                    )

        return findings
