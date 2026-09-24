# AI-Human Workflow Collaboration — Process

## Status as of 2026-09-23 — read this first if resuming in a new session

The full loop described below is **implemented and verified working live** (not just
unit-tested) on a deliberately read-only use case: enable AI updates on a real
workflow → an AI-driven `backend/scripts/ai_workflow_apply.py` invocation adds a
Nautobot-inventory step, then a dependent attribute-lookup step → the open canvas
tab's polling banner appears on its own → clicking Reload redraws the canvas in place
and the banner clears. Two real bugs were found only by testing this live in a
browser and are fixed — see "Bugs found and fixed during live testing" below, they
are worth reading before assuming anything else works by inspection alone.

**Nothing is committed.** Everything is on branch `feature/ai-assistent`, uncommitted,
matching the file inventory in "What's actually been built" below.

**A follow-up code review found four more real bugs** (not caught by live testing —
disable-leaves-a-session-active, a plain restore falsely triggering the banner, and
a non-owner being able to grant AI consent on a public workflow — plus one security
issue, validation decrypting credential secrets it should only check for existence).
All four are fixed and verified — see items 7–10 in "Bugs found and fixed" below.

**Update 2026-09-23 (later session):** the minimal in-canvas "Validate" UI (one of
the two motivations for building validation at all — see `VALIDATION_PLAN.md`'s
"Frontend surfacing") is now built: a topbar "Validate" button, a findings dialog
grouped by node, and red/yellow per-node badges on the canvas. See "What's actually
been built" for the file list. **Verified live in a browser by the user**: an
intentionally-introduced config error was correctly caught and surfaced by the
Validate button.

**Update 2026-09-23 (same session, continued):** Tier 3 (capability-flow) validation
is now built — `WorkflowValidationService._tier3_capability_flow` does a static DAG
walk reusing the real runtime rules from `services/workflow_context/guards.py`
(`effective_produces`, `StepCapabilitySpec.consumes`) and the same graph-resolution
pipeline `StepRunner` walks at execution time
(`services/execution/step_runner/graph_resolution.py`: funnel splicing,
author-disabled steps, stop-here truncation, canvas-decoration filtering) — so the
walked graph matches exactly what would actually execute. Joins (multiple parent
edges) use **intersection**: a capability guaranteed on only one incoming branch is
not counted, since a device could have arrived via the other one — this is a
deliberate, documented departure from a literal port of the frontend's
`capability-graph.ts` (which the same reasoning already uses) and from
`pre_step_guard`'s runtime "vacuous when no devices selected yet" shortcut, which
is intentionally NOT replicated: a step requiring a capability with nothing upstream
to produce it is exactly the AI-authored wiring bug this tier exists to catch, and a
hand-built canvas can never reach that state (`WorkflowCanvas`'s `isValidConnection`
already blocks the edge) — only a script-authored patch can. `POST
/workflows/{id}/validate` and `WorkflowValidationService.validate()` now also take
`canvas_edges` (previously nodes-only, which made Tier 3 impossible); the frontend's
Validate button now sends both. 12 new unit tests in
`test_workflow_validation_service.py` cover joins, failure-outcome branches, consumes,
`effective_produces`' config-awareness (get-device-configs), `requires_parsed`, and
disabled/cyclic/decoration graph handling. **Not yet manually verified live in a
browser** — do that before trusting it fully; consider deliberately misconfiguring a
workflow with unreachable capability requirements (e.g. wire a step needing
`attributes` directly off an inventory step's `success` outcome with nothing in
between) and confirming Validate reports it.

