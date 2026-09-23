# Workflow Validation — Implementation Plan

## Why

Today, `WorkflowService.create_workflow` / `update_workflow`
(`backend/services/workflow/workflow_service.py:197-288`) runs exactly three checks
before persisting: `_validate_no_cycle`, `_validate_stop_here_not_in_fan_out`,
`_validate_static_attributes`. Nothing checks a step's `pluginConfig` against its
schema, whether referenced credentials/repos/sources/inventories exist, or whether a
step's declared `requires` can actually be satisfied by anything upstream. A
structurally valid but semantically broken workflow saves without complaint and only
fails at run time — against real devices, git remotes, or change requests.

This is needed for both the human editing the canvas by hand and for AI-assisted
generation (`PROCESS.md`) — same validator, two callers.

## Four tiers, by confidence

| Tier | Checks | Confidence | New work? |
|---|---|---|---|
| 1. Schema conformance | Required `pluginConfig` fields present; rough `data_type` match; per-step conditional rules | High, mechanical | Yes |
| 2. Reference existence | `credential_reference`, `git_repository_id`, `*_source_id`, `inventory_id`/`inventory_param` actually resolve for this user | High, mechanical | Reuses existing resolvers |
| 3. Capability flow | A step's `requires`/`requires_parsed` is satisfiable from some upstream path | High — mirrors an existing runtime guard | Mostly reuse |
| 4. Named attribute-path wiring | A Jinja/dot-path reference plausibly points at something an ancestor produces | Best-effort only | Yes, heuristic |

Tiers 1–3 can be **blocking** (hard errors). Tier 4 is **advisory** (warnings) — it
can't be complete (dynamic keys, runtime-only branches are the same sharp edge the
`device.parsed` flat-key issue hit).

---

## Tier 1 — Schema conformance

**Source of truth:** `backend/workflow_steps/registry.yaml`, loaded as
`PluginRegistry`/`PluginDefinition`/`PluginIOField` (`backend/models/plugins.py`).
Each `PluginDefinition.metadata.configuration_input` is a `list[PluginIOField]` —
`name`, `data_type`, `required`, `default`, `example`.

**Work:**
- A generic checker: for each canvas node, look up its `PluginDefinition` by `kind`,
  and for each `configuration_input` entry, check `required` fields are present in
  `pluginConfig` and roughly type-match `data_type` (string/number/boolean/object/array).
- **Conditional requirements are the catch.** Several steps have fields that are only
  required given another field's value — e.g. `get-nautobot-devices`:
  `inventory_param` is required only when `inventory_source == "run_param"`.
  `registry.yaml`'s flat `configuration_input` list can't express that. Two options:
  - (a) extend `PluginIOField` with an optional declarative condition
    (`required_if: {field, equals}`) — works for simple cases, keeps the checker
    generic.
  - (b) an optional `validate_config(config: dict) -> list[str]` hook per step
    package (`workflow_steps/{step}/validate.py`), called when present, falling back
    to pure registry-driven checks otherwise. More flexible, more per-step code.
  - **Recommendation:** start with (a) for the common "field X required when field Y
    equals Z" shape (covers `get-nautobot-devices`, likely most others); fall back to
    (b) only for steps where that's not expressive enough (check as each step is
    ported — don't pre-build the hook for steps that don't need it).

---

## Tier 2 — Reference existence

**Do not re-implement resolution.** Reuse, in check-only mode (existence check, no
side effects, no secret decryption):
- `workflow_steps/common/git_repository_loader.py::load_git_repository` for
  `git_repository_id`.
- The credential resolver already used by executors, for `credential_reference` —
  metadata existence only (name + type match), never `credentials:reveal`.
- `services/execution/reference_resolver.py` for `type: "reference"` static
  attributes (`ref_kind` inventory/credential) — this already has a "does this
  resolve for the given user" mode since it's used at schedule-dispatch time
  (`doc/ARCHITECTURAL_OVERVIEW.md` → "Scheduling", step 4).
