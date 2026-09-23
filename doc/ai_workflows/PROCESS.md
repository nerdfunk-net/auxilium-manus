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

**Not built yet** (see "Open items" at the end): the `AI_DEFAULTS.md` drift-checker
inside the apply script (names were resolved by hand every time this session), an
auto-layout helper (node positions were hardcoded by hand), a minimal in-canvas
"Validate" UI, Tier 3/4 validation, and a pre-run validation gate. None of these
blocked what's proven working; they're the next slice, not a blocker to resuming.

**Live test artifact**: workflow id `23`, name "AI Assistent", owned by `admin`
(user id 1), currently has two connected steps (`get-nautobot-devices-1` →
`get-nautobot-attributes-1` on the `success` outcome). Safe to keep, reuse, or delete
when picking this back up.

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
  in order, with the defaults it's resolving from `AI_DEFAULTS.md`), so you can
  redirect before there's anything to undo.

---

## The loop

1. **You create a blank workflow** in the UI and Save it (an empty canvas can now be
   saved — see "Bugs found and fixed" below — this gives it a real id).
2. **You enable AI updates** for that workflow (canvas properties panel toggle).
3. **You describe the use case** in chat.
4. **The AI proposes a step plan in chat first** — which registry steps, in what
   order, which `AI_DEFAULTS.md` entries it's resolving, anything it couldn't resolve
   (stop and ask, never guess a name).
5. **The AI applies the draft** via `ai_workflow_apply.py`, which runs validation as
   part of the same pass and reports findings.
6. **You get a "Reload" banner**, click it, give feedback.
7. **The AI re-fetches current state, applies the delta, re-validates.** Repeat 6–7
   until satisfied.
8. **Explicit Validate pass** before any run — currently only available via the apply
   script's JSON output (no in-canvas "Validate" button yet — see "Open items").
9. **Safety routing for config-mutating steps**: route the first run through
   `open-change-request` rather than a direct run, per `AI_DEFAULTS.md`'s policy
   defaults — not yet exercised in any live test (every test this session was
   deliberately read-only: Nautobot inventory/attribute lookups).
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
- `backend/tests/unit/test_rbac_seed_ai_assistant.py`
- `backend/tests/unit/test_workflow_ai_session_service.py`
- `backend/tests/unit/test_workflow_validation_service.py`

**Backend — modified files:**
- `backend/core/models/__init__.py` — export `WorkflowAiSession`
- `backend/main.py` — seed `ai-assistant` in lifespan; register the new router
- `backend/routers/workflows.py` — `POST /workflows/{id}/validate` endpoint
- `backend/services/auth/rbac_seed.py` — `AI_ASSISTANT_PERMISSIONS`, `ensure_ai_assistant_user`
- `backend/services/workflow/workflow_service.py` — `update_workflow_for_ai_session` +
  `_apply_update` refactor

**Frontend — new files:**
- `frontend/src/components/features/workflows/types/workflow-ai-session.ts`
- `frontend/src/hooks/queries/use-workflow-ai-session-query.ts`
- `frontend/src/hooks/queries/use-workflow-ai-session-mutations.ts`
- `frontend/src/components/features/workflows/components/workflow-ai-session-panel.tsx`
- `frontend/src/components/features/workflows/components/ai-session-update-banner.tsx`

**Frontend — modified files:**
- `frontend/src/lib/query-keys.ts` — `workflows.aiSession(id)` key
- `frontend/src/components/features/workflows/components/workflow-properties-panel.tsx`
  — slots in `WorkflowAiSessionPanel`
- `frontend/src/components/features/workflows/workflow-builder-page.tsx` — renders
  `AiSessionUpdateBanner`, wires `onReload`
- `frontend/src/components/features/workflows/hooks/use-workflow-persistence.ts` —
  `baselineUpdatedAt` tracking (see bugs below)
- `frontend/src/components/features/workflows/hooks/use-canvas-node-changes.ts` —
  dirty-flag fix (see bugs below)
- `frontend/src/components/features/workflows/hooks/use-workflow-save.ts` — `requireSteps: false`
- `frontend/src/components/features/workflows/utils/workflow-validation.ts` —
  `requireSteps` option

**Related docs**: `AI_DEFAULTS.md` (defaults/policy), `VALIDATION_PLAN.md` (the
four-tier validator design, Tiers 1–2 implemented here).

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

- Both apply-script gates (`is_active=False`, no active session) refuse correctly
  with clear error messages.
- A successful apply is attributed to `ai-assistant` in `workflow_changes`, cleanly
  separate from the human's own edits (verified: workflow 23's history alternates
  `admin`/`ai-assistant` rows correctly across multiple real saves from both sides).
- `WorkflowValidationService` Tiers 1–2 ran against all 7 real gallery workflows:
  2 pass clean, 5 correctly flag real, previously-invisible gaps (e.g.
  `parse-cisco-config`'s `output_key`, confirmed genuinely missing against
  `registry.yaml` — not a checker bug).
- Full loop, three sequential AI-authored steps added to workflow 23
  (`get-nautobot-devices` → `get-nautobot-attributes` → `get-device-configs`, later
  reset and retried clean), with the live banner→reload→clear cycle confirmed
  working on the final attempt after bugs 2–5 above were fixed.

## Open items (not built this session)

- **`AI_DEFAULTS.md` resolver/drift-check inside the apply script.** Every live test
  resolved names (`nautobot_source_id`, inventory, credential) by hand. The script
  should cross-check every name it's given still resolves and fail loudly, not
  silently, per `AI_DEFAULTS.md`'s own stated rule.
- **Auto-layout helper.** Node `position` was hardcoded by hand each time
  (`{x: 0}`, `{x: 400}`, `{x: 800}`, ...). Reuse
  `services/execution/graph.py::topological_generations` for x-ordering by
  dependency layer.
- **Minimal in-canvas "Validate" UI.** Findings are currently only visible in the
  apply script's stdout JSON — nothing surfaces them for a human editing by hand,
  which was explicitly one of the two motivations for building validation at all.
- **Tier 3 (capability-flow) and Tier 4 (attribute-path) validation** — see
  `VALIDATION_PLAN.md`'s build order.
- **Pre-run validation gate** on `RunService.trigger_run`.
- **Automated regression tests for bugs 2–5 above** — only manually verified live in
  a browser this session, not codified as frontend tests (no existing test
  convention for these specific hooks/components was found to extend).
- **Nothing committed.** All work described above is uncommitted on
  `feature/ai-assistent`.
- **Nothing config-mutating has been tried.** Every live test was deliberately
  read-only (Nautobot lookups). The change-request safety routing in step 9 of "The
  loop" is designed but unexercised.