**Update 2026-09-23 (same session, continued further):** Tier 4 (advisory
attribute-path wiring) is now built — `WorkflowValidationService._tier4_attribute_path_wiring`
flags a `parsed.<node-id>...` config reference (bare dot-path fields like
route-on-attribute's `attribute_path`, or inside a `{{ }}` Jinja placeholder) whose
`<node-id>` is a real canvas node id belonging to one of 11 step kinds confirmed (by
grep, not the registry) to nest their own result under their own node id
(`services/workflow_context/node_result.py`), but which is NOT actually upstream of
the referencing step — the exact class of bug the `device.parsed` flat-key nesting
fix (see memory) was about. Findings are `severity="warning"` (never an error, per
`VALIDATION_PLAN.md`), and the existing Validate dialog/node badges already surface
warnings generically — no frontend changes were needed for this tier. **Deliberately
narrower than `VALIDATION_PLAN.md`'s original Tier 4 sketch** — see that doc's Tier 4
section for exactly what shipped vs. what was cut and why (the `device.attribute_bags`
shape from the original sketch isn't structurally checkable the same way; the "key
name matches" sub-check was dropped as too per-step-specific to generalize). 7 new
unit tests. **Not yet manually verified live in a browser** — do that before trusting
it; consider wiring, e.g., a List Contains node whose result is referenced by an
unrelated sibling branch's Route on Attribute step and confirming Validate flags it.

All four validation tiers from `VALIDATION_PLAN.md` are now built. What's left of the
original validation work is the pre-run gate (blocking Run on unresolved Tier 1–3
errors) — see "Open items" below.

**Update 2026-09-23 (real live usage, two real bugs found and fixed):** the first
real use of the Validate button against real workflows found two Tier 1 false
positives, reported by the user: `get-nautobot-attributes`'s `list_of_attributes`
flagged as missing when left empty (empty is correct — Nautobot's core fields are
fetched regardless, the field only adds optional groups) and `parse-cisco-config`'s
`output_key` flagged as missing despite the step having a real, applied fallback
default (`config.py`'s `"cisco_config"`). Root causes were different — the first was
simply wrong registry data (`required: true` on a field that's legitimately always
optional); the second exposed a real gap in Tier 1's design, that a "required" field
can still have a genuine fallback default, which isn't the same as being missing.
Fixed generally: `WorkflowValidationService._tier1_schema` now checks both
`PluginIOField.default` and the step's `config.py::get_config()` default before
flagging a blank required field — a registry-wide scan found **37** required fields
across the registry with exactly this shape (config.py default, no matching
registry `default:`), all now resolved by this one change. `list_of_attributes` was
additionally corrected to `required: false` with a clearer description (registry
data can't be fixed by a defaulting mechanism — it was never actually required).
The frontend's Select Attribute Groups dialog, config panel, and Help tab for
`get-nautobot-attributes` were also rewritten to make "empty is valid, core fields
are always fetched" explicit, and to remove a stale Help tab claim that an empty
list causes a failure outcome (it never did). See `VALIDATION_PLAN.md`'s Tier 1
section for the full reasoning and `PluginRegistryService`-injection detail
(`WorkflowValidationService`'s constructor now takes the service, not the raw
registry, so Tier 1 can call `get_plugin_config`).

**Update 2026-09-24:** the `AI_DEFAULTS.md` resolver/drift-check is now built —
`backend/scripts/ai_defaults.yaml` is a structured, machine-checkable counterpart to
this doc's tables (source of truth for values; the doc keeps the "why"), and
`backend/scripts/ai_defaults.py::resolve_and_check` live-resolves every entry
(credentials via `CredentialsService`, git repos via `GitRepositoryService`,
sources via `SettingsRepository`, inventory via `InventoryRepository`) against the
current DB, raising `AiDefaultsDriftError` naming the exact stale entry instead of
ever falling back to a guess — run `python scripts/ai_defaults.py` before drafting a
patch to get current ids. Separately, `ai_workflow_apply.py` had a real gap closed:
it computed Tier 1-4 validation findings but always persisted the patch regardless,
so a dangling `credential_reference`/`git_repository_id`/`*_source_id` would apply
silently and only show up as a reported (non-blocking) finding. It now passes
`canvas_edges` into `validate()` too (previously omitted, which meant Tier 3 never
actually ran from this script) and **refuses to write** if any Tier 2
reference-existence finding comes back (`REFERENCE_DRIFT_CODES` in
`scripts/ai_defaults.py`) — this is the enforcement half of AI_DEFAULTS.md's
"resolve live or fail loudly" rule; `scripts/ai_defaults.py` is the other half, for
resolving names *before* a patch exists. Every other finding (Tier 1/3/4) is still
only reported, not blocking — that's the separate, still-open "pre-run validation
gate" item below, deliberately not conflated with this one. **Verified live against
the real dev DB**: `python scripts/ai_defaults.py` resolved all 20 real
AI_DEFAULTS.md entries to their current ids; a deliberately-corrupted entry (renamed
credential) correctly failed loudly with a clear per-entry message and exit code 1.
8 new unit tests in `backend/tests/unit/test_ai_defaults.py` (including one that
loads the real `ai_defaults.yaml`, not a fixture, to catch a malformed real file).
The apply-script's new refuse-to-write gate is verified by code inspection plus the
existing Tier 2 test coverage in `test_workflow_validation_service.py` (which
already exercises every code in `REFERENCE_DRIFT_CODES`), not yet exercised as a
full live `ai_workflow_apply.py` run — that would need a live AI session enabled on
a real workflow, deliberately not done without asking first (see "Turn-taking
discipline").

**Update 2026-09-24 (pre-run validation gate — the last open item is now built):**
`RunService._assert_no_blocking_validation_errors` refuses to dispatch a run
(`ValidationFailedError`, 400, no run row created) when `WorkflowValidationService`
reports any Tier 1–3 error on the workflow's current saved canvas. Unconditional —
no override, matching the existing no-bypass convention `scheduled_trigger.py`
already uses for its run-input validation. Turned out to need more than the one
call site the open item named:

- Investigation found **three** independent run-dispatch code paths, not one.
  `RunService.trigger_run` (manual) and `ChangeRequestService._dispatch_deploy`
  (webhook/change-request approval) both go through the shared
  `RunService._create_and_dispatch_run`, so gating there covers both at once — the
  check runs before `run_repo.create_run`, so a blocked run leaves no row behind.
  `_create_and_dispatch_run`'s own docstring previously claimed scheduled triggers
  shared it too; that was **stale/wrong** — `hatchet/workflows/scheduled_trigger.py`
  has always had its own independent run-creation code (it runs in a separate
  Hatchet worker process, calling `SessionLocal()` directly, not through
  `RunService` at all). Fixed the docstring and gave that file its own mirrored
  check instead, matching its existing convention exactly: create the run row
  first (so a blocked cron fire is still visible in run history — there's no
  interactive caller to raise an exception at), then mark it `failed` with
  `error_category="configuration"`, same shape as its existing
  `resolve_run_inputs`/`validate_reference_inputs` failure branch right next to it.
- `RunService.__init__` gained an optional `plugin_registry_service` param
  (`WorkflowValidationService` needs one). The router's `trigger_run` endpoint gets
  the app-wide cached instance via `Depends(get_plugin_service)` — but only through
  a *new*, trigger-only dependency function (`_service_for_trigger`), deliberately
  not folded into the `_service` dependency every other endpoint on this router
  uses, so a plugin-registry hiccup can't take down read-only run-history endpoints
  too. `ChangeRequestService` never threads one through (unchanged), so its call
  falls back to `RunService`'s own lazy construction (a fresh
  `PluginRegistryService(PluginRepository(plugins_file=settings.plugins_file))`,
  same one-off pattern `ai_workflow_apply.py`/`ai_defaults.py` already use).
  `scheduled_trigger.py` builds its own fresh one too, for the same reason (no
  FastAPI `app.state` inside a Hatchet worker).
- **Deliberately no frontend change** — see `VALIDATION_PLAN.md`'s "Frontend
  surfacing" update. A blocked run surfaces via the existing
  `useTriggerRunMutation` error toast; disabling/confirming the Run button
  pre-flight is a follow-up if that toast proves confusing in practice.
- 6 new unit tests (`tests/unit/test_run_service_pre_run_validation.py`):
  blocking-error refusal creates no run row, clean validation still dispatches,
  Tier 4 warnings never block, the triggering user's id is what gets passed as
  `acting_user_id`, and both branches of the registry-service fallback. Full
  existing `RunService`/`ChangeRequestService`/`WorkflowValidationService` suites
  (155 tests) re-run clean — no regressions. **Verified live against the real dev
  DB**: workflow 23 (this doc's live test artifact) re-validated clean
  (`has_errors: False`) through the exact same `WorkflowValidationService` call the
  gate now makes, confirming it won't false-block a legitimately clean workflow.
  **Not verified live**: actually calling `trigger_run`/the scheduled-trigger task
  end-to-end against a real broken workflow — that would dispatch a real
  background run, so it was deliberately not done without asking first (same
  "Turn-taking discipline" reasoning as the AI_DEFAULTS.md gate). `scheduled_trigger.py`
  has no dedicated unit test at all, before or after this change — `hatchet_sdk`'s
  `Task.fn` (the only way to call the wrapped function directly) is marked
  internal/deprecated, and this file had zero prior test coverage for the exact
  same reason; not a gap introduced by this change.

All four `VALIDATION_PLAN.md` tiers, plus the pre-run gate, are now built — the
`AI_DEFAULTS.md` drift-check and the auto-layout helper too (see their own updates
above). What's left is verification, not construction — see "Open items" below.

**Update 2026-09-24 (`AI_VOCABULARY.md` added):** a third required-reading doc
alongside `PROCESS.md`/`AI_DEFAULTS.md`, addressing a gap those two don't cover —
neither says which registry steps and wiring a recurring natural-language request
actually means (`AI_DEFAULTS.md` is about *values*, not step selection). Scoped
deliberately small: a glossary of **confirmed** phrase → step mappings, grown from
actual corrections/confirmations rather than a speculative grammar — see the file
itself for the seed entry (a two-step Nautobot devices+attributes request) and its
"how entries get added" rule. Doesn't change `PROCESS.md`'s propose-before-apply
step; it just makes the first proposal more likely to match intent.

**Correction (same session, right after writing the above):** the first pass at
the seed entry claimed there was no backend way to resolve a saved "filter"-type
inventory by name at all — **wrong**, caught by the user questioning it directly.
`device_filter` (the canvas snapshot format `"fixed"` mode needs) and
`Inventory.conditions` (what a saved inventory actually stores — confirmed live
for `LAB`: `[{"version": 2, "tree": {"type": "root", "internalLogic": "OR",
"items": [...]}}]`) genuinely are different tree formats, and the only converter
between *those two specific shapes*
(`frontend/.../inventory/utils/tree-format-converters.ts`) is frontend-only — that
part was right. But `backend/utils/inventory_converter.py::
convert_saved_inventory_to_operations` is a full, real, **backend-native** Python
function that evaluates the same saved `conditions` directly into Nautobot query
operations, already used at run time whenever `get-nautobot-devices` is configured
with `inventory_source: "run_param"`
(`NautobotSourceService.resolve_saved_inventory_devices_by_id`). So resolving a
named inventory's devices from the backend, with zero frontend involvement, was
never actually blocked — only the one narrow case of *freezing a `"fixed"`-mode
canvas snapshot* is. `AI_VOCABULARY.md`'s recipe now targets a named inventory via
`run_param` (a `reference`/`inventory` static_attribute defaulting to the resolved
id) instead of a stop-and-ask — arguably the more faithful reading of "use the
inventory named X" anyway, since it stays live rather than freezing a
point-in-time copy. The narrower `"fixed"`-mode snapshot case is still a real,
undone gap (would need the frontend converter ported to Python) but is no longer
the default path, so it rarely comes up.

**Update 2026-09-24 (first real end-to-end workflow, three more real bugs found
and fixed by actually running it):** built and ran a 6-step "get backups"
workflow (Get from Nautobot → Get Nautobot Attributes → Get Configs → Git Pull →
Store Artifact → Git Push) on workflow 23 end to end — the first AI-authored
workflow in this feature's history to actually **run** to completion, not just
validate cleanly. Two bugs surfaced immediately on apply, before it ever ran:

1. `ai_workflow_apply.py` passed the raw `PluginRegistry` (from
   `plugin_service.load_registry()`) into `WorkflowValidationService`, which
   expects the `PluginRegistryService` wrapper — a stale call site from before
   that constructor's signature changed (see the 2026-09-23 Tier 1 update
   above), never caught because this script had never actually been run
   end-to-end since. Crashed on every invocation. Fixed: pass `plugin_service`
   directly.
2. `WorkflowService._validate_static_attributes` (and its frontend twin,
   `workflow-validation.ts`) had no branch for `type == "reference"` at all —
   any non-null default on a reference-type static attribute was
   unconditionally rejected, making the `run_param` + defaulted-reference
   pattern this very doc recommends impossible to actually save. Fixed on both
   sides, matching `StaticAttributeDef`'s own documented contract
   (`ref_kind: "inventory"` → int default, `ref_kind: "credential"` → string
   default). 7 new backend tests, 5 new frontend tests. The frontend fix also
   added a "used by \"<node title>\"" hint to the error message, at the user's
   request, by scanning node configs for the known `*_param` reference fields
   (`inventory_param`, `credential_param`).

**Then a design correction, not a bug**: the user pointed out that for a
workflow meant to run *live* (the common case), `"fixed"` mode with the
inventory's real name is what they actually want — `"run_param"` should be the
exception for a workflow that will be scheduled, not the default for everything.
This reopened the `"fixed"`-mode snapshot gap the correction above had marked as
"undone, out of scope unless requested" — now requested. Re-reading the frontend
converter in full (not just skimming it, as the first pass had) found the
actually-relevant logic is ~25 lines (`conditionTreeToFilterTree` +
`convertConditionItems`/`convertConditionGroup`), not the ~180-line whole file —
most of that file is the unneeded opposite direction. Ported it faithfully to
`backend/scripts/ai_inventory_filter.py::saved_conditions_to_device_filter`,
covering flat conditions, arbitrary nesting, and the single-top-level-NOT-group
unwrap special case. **Verified live**: cross-checked that converting `LAB`'s
real `conditions` through this new function, then through the real
`get-nautobot-devices` "fixed"-mode executor logic
(`_filter_tree_to_operations`), produces **byte-identical** `LogicalOperation`
output to the existing runtime converter
(`convert_saved_inventory_to_operations`) for the same inventory — not just a
structural match. 9 new tests, including one that re-runs this exact live
cross-check against the real dev DB (skips gracefully if unreachable).
`AI_VOCABULARY.md`'s recipe now defaults to `"fixed"` mode; `"run_param"` is used
specifically when the request says or implies scheduling.

**Update 2026-09-24 (fan-out threshold + Fan In wiring rule):** two more
`AI_VOCABULARY.md` additions from the same live-testing conversation. First,
`get-nautobot-devices`'s `fan_out` now has a real, checked default instead of a
static number: `scripts/ai_inventory_filter.py::count_inventory_devices` gets
the target inventory's *live* device count (via
`NautobotSourceService.analyze_inventory` — a filter-type inventory's true count
can only be known by evaluating it against Nautobot, not by reading the DB) and
stops to ask whether to enable fan-out when it's above 10 — never silently
picks either way. Verified live: `LAB` is 3 devices (`count_inventory_devices`
returned 3 against the real dev Nautobot), correctly below the threshold. Doing
this required starting `NautobotService` by hand
(`NautobotService().startup()` + `service_factory.set_nautobot_app_service`) —
normally done once in `main.py`'s app lifespan, which a standalone script never
runs through; a real gap, same shape as the `NautobotService is not
initialized` `RuntimeError` this surfaced on first attempt. 3 new unit tests
(mocked Nautobot boundary). The `fan_out.max_concurrency: 5` policy default
this replaces was never actually applied by any rule — corrected to the user's
stated real default (`enabled: true, mode: per_device, chunk_size: 1,
max_concurrency: 10`), used only when fan-out is actually turned on.

Second, the user caught that enabling fan-out isn't just a config block on the
inventory step — it changes what "safe" wiring means for everything downstream,
specifically the backup workflow's own git-pull/store-artifact/git-push chain.
This was already fully documented (`fan-in`'s own registry description: *"Place
git / store-artifact steps after Fan In for safe, single-commit exports"*;
`doc/WORKFLOW-STEPS.md`'s "Writing concurrency-safe steps" table lists exactly
which step kinds need it — `store-artifact`→git, `git-clone`, `git-pull`,
`git-push`, `open-change-request`, all because they share one on-disk working
tree per git repository and each fanned-out caller opens its own commit
otherwise) — it just hadn't been carried into `AI_VOCABULARY.md` as an
authoring rule. Now it has: whenever fan-out is enabled, insert a `fan-in`
node before the first git-touching step, with per-device compute before it and
git/store steps after. No code changed here, only documentation — the
underlying mechanism (the per-repo advisory lock, the fan-in join semantics)
was already built and correct.

**Live test artifact**: workflow id `23`, name "AI Assistent", now holds the real
6-step backup workflow described above (applied via `ai_workflow_apply.py`,
**verified to actually run successfully** by the user). No longer the old
two-step read-only test — update this note again before assuming its contents
if picking this back up later.

---

## Goal

You open a blank canvas, describe a use case, and an AI collaborator builds the
workflow directly into that same workflow — not an exported file you import, not a
suggestion in chat you retype by hand. You give feedback, it revises in place, you
validate, you run.

## What this requires that doesn't exist today

Two gaps, both need to be closed before the loop above works at all:

1. **No mechanism for something outside the browser to write into a workflow.**
   `canvas_nodes`/`canvas_edges` only change via the canvas UI calling
   `WorkflowService.update_workflow` through the authenticated browser session. An AI
   collaborator running in a terminal has no browser session and no JWT.
2. **No live sync from DB to an open canvas tab.** The editor loads the workflow once
   into local state; nothing pushes a change made elsewhere into an already-open tab.
   A websocket/SSE push is real work and explicitly **out of scope for v1** — see
   "Near-live view via polling" below.

Everything in this doc is about closing gap 1 cleanly (through the real service
layer, with a real identity and real audit trail) and living with gap 2 via polling
plus an explicit reload action, rather than building live push now.

---

## AI actor identity

The AI collaborator acts as its own restricted user, `ai-assistant`, not as you and
not as an anonymous script. This matters for three reasons: RBAC's delegation-bound
model (`CLAUDE.md` → P1–P8) means an actor can only grant/act within permissions it
holds; every `WorkflowChange` record and git-mirror commit
(`WorkflowGitService.sync_workflow_to_git`) carries `actor_username`, so "AI wrote
this" vs. "you wrote this" needs to be a real, visible distinction in history and in
change-request review; and it means **you never log in as it** — you stay yourself
the whole time (see "Enabling AI updates" below for why that matters).

**Seeded, not manually created.** `ai-assistant` is created the same way `admin` is —
an idempotent seed step alongside `services/auth/rbac_seed.py::seed_rbac()`, run on
every boot like the existing `SYSTEM_ROLES`/`DEFAULT_PERMISSIONS` seed.

1. A system role, `ai-assistant` (`is_system=True`), granted exactly (constant
   `AI_ASSISTANT_PERMISSIONS` in `rbac_seed.py`):
   - `workflows:read`, `workflows:write`
   - `credentials:read` (metadata existence only — **never** `credentials:reveal`)
   - `git.repositories:read`
   - `sources.nautobot:read`, `sources.mattermost:read`, `sources.batfish:read`,
     `sources.pyats:read`
   - No `workflows:execute`, `workflows:publish`, `workflows:delete`,
     `change_requests:approve` — the AI actor never triggers a run, publishes to the
     background tier, deletes a workflow, or approves a change request.
   - Nothing touching `rbac.*`, `users`, `system.*`, `secret_manager.*` (P3 already
     forces these to require `admin` regardless of role).
2. A seeded user `ai-assistant` (`ensure_ai_assistant_user` in `rbac_seed.py`),
   created with **`is_active=False`** and a random, never-surfaced password (it never
   logs in interactively). It does not exist as a usable login until an admin
   explicitly flips it on (**Settings → Users → edit the `ai-assistant` row → Active
   switch**). A fresh install ships with the feature fully wired but inert.

This is a real, enforced two-layer gate, not just a UI convenience: `is_active` is
checked explicitly by `ai_workflow_apply.py` before anything else runs (there is no
JWT/`get_current_user` path involved for a direct-DB-session script, so this check
has to be explicit or the flag would do nothing).

## Enabling AI updates — a consent flag, not a login

Earlier drafts of this doc considered having you log into the browser *as*
`ai-assistant` to watch it work. Rejected: every save made from that session —
including your own hand-edits while reviewing — would be attributed to `ai-assistant`
in the audit trail and the git-mirror commit author, indistinguishable from what the
AI actually wrote.

Instead: **you stay logged in as yourself.** Enabling AI updates is a per-workflow,
time-boxed consent flag on your own session, not an identity swap. Mechanically it's
a row-existence flag, the same pattern `workflow_background_tier` already uses
("existence of the row *is* the published flag"):

- Table `workflow_ai_sessions {id, uuid, workflow_id, enabled_by_id, expires_at,
  created_at, updated_at}` — not unique on `workflow_id`, so past sessions are kept
  as a history; "active" is the latest row with `expires_at > now()`.
- Any user holding `workflows:write` on that workflow can create one from the canvas
  properties panel ("AI Collaboration" section, next to "Background Tier"), default
  60-minute expiry, never a standing switch.
- The apply script checks for an active, non-expired row **before** it's allowed to
  write, attributing the write to `ai-assistant` regardless of who enabled the
  session. This is a real, server-enforced gate (checked in the script/service layer,
  not the frontend).
- Your own edits are never gated by this flag and never attributed to `ai-assistant`
  — the two identities stay cleanly separable in history no matter how the toggle is
  set.

## The apply mechanism

`backend/scripts/ai_workflow_apply.py` is the **only** way the AI collaborator
touches the database. It:
1. Parses `--workflow-id` (int) and `--patch-file` (path to a JSON object with any of
   `canvas_nodes`/`canvas_edges`/`canvas_groups`/`static_attributes` — each a full
   replacement of that field, not a diff).
2. Resolves the `ai-assistant` user; refuses if `is_active` is not `True`.
3. Resolves the active `workflow_ai_sessions` row for `--workflow-id`; refuses if
   none/expired.
4. Fetches the workflow fresh via `WorkflowRepository.get_by_id` — **never** trust a
   previous invocation's cached state.
5. Runs `WorkflowValidationService` (Tiers 1–2) against the proposed merged state and
   includes findings in the output regardless of outcome.
6. Calls `WorkflowService(db).update_workflow_for_ai_session(workflow_id, data,
   ai_user_id, actor_username="ai-assistant")` — a variant of the normal
   `update_workflow` added specifically for this (see "A real gap found during
   implementation" below for why the normal method doesn't work here) that shares all
   the same validation/git-mirror/change-tracking logic via a private
   `_apply_update` helper, skipping only the ownership check.
7. Prints a JSON report to stdout: `{workflow_id, updated_at, validation:
   {has_errors, findings}}`.

This is deliberately not a raw SQL write and not a second persistence code path — it
is the existing service layer, called from a script instead of a router, exactly like
`scripts/init_test_db.py` already does for seeding.

**Critical rule for whoever calls this script: always re-fetch the current
`canvas_nodes`/`canvas_edges` immediately before constructing a patch, never trust
memory of what was written last turn.** If the human hand-edited and saved between
turns, the patch must apply on top of their saved state, not silently overwrite it.
This is procedural discipline (fetch-then-patch), not a locking mechanism — true
concurrent editing is out of scope for v1.

**Building a patch by hand — the real node/edge shape.** `canvas_nodes`/
`canvas_edges` are loosely-typed JSON on the backend (`list[dict[str, Any]]`), but the
frontend expects a specific shape. A real, working example is in
`contributing-data/workflow-gallery/get-backups.json`. The fields that matter and are
easy to get wrong by hand:
- Every node needs `measured: {width: 320, height: 128}` (the fixed node size per
  `doc/WORKFLOW-STEPS-STYLE_GUIDE.md`), plus `dragging: false, selected: false`. See
  "Bugs found and fixed" below for what happens if you omit `measured`.
- `data.kind` is the registry step id (e.g. `get-nautobot-devices`); `data.pluginConfig`
  holds that step's config, matching `registry.yaml`'s `configuration_input` for that
  plugin exactly (required fields, types).
- `data.requires`/`produces`/`consumes`/`outcomes`/`artifactType`/`overview`/
  `description` should be denormalized copies of the plugin's registry entry — the
  frontend's `migrateCanvasState` will "fix up" a node missing these (setting
  `migrated: true` → `markDirty()`), so include them to avoid a spurious dirty flag
  on load, matching what `applyPluginDefaults` in
  `frontend/.../utils/migrate-canvas.ts` checks for.
- Edges: `{id, type: "waypoint", data: {edgeStyle: "bezier"}, source, sourceHandle,
  target, targetHandle: "input", selected: false}`. `sourceHandle` is the upstream
  step's outcome name (`"success"`/`"failure"`).

**A real gap found during implementation, now fixed:** `WorkflowService.update_workflow`
has a strict ownership check (`workflow.creator_id != user_id → AccessDeniedError`).
Since `ai-assistant` is never the creator of a workflow you made, this would have
permanently blocked the entire feature. Fixed by adding
`WorkflowService.update_workflow_for_ai_session` (in
`backend/services/workflow/workflow_service.py`), which shares all the real logic
with `update_workflow` via a new private `_apply_update` helper and skips only the
ownership check — its only precondition is the caller having already verified an
active `workflow_ai_sessions` row (the `ai_workflow_apply.py` gate above).

## Near-live view via polling, not websockets

No websocket/SSE infrastructure exists anywhere in this app. Instead, reuse the
polling convention already used for jobs/runs (`refetchInterval` via TanStack Query,
mirroring `useWorkflowRunQuery`'s variable-interval pattern): a self-referential
`refetchInterval` on `useWorkflowAiSessionQuery` that only polls (every 5s) while its
own last-known result says the session is `active` — so enabling the toggle starts
polling and disabling/expiry stops it, with no caller-supplied flag needed. On a
change (the poll's `workflow_updated_at` newer than what the canvas currently has), a
banner appears — "The AI updated this workflow — Reload" — rather than silently
swapping canvas state out from under an in-progress edit.

**Its own query key.** The poll uses `queryKeys.workflows.aiSession(id)`, deliberately
*not* `queryKeys.workflows.detail(id)` — the canvas's one-shot rehydration query
shares that second key at `staleTime: Infinity`, and any refetch under it would flow
straight into the open canvas and clobber in-progress edits.

## Turn-taking discipline

- While the AI is mid-turn (resolving defaults, drafting, applying), don't hand-edit
  the canvas — if you do, save it first so it's not lost on the next fetch-then-patch.
- After a change is applied, wait for the "Reload" banner (or reload manually) before
  giving feedback — feedback on stale state produces confusing patches.
- The AI should describe what it's about to build in chat *before* writing it (steps,
  in order, with the defaults it's resolving from `AI_DEFAULTS.md` and any phrase
  interpretations from `AI_VOCABULARY.md`), so you can redirect before there's
  anything to undo.

---

## The loop

1. **You create a blank workflow** in the UI and Save it (an empty canvas can now be
   saved — see "Bugs found and fixed" below — this gives it a real id).
2. **You enable AI updates** for that workflow (canvas properties panel toggle).
3. **You describe the use case** in chat.
4. **The AI proposes a step plan in chat first** — which registry steps, in what
   order (checking `AI_VOCABULARY.md` for a confirmed phrase mapping first), which
   `AI_DEFAULTS.md` entries it's resolving, anything it couldn't resolve (stop and
   ask, never guess a name).
5. **The AI applies the draft** via `ai_workflow_apply.py`, which runs validation as
   part of the same pass and reports findings.
6. **You get a "Reload" banner**, click it, give feedback.
7. **The AI re-fetches current state, applies the delta, re-validates.** Repeat 6–7
   until satisfied.
8. **Explicit Validate pass** before any run — currently only available via the apply
   script's JSON output (no in-canvas "Validate" button yet — see "Open items").
9. **Change-request routing is opt-in, not default** (corrected 2026-09-24 — an
   earlier version of this doc had it backwards): a config-mutating step
   (`configure-replace-config`, `deploy-rendered-template`, any `store-artifact`/
   `git-push` writing to a tracked repo) still routes through `open-change-request`
   when the user explicitly asks for that in the same turn, but the default for an
   unqualified request is a direct run — see `AI_DEFAULTS.md`'s policy defaults.
10. **You click Run** (or approve the change request) — the AI actor's RBAC grant
    makes this structurally impossible for it to do itself, not just a self-imposed
    rule.

---

## What's actually been built (file inventory)

Everything below is uncommitted on branch `feature/ai-assistent`.

**Backend — new files:**
- `backend/core/models/workflow_ai_session.py` — `WorkflowAiSession` model
- `backend/models/workflow_ai_session.py` — Pydantic request/response
- `backend/models/workflow_validation.py` — `ValidationFinding`/`WorkflowValidationResult`
- `backend/repositories/workflow_ai_session_repository.py`
- `backend/services/workflow/workflow_ai_session_service.py`
- `backend/services/workflow/workflow_validation_service.py` — Tiers 1–2
- `backend/routers/workflow_ai_session.py` — GET/PUT/DELETE `/workflows/{id}/ai-session`
- `backend/scripts/ai_workflow_apply.py` — the apply mechanism
- `backend/scripts/ai_defaults.yaml` — structured, machine-checkable counterpart to
  `AI_DEFAULTS.md`'s tables (source of truth for values)
- `backend/scripts/ai_defaults.py` — `resolve_and_check`: live-resolves every
  `ai_defaults.yaml` entry against the DB, raising `AiDefaultsDriftError` on drift;
  `REFERENCE_DRIFT_CODES`, shared with `ai_workflow_apply.py`'s refuse-to-write gate
- `backend/scripts/ai_layout.py` — `compute_layer_layout`/`apply_layout`: the
  auto-layout helper, see "Auto-layout helper" in Open items below
- `backend/scripts/ai_inventory_filter.py` — `saved_conditions_to_device_filter`:
  Python port of the frontend's saved-conditions → canvas `device_filter`
  converter, for defaulting `get-nautobot-devices` to `"fixed"` mode with a real
  inventory name — see the 2026-09-24 update above. Also
  `count_inventory_devices`/`FAN_OUT_DEVICE_THRESHOLD`/`DEFAULT_FAN_OUT_CONFIG`:
  the live device-count check behind the fan-out threshold rule (see the
  second 2026-09-24 update below).
- `backend/tests/unit/test_rbac_seed_ai_assistant.py`
- `backend/tests/unit/test_workflow_ai_session_service.py`
- `backend/tests/unit/test_workflow_validation_service.py`
- `backend/tests/unit/test_ai_defaults.py`
- `backend/tests/unit/test_ai_layout.py`
- `backend/tests/unit/test_ai_inventory_filter.py`
- `backend/tests/unit/test_ai_inventory_filter_device_count.py`
- `backend/tests/unit/test_workflow_service_static_attributes.py`

**Backend — modified files:**
- `backend/core/models/__init__.py` — export `WorkflowAiSession`
- `backend/main.py` — seed `ai-assistant` in lifespan; register the new router
- `backend/models/workflow_validation.py` — `WorkflowValidateRequest` (optional
  unsaved-draft body for the validate endpoint)
- `backend/routers/workflows.py` — `POST /workflows/{id}/validate` endpoint; now
  accepts an optional body (`canvas_nodes` + `canvas_edges`) so it can validate
  unsaved canvas edits, not just the last-saved state
- `backend/services/auth/rbac_seed.py` — `AI_ASSISTANT_PERMISSIONS`, `ensure_ai_assistant_user`
- `backend/services/workflow/workflow_service.py` — `update_workflow_for_ai_session` +
  `_apply_update` refactor
- `backend/services/workflow/workflow_validation_service.py` — Tier 3
  (`_tier3_capability_flow`): static DAG walk, `_CapabilityState`,
  `_intersect_capability_states`, `_is_executable_node`; `validate()` now also
  takes `canvas_edges`. Tier 4 (`_tier4_attribute_path_wiring`):
  `_PARSED_PATH_CANDIDATE_RE`, `_NODE_SCOPED_PARSED_STEP_KINDS`,
  `_iter_config_strings`. Constructor now takes `PluginRegistryService` (was
  the raw `PluginRegistry`) so Tier 1 can call `get_plugin_config` for
  default-aware required-field checking (`_config_default`,
  `_config_defaults_cache`) — see the "default keys" fix in `VALIDATION_PLAN.md`.
- `backend/scripts/ai_workflow_apply.py` — now passes `canvas_edges` into
  `validate()` (previously omitted, so Tier 3 never actually ran from this
  script); refuses to write (returns an error, does not call
  `update_workflow_for_ai_session`) when any Tier 2 reference-existence finding
  is in `REFERENCE_DRIFT_CODES` — the AI_DEFAULTS.md drift enforcement gate.
- `backend/workflow_steps/registry.yaml` — `get-nautobot-attributes.list_of_attributes`
  corrected to `required: false` (was always a valid empty selection, never
  actually required) with a clearer description and a correct example (the old
  example listed `location`/`role`, which aren't even valid group keys — they're
  core fields, always fetched); `parse-cisco-config`'s `output_key`/`config_source`
  gained an explicit `default:` (belt-and-suspenders; not load-bearing for the
  fix, which is in the service, not the registry)
- `backend/services/execution/run_service.py` — the pre-run validation gate:
  `RunService.__init__` gained an optional `plugin_registry_service` param and a
  `_validator()`/`_assert_no_blocking_validation_errors` pair;
  `_create_and_dispatch_run` now calls the latter before creating a run row, and
  its docstring's stale "shared by scheduled triggers too" claim is corrected.
- `backend/routers/workflow_runs.py` — new `_service_for_trigger` dependency
  (only `trigger_run` uses it) injects the cached `PluginRegistryService` via
  `Depends(get_plugin_service)`; every other endpoint keeps the plain `_service`.
- `backend/hatchet/workflows/scheduled_trigger.py` — mirrors the same pre-run
  validation check inline (own fresh `PluginRegistryService`, no `RunService`
  involved — see the 2026-09-24 update above for why), same
  create-run-then-mark-failed shape as its existing run-input validation.
- `backend/scripts/ai_workflow_apply.py` — fixed a real bug (see the 2026-09-24
  "first real end-to-end workflow" update above): was passing the raw
  `PluginRegistry` into `WorkflowValidationService` instead of the
  `PluginRegistryService` wrapper it actually expects, crashing on every
  invocation.
- `backend/services/workflow/workflow_service.py` —
  `_validate_static_attributes` fixed to actually check `type == "reference"`
  defaults (was unconditionally rejecting them; see the 2026-09-24 update
  above).

**Backend — new tests:**
- `backend/tests/unit/test_workflows_router_validate.py` — draft-vs-saved
  `canvas_nodes`/`canvas_edges` selection on the validate endpoint, plus an
  end-to-end Tier 3 case through the router
- 23 new cases in `backend/tests/unit/test_workflow_validation_service.py`:
  `Tier3CapabilityFlowTests` (12 — joins/intersection, failure-outcome branches,
  consumes, config-aware `effective_produces`, `requires_parsed`, disabled
  steps, cycles, canvas decorations), `Tier4AttributePathWiringTests` (7 —
  upstream/stale/self references, non-node-scoped and ordinary-namespace
  candidates never guessed, nested-config and Jinja-placeholder scanning), 4
  default-aware Tier 1 cases (registry default, config.py default, a blank
  config.py default still errors, memoization), and
  `RealRegistryDefaultRegressionTests` (4 — loads the real registry.yaml +
  config.py, not an in-memory fixture, and regression-locks the two exact
  reported bugs)
- `backend/tests/unit/test_run_service_pre_run_validation.py` — 6 cases: blocking
  error refuses before any run row exists, clean validation still dispatches,
  Tier 4 warnings never block, `acting_user_id` is the triggering user, and both
  branches of the injected-vs-fresh `PluginRegistryService` fallback

**Frontend — new files:**
- `frontend/src/components/features/workflows/types/workflow-ai-session.ts`
- `frontend/src/hooks/queries/use-workflow-ai-session-query.ts`
- `frontend/src/hooks/queries/use-workflow-ai-session-mutations.ts`
- `frontend/src/components/features/workflows/components/workflow-ai-session-panel.tsx`
- `frontend/src/components/features/workflows/components/ai-session-update-banner.tsx`
- `frontend/src/components/features/workflows/types/workflow-validation.ts` —
  `ValidationFinding`/`WorkflowValidationResult` mirroring the backend models
- `frontend/src/hooks/queries/use-workflow-validate-mutation.ts` — now sends
  `canvas_edges` alongside `canvas_nodes` (needed for Tier 3)
- `frontend/src/components/features/workflows/hooks/use-workflow-validation.ts` —
  drives the Validate button: mutation, dialog open state, per-node
  error/warning counts (workflowId-keyed so a workflow switch can't show stale
  findings); now also takes `allEdges`
- `frontend/src/components/features/workflows/dialogs/workflow-validation-dialog.tsx`
  — findings grouped by node; clicking a group selects that node and opens its
  config modal
- `frontend/src/components/features/workflows/utils/workflow-validation.test.ts`
  — the client-side `type: "reference"` fix and its "used by" hint (see the
  2026-09-24 update above)

**Frontend — modified files:**
- `frontend/src/lib/query-keys.ts` — `workflows.aiSession(id)` key
- `frontend/src/components/features/workflows/components/workflow-properties-panel.tsx`
  — slots in `WorkflowAiSessionPanel`
- `frontend/src/components/features/workflows/workflow-builder-page.tsx` — renders
  `AiSessionUpdateBanner`, wires `onReload`; wires `useWorkflowValidation` +
  `WorkflowValidationDialog` + the topbar Validate button
- `frontend/src/components/features/workflows/hooks/use-workflow-persistence.ts` —
  `baselineUpdatedAt` tracking (see bugs below)
- `frontend/src/components/features/workflows/hooks/use-canvas-node-changes.ts` —
  dirty-flag fix (see bugs below)
- `frontend/src/components/features/workflows/hooks/use-workflow-save.ts` — `requireSteps: false`
- `frontend/src/components/features/workflows/utils/workflow-validation.ts` —
  `requireSteps` option (client-side save-block checks; unrelated to the new
  server-side `WorkflowValidationService` beyond the shared name). Fixed
  2026-09-24: `validateStaticAttributes` had no branch for `type: "reference"`
  at all (mirrors the backend bug fixed in `workflow_service.py` the same day);
  now also names the referencing node(s) in the error via
  `describeReferencingNodes` (scans `inventory_param`/`credential_param`
  config fields).
- `frontend/src/components/features/workflows/types/workflow-canvas.ts` — `validation?`
  field on `WorkflowNodeData`, a view-only annotation (never persisted) merged in
  from the last Validate run, same pattern as `isGroupEntryPoint`
- `frontend/src/components/features/workflows/components/workflow-canvas.tsx` —
  `validationByNodeId` prop, merged into each `workflowNode`'s data before handing
  nodes to React Flow
- `frontend/src/components/features/workflows/components/nodes/workflow-node.tsx` —
  red/yellow error-count badge, only for `data.validation`, no per-step branch
- `frontend/src/components/features/workflows/components/workflow-topbar.tsx` —
  "Validate" button, disabled until the workflow has an id (same rule as Version
  Control)
- `frontend/src/components/features/workflow-steps/get-nautobot-attributes/index.tsx`,
  `attributes-dialog.tsx`, `help-panel.tsx` — "Select Optional Attribute Groups"
  wording throughout (was "Select Attribute Groups"), explaining that core
  Nautobot fields are always fetched and an empty selection is valid; removed a
  stale Help tab claim that an empty selection causes a failure outcome

**Related docs**: `AI_DEFAULTS.md` (defaults/policy), `AI_VOCABULARY.md` (phrase →
step/wiring glossary, added 2026-09-24), `VALIDATION_PLAN.md` (the four-tier
validator design — all four tiers are now built).

## Bugs found and fixed during live testing

These were only found by actually running the feature in a browser — worth reading
before assuming anything works from inspection alone.

1. **Client-side "Workflow has no steps" save block.** `validateCanvasWorkflow`
   blocked saving *any* empty canvas, making it impossible to create a blank shell
   for the AI to build into. Fixed with an opt-out param (`requireSteps`, default
   `true` so Run still correctly refuses an empty workflow) passed as `false` from
   the four Save call sites in `use-workflow-save.ts` only.
2. **Banner baseline never set for a workflow created within the same session.** The
   banner's `baselineUpdatedAt` was only derived from the canvas's one-shot
   rehydration query, which is skipped (keyed on `mountWorkflowId`, frozen `null` at
   mount) for a workflow that didn't exist yet when the page loaded. Fixed by also
   sourcing the baseline from `createWorkflow`/`updateWorkflow` mutation results in
   `use-workflow-persistence.ts`.
3. **"Reload" used `window.location.reload()`.** This app has no per-workflow URL
   route — a hard browser refresh always lands on a blank new workflow, confirmed as
   pre-existing/expected app behavior, not something to fix. So the banner's Reload
   button was wiping the canvas instead of restoring it. Fixed by wiring it to
   `handleLoadWorkflow` (the same in-place fetch-and-apply the Open dialog uses)
   instead.
4. **Banner never cleared after clicking Reload.** `handleLoadWorkflow` (used for
   fix #3) fetches and applies canvas content through its own path, which didn't
   feed into `baselineUpdatedAt` at all — so the canvas updated correctly but the
   banner stayed up forever. Fixed by having `handleLoadWorkflow` also record its
   fetch's `updated_at`, and taking the max across all four paths that can sync
   canvas content (initial fetch, create, save, load) rather than trusting one.
5. **Spurious "unsaved changes" on every reopen of an AI-authored node.**
   `handleNodesChange`'s dirty check only excluded `"select"`-type React Flow
   changes. A node loaded without a pre-baked `measured` size gets auto-measured by
   React Flow on first render, firing a `"dimensions"` change — counted as a real
   edit with zero actual user action. Verified directly against `@xyflow/react`'s
   source: the auto-measure path never sets `resizing`, while an actual user-driven
   resize (label/background nodes) always sets `resizing: true`/`false`. Fixed by
   excluding `"dimensions"` changes with `resizing === undefined` in
   `use-canvas-node-changes.ts`, which correctly still tracks real resizes.
6. **R9 architecture boundary violation** (caught by
   `tests/unit/test_production_hardening.py::TestR9StepBoundary`, not live testing):
   `WorkflowValidationService`'s git-repository existence check initially imported
   `workflow_steps.common.git_repository_loader`, which `services/*` may never do.
   Fixed by calling `services.git.repository_service.GitRepositoryService` directly
   (the same service that loader itself delegates to) and replicating its three
   existence checks inline.
7. **`disable` only expired the newest session row** (`workflow_ai_session_repository.py`,
   found by external code review, not live testing). `enable` always inserts a new
   row rather than reusing one, so two overlapping active rows are a real
   possibility (a retried PUT, two users). `expire_active_for_workflow` fetched only
   the single newest active row and expired that one, leaving an older row still
   valid — so `ai_workflow_apply.py`'s own active-session check could still succeed
   after "disable". Fixed to expire every currently-active row for the workflow, not
   just the latest; verified live against Postgres (two overlapping rows both
   correctly expired by one `disable` call) plus a new
   `tests/unit/test_workflow_ai_session_repository.py`.
8. **Tier 2 validation decrypted credential secrets.** `_check_credential_reference`
   called `CredentialManager.ssh()`/`.generic()`/`.shared_secret()`, which decrypt
   the secret as a side effect of resolving it — triggered by
   `POST /workflows/{id}/validate`, gated only on `workflows:read`, not
   `credentials:read`/`credentials:reveal`. Also leaked resolver/vault exception text
   into the finding message. Contradicted `VALIDATION_PLAN.md`'s explicit "existence
   check only" design. Fixed by switching to `CredentialsService.list_credentials`
   (metadata only, no decryption), mirroring
   `services/execution/reference_resolver.py`'s `_CredentialReferenceResolver`
   pattern (private-over-global precedence, type/status checks) generalized from
   "ssh only" to the three credential types a step kind can require. Verified live
   against real credentials (`cisco - noc` correctly resolves, a fake name correctly
   reports `credential_reference_not_found`, no decryption occurs) plus updated
   `test_workflow_validation_service.py`.
9. **Git version restore didn't advance the banner baseline.** `handleRestored`
   (`use-workflow-persistence.ts`) redraws the canvas via
   `WorkflowService.update_workflow` server-side (so `updated_at` genuinely
   advances) but never recorded that into `baselineUpdatedAt` — same root cause as
   bug 4, just a second call site that needed the same fix. While an AI session is
   active, the poll would see the newer server timestamp and the banner would
   falsely claim "the AI updated this workflow" right after a plain restore. Fixed
   by calling `setLoadedUpdatedAt(full.updated_at)` in `handleRestored` too.
10. **A non-owner could grant AI write consent on a public workflow.**
    `WorkflowAiSessionService._assert_workflow_access` copied
    `BackgroundTierService`'s pattern verbatim: deny only when the workflow is
    *private* and the caller isn't the creator. On a *public* workflow, any user
    holding the global `workflows:write` permission — not just the owner — could
    enable an AI session, and `update_workflow_for_ai_session` then skips the normal
    ownership check entirely, trusting that session as authorization. Fixed to
    require strict ownership (`creator_id != user_id`) regardless of visibility —
    granting write access to `ai-assistant` is a stronger action than the
    visibility-gated check that pattern was written for. Verified with a new test
    (`test_assert_access_public_other_user_still_denied`).

## Verified end-to-end (this session, against the real dev DB)

- Both original apply-script gates (`is_active=False`, no active session) refuse
  correctly with clear error messages. The third gate added 2026-09-24
  (reference-drift refusal) is verified via `scripts/ai_defaults.py` run live
  against the dev DB and via `test_workflow_validation_service.py`'s existing Tier 2
  coverage — see the 2026-09-24 update above for exactly what was and wasn't
  exercised live.
- A successful apply is attributed to `ai-assistant` in `workflow_changes`, cleanly
  separate from the human's own edits (verified: workflow 23's history alternates
  `admin`/`ai-assistant` rows correctly across multiple real saves from both sides).
- `WorkflowValidationService` Tiers 1–2 ran against all 7 real gallery workflows:
  2 pass clean, 5 correctly flag real, previously-invisible gaps. **Correction
  (2026-09-23, later session):** this bullet originally cited `parse-cisco-config`'s
  `output_key` finding here as a confirmed genuine gap, "not a checker bug" — that
  was wrong, it was in fact the exact false positive fixed in the "real live usage"
  update above. **Re-verified against the real gallery + real registry.yaml after
  that fix landed**: all 7 now pass Tier 1 cleanly (zero findings) — the false
  positive wasn't isolated to this one reported case, it affected other gallery
  workflows' Tier 1 results too. The only findings left on any of the 7 are Tier 2
  `credential_reference_not_found` (5 of 7 reference a credential name — "cisco -
  noc", "noc", "shared-secret" — that doesn't exist under that name in this dev DB;
  a correct finding for this environment, not a bug in either tier).
- Full loop, three sequential AI-authored steps added to workflow 23
  (`get-nautobot-devices` → `get-nautobot-attributes` → `get-device-configs`, later
  reset and retried clean), with the live banner→reload→clear cycle confirmed
  working on the final attempt after bugs 2–5 above were fixed.

## Open items (not built this session)

- **`AI_DEFAULTS.md` resolver/drift-check — built 2026-09-24, see the update above.**
  Left for a future session: the apply-script gate only refuses on Tier 2
  reference-existence findings — a real live `ai_workflow_apply.py` run exercising
  that refusal (requires enabling an AI session on a real workflow) hasn't been done,
  only the equivalent logic via `scripts/ai_defaults.py` and existing Tier 2 tests.
- **Auto-layout helper — built 2026-09-24.** `backend/scripts/ai_layout.py`:
  `compute_layer_layout`/`apply_layout` replace the hand-picked `{x: 0}`,
  `{x: 400}`, `{x: 800}`, ... with a layered grid — columns from
  `services/execution/graph.py::topological_generations` (dependency waves),
  rows stacked within a column, pitch matching the fixed 320x128 node size from
  `WORKFLOW-STEPS-STYLE_GUIDE.md`. Decoration nodes (label/background) and
  author-disabled steps are skipped (reuses
  `graph_resolution.filter_executable_graph`, same check StepRunner uses) — their
  position is left untouched, never invented. Deliberately backend-only and NOT
  wired into `ai_workflow_apply.py` (which still never lays out nodes itself, per
  its docstring) — call it yourself before building a patch. A user-facing
  "Auto Layout" canvas button was explicitly descoped (would need a separate JS
  implementation, e.g. dagre, since layout there runs client-side). 11 new unit
  tests (`tests/unit/test_ai_layout.py`: linear chains, parallel branches,
  joins, cycles, decoration/disabled exclusion). **Verified live**: ran against
  workflow 23's real canvas (`get-nautobot-devices-1` → `get-nautobot-attributes-1`)
  with the real plugin registry — correctly produced a two-column layout.
- **All four validation tiers are now built** (see the two "Update 2026-09-23"
  entries above) and **neither Tier 3 nor Tier 4 has been manually verified live in
  a browser yet** — only Tiers 1–2 and the UI shell have been. Do that before
  trusting the Validate button's output fully.
- **Pre-run validation gate — built 2026-09-24, see the update above.** Left for a
  future session: not exercised live end-to-end (would need to actually dispatch a
  blocked run against a real broken workflow — deliberately not done without
  asking first); the frontend Run button still isn't disabled/confirmed
  pre-flight, a blocked run only surfaces via the existing generic error toast;
  and `scheduled_trigger.py`'s check has no dedicated unit test (matching that
  file's pre-existing, unrelated lack of test coverage, not a new gap).
- **Automated regression tests for bugs 2–5 above** — only manually verified live in
  a browser this session, not codified as frontend tests (no existing test
  convention for these specific hooks/components was found to extend).
- **Nothing committed.** All work described above is uncommitted on
  `feature/ai-assistent`.
- **Nothing config-mutating has been tried.** Every live test was deliberately
  read-only (Nautobot lookups). The change-request safety routing in step 9 of "The
  loop" is designed but unexercised.
- **New validation tier: fan-out + unguarded shared-sink step.** Not built —
  discussed 2026-09-24, deliberately deferred. `AI_VOCABULARY.md`'s "fan-out
  requires re-checking downstream wiring" rule (see the update above) is
  currently enforced only by *me* remembering to apply it when authoring a
  patch — nothing catches it if a human (or a future, less careful AI patch)
  wires it wrong by hand. There's already direct precedent for exactly this
  class of check: `WorkflowService._validate_stop_here_not_in_fan_out`
  rejects a `stop-here` node positioned inside a fan-out branch at save time.
  The new check would be the same shape: walk the graph from a
  `fan_out.enabled: true` inventory step; if a node of kind `store-artifact`
  (with `destination: "git"`), `git-clone`, `git-pull`, `git-push`, or
  `open-change-request` is reachable **before** the nearest `fan-in` node (or
  no `fan-in` exists on that path at all), flag it — real, structural, not
  advisory (this produces N commits instead of one, not a crash, so it's easy
  to ship unnoticed). Open design questions to resolve when this gets picked
  up: (1) enforce at save time like `_validate_stop_here_not_in_fan_out`
  (`WorkflowService`), as a new `WorkflowValidationService` tier/finding, or
  both; (2) whether `store-artifact` with `destination: "filesystem"` needs
  any check too (currently safe only *if* `filename_template` is
  device-unique — see `doc/WORKFLOW-STEPS.md`'s concurrency table — a
  fixed/colliding template there is a real but different bug); (3) reuse
  Tier 3's existing fan-out-aware graph walk
  (`WorkflowValidationService._tier3_capability_flow`) rather than writing a
  second one.