- A small new existence check for `*_source_id` fields against `Settings` rows
  matching `sources.<type>.<id>` (four fields: `nautobot_source_id`,
  `mattermost_source_id`, `batfish_source_id`, `pyats_source_id`; `ise_source_id` if
  used).

**Work:** one function per reference kind, each returning "exists" / "not found" /
"exists but not visible to this user" (the last one matters for private credentials —
same distinction `workflow-import.ts`'s remap logic already makes).

---

## Tier 3 — Capability flow (the good news) — ✅ built 2026-09-23

**This already exists as a runtime mechanism.** `services/workflow_context/guards.py`
has `StepCapabilitySpec`, `effective_produces(spec, step_type, config)`, and
`pre_step_guard`/`post_step_guard` — all pure functions over `Capability` enum values
(`RUNNING_CONFIG`, `STARTUP_CONFIG`, `PARSED`, `ATTRIBUTES`, `IDENTITY`, …), no device
I/O required to evaluate `effective_produces`. Today they only run inside
`StepRunner` during an actual execution, raising `RuntimeError` (which aborts the run)
on mismatch.

**What was actually built** (`WorkflowValidationService._tier3_capability_flow`,
`backend/services/workflow/workflow_validation_service.py`):
1. Resolve the graph exactly like `StepRunner` does before walking it — reusing
   `services/execution/step_runner/graph_resolution.py`'s `resolve_funnels`,
   `resolve_disabled_steps`, `resolve_stop_here`, and a local
   executable-node filter (same rule as `is_executable_node`, without needing a
   `PluginRegistryService`) — then `services/execution/graph.py::topological_order`.
2. Walk in topological order, tracking `(capabilities, parsed_keys)` per node.
   A node with multiple parents takes the **intersection** across incoming branches
   (`_intersect_capability_states`): a capability produced on only one branch of an
   unresolved fork isn't guaranteed for a device that could have taken the other one.
   This turned out to already be a settled question, not a new one to answer from
   scratch — it's exactly what the frontend's `capability-graph.ts` (used for
   canvas connection validation) already does at edge-draw time; the backend walker
   ports that same join rule rather than inventing a second one, while getting
   `effective_produces`' config-awareness (something the frontend's naive
   `node.data.produces` doesn't have — e.g. `get-device-configs` only truly
   guarantees `startup_config` when `config_format == "startup"`) as a bonus from
   reusing the real backend function.
3. `pre_step_guard`'s runtime "vacuous when no devices selected yet" shortcut is
   **deliberately not replicated**: a step requiring a capability with nothing
   upstream to produce it is exactly the AI-authored wiring bug this tier exists to
   catch, and a hand-built canvas can never reach that state (`WorkflowCanvas`'s
   `isValidConnection` already blocks the edge) — only a script-authored
   `canvas_nodes`/`canvas_edges` patch can, which is precisely the audience Tier 3
   serves.
4. A step's `produces`/`produces_parsed` are only counted on outcomes other than
   `failure`/`fail`/`error` (same `FAILURE_CLASS_OUTCOMES` set as
   `capability-graph.ts`, deliberately excluding `mismatch`) — a step wired off its
   failure branch inherits its *input* state, not what it would have produced on
   success.

This reuses real, already-tested logic instead of building a parallel capability
model. 12 unit tests cover joins, failure-outcome branches, `consumes`,
`effective_produces`' config-awareness, `requires_parsed`, and disabled/cyclic/
decoration graph handling. **Not yet manually verified live in a browser** — see
`PROCESS.md`.

---

## Tier 4 — Named attribute-path wiring (advisory)

Lower priority, ship last. Best-effort static check that a Jinja
`{{ device.attribute_bags.<node-id>.<key> }}` / dot-path config value references a
node that is actually an ancestor on that branch, and — if that node's `output_key`
(or similar) is itself known at generation time — that the key name matches. Flag as
a **warning**, never a hard error: dynamic keys and runtime-only branches make this
provably incomplete. This is the same class of bug the `device.parsed` flat-key nesting
fix (see memory) was really about — a plausible-looking reference that silently
resolves to nothing.

---

## Where it plugs in

One new `WorkflowValidationService`
(`backend/services/workflow/workflow_validation_service.py`), consuming the registry,
the reused resolvers, and the graph utilities above. Three call sites:

1. **Explicit validate endpoint** — `POST /api/workflows/{id}/validate` (or a
   variant taking an unsaved draft payload for the canvas's "Validate" button before
   the first save). Returns `WorkflowValidationResult`: a list of findings, each
   `{node_id, tier, severity, code, message}`. This is the primary UI surface for
   human users — your point 2 — and the last step before Run in the AI-collaboration
   loop (`PROCESS.md`).
2. **Non-blocking pass at save time**, riding back on the response the same way
   `WorkflowGitSyncStatus`/`git_sync` already does (`models/workflows.py`,
   `WorkflowResponse.git_sync`) — add a parallel `validation: WorkflowValidationResult
   | None` field. Never blocks the save itself; a human should be able to save a
   work-in-progress workflow.
3. **Optional pre-run gate** — before `RunService.trigger_run` dispatches, run Tiers
   1–3 and block on hard errors (Tier 4 stays advisory even here). Cheap since it's
   the same service; decide at implementation time whether this is a hard block or a
   confirmable warning — probably hard block, since a Tier 1–3 failure means the run
   would fail anyway, just later and against a live device.

---

## Frontend surfacing (minimal, needed before the AI loop is usable)

- A "Validate" action in the canvas toolbar, calling the endpoint and rendering
  findings in a panel (grouped by node).
- Per-node error/warning badges, consistent with the existing outcome-handle color
  convention (`doc/WORKFLOW-STEPS-STYLE_GUIDE.md`) — red badge for hard errors,
  yellow for Tier 4 warnings. No new node layout, just a badge overlay — the style
  guide's "never fork the node layout" rule applies here too.
- `Run` button disabled (or requires confirmation) when unresolved Tier 1–3 errors
  exist on the current saved state.

---

## Build order

1. ✅ **Tier 1 + Tier 2 + validate endpoint (no UI yet)** — the mechanical, highest
   -value chunk. Catches the large majority of "AI guessed a config field wrong" bugs.
2. ✅ **Minimal UI** (Validate button, findings panel, node badges) — needed for the
   human side of the collaboration loop; can ship right after step 1 since it only
   needs the endpoint to exist. Verified live in a browser (2026-09-23).
3. ✅ **Tier 3 (capability-flow walker)** — built 2026-09-23. Reuses
   `services/workflow_context/guards.py` (`effective_produces`,
   `StepCapabilitySpec.consumes`) and `services/execution/step_runner/graph_resolution.py`
   (funnels, disabled steps, stop-here, decoration filtering) — the graph it walks
   matches exactly what `StepRunner` would execute. Joins use **intersection** (a
   capability on only one incoming branch doesn't count), which also settles the
   "fan-in join semantics" question this bullet originally flagged as open — see
   `PROCESS.md`'s corresponding update entry for the full reasoning, including why
   `pre_step_guard`'s runtime "vacuous when no devices yet" shortcut is deliberately
   NOT replicated here. **Not yet manually verified live in a browser.**
4. **Pre-run gate** — wire the same service into `RunService.trigger_run`.
5. **Tier 4 (advisory)** — lowest priority, ship once the loop has real usage and
   you can see which false positives/negatives actually matter in practice.

## Testing

- Unit tests per tier, using the existing `registry.yaml` fixtures/test patterns
  already in `tests/unit/test_plugin_config_loader.py` /
  `test_plugin_registry_capabilities.py` as a starting point.
- At least one integration test per tier against a workflow built from the actual
  gallery examples (`contributing-data/workflow-gallery/*.json`) — these are known-good,
  so the validator should report zero hard errors on all of them; a red gallery
  example means a bug in the checker, not the workflow.
