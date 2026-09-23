# AI-Human Workflow Collaboration — Process

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
   "Accepted v1 limitation" below.

Everything in this doc is about closing gap 1 cleanly (through the real service
layer, with a real identity and real audit trail) and living with gap 2 via an
explicit reload step, rather than building live sync now.

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
every boot like the existing `SYSTEM_ROLES`/`DEFAULT_PERMISSIONS` seed. Two additions
to that pattern:

1. A new system role, `ai-assistant` (`is_system=True`, so it can't be renamed or
   deleted per RBAC rule P5), granted exactly:
   - `workflows:read`, `workflows:write`
   - `credentials:read` (metadata existence only — **never** `credentials:reveal`)
   - `git.repositories:read`
   - `sources.nautobot:read`, `sources.mattermost:read`, `sources.batfish:read`,
     `sources.pyats:read`
   - No `workflows:execute`, `workflows:publish`, `workflows:delete`,
     `change_requests:approve` — the AI actor never triggers a run, publishes to the
     background tier, deletes a workflow, or approves a change request. Those stay
     exclusively yours.
   - Nothing touching `rbac.*`, `users`, `system.*`, `secret_manager.*` (P3 already
     forces these to require `admin` regardless of role).
2. A seeded user `ai-assistant`, mirroring `AuthService.ensure_initial_admin()` —
   created with **`is_active=False`**. It does not exist as a usable login until an
   admin explicitly flips it on (Settings → Users), the same gate `must_change_password`
   already enforces for the bootstrap admin. A fresh install ships with the AI
   collaboration feature fully wired but inert.

## Enabling AI updates — a consent flag, not a login

Earlier drafts of this doc considered having you log into the browser *as*
`ai-assistant` to watch it work. Rejected: every save made from that session —
including your own hand-edits while reviewing — would be attributed to `ai-assistant`
in the audit trail and the git-mirror commit author, indistinguishable from what the
AI actually wrote. That defeats the "you always know what happened" goal instead of
serving it.

Instead: **you stay logged in as yourself.** Enabling AI updates is a per-workflow,
time-boxed consent flag on your own session, not an identity swap. Mechanically it's
a row-existence flag, the same pattern `workflow_background_tier` already uses
("existence of the row *is* the published flag"):

- A new table, `workflow_ai_sessions {workflow_id, enabled_by_user_id, expires_at}`.
- Any user holding `workflows:write` on that workflow can create one (a toggle in the
  canvas toolbar), with a bounded default expiry (e.g. 60 minutes) — never a
  standing, easy-to-forget switch.
- The apply path (see below) checks for an active, non-expired row **before** it's
  allowed to write, attributing the write to `ai-assistant` regardless of who enabled
  the session. This check lives in the service layer, not the frontend — turning the
  toggle off (or letting it expire) is a real, server-enforced gate, not cosmetic.
- Your own edits, made in your own session, are never gated by this flag and are
  never attributed to `ai-assistant` — the two identities stay cleanly separable in
  history no matter how the toggle is set.

## The apply mechanism

A small backend script, `backend/scripts/ai_workflow_apply.py` (to be written —
see `VALIDATION_PLAN.md`'s build order for sequencing relative to validation), is the
**only** way the AI collaborator touches the database. It:
- Opens a normal `SessionLocal()` DB session (same as other `scripts/*.py`).
- Resolves `ai-assistant`'s `user_id` once.
- Takes a JSON patch (new/changed `canvas_nodes`/`canvas_edges`/`static_attributes`)
  on stdin or a file path.
- Constructs a `WorkflowUpdate` (or `WorkflowCreate` for a brand-new workflow) and
  calls `WorkflowService(...).update_workflow(workflow_id, data, user_id=ai_assistant_id,
  actor_username="ai-assistant")` — the exact same call the API router makes, so every
  existing check (cycle detection, `stop-here` placement, static attributes, and once
  built, `WorkflowValidationService`) runs unchanged, and the git mirror commits under
  the `ai-assistant` identity.
- Prints back the resulting workflow id/URL and any validation findings.

This is deliberately not a raw SQL write and not a second code path — it is the
existing service layer, called from a script instead of a router, exactly like
`scripts/init_test_db.py` already does for seeding.

**Critical rule for the script and for me: always re-read the current
`canvas_nodes`/`canvas_edges` from the DB immediately before constructing a patch,
never trust what I wrote last turn from memory.** If you hand-edited and saved in the
canvas between my turns, my patch must apply on top of *your* saved state, not
silently overwrite it. This is the same clobbering hazard as any concurrent editor
without a merge story — the mitigation here is procedural (always fetch-then-patch),
not a locking mechanism, because true concurrent editing is out of scope for v1.

## Near-live view via polling, not websockets

No websocket/SSE infrastructure exists anywhere in this app today — real push would
be new infrastructure. Instead, reuse the polling convention already documented for
jobs/tasks (`refetchInterval` via TanStack Query): **only while a workflow has an
active `workflow_ai_sessions` row**, the open canvas polls that workflow's
`updated_at` every few seconds. On a change, it shows a banner — "AI updated this
workflow — Reload to view" — rather than silently swapping your canvas state out from
under an in-progress drag or edit. Polling stops the moment the session row expires,
so this costs nothing for every normal editing session that never enables it.

## Turn-taking discipline

To avoid the two of us stepping on each other:
- While I'm mid-turn (resolving defaults, drafting, applying), don't hand-edit the
  canvas — if you do, save it before your next message so it's not lost when I next
  fetch-then-patch.
- After I say a change is applied, reload before giving feedback — feedback on stale
  state produces confusing patches.
- I will describe what I'm about to build in chat *before* writing it (steps, in
  order, with the defaults I'm resolving from `AI_DEFAULTS.md`), so you can redirect
  before there's anything to undo, not just after.

---

## The loop

1. **You create a blank workflow** in the UI (gives it a name and an id) — or tell me
   the name and I create it via the apply script. Either way, one `workflow_id` is
   the target for the whole session; I never bulk-edit other workflows.
2. **You describe the use case.** In chat, not as a canvas edit yet.
3. **I propose a step plan in chat first** — which registry steps, in what order,
   which `AI_DEFAULTS.md` entries I'm resolving (credential, git repo, source,
   inventory), and anything I couldn't resolve (flagged per `AI_DEFAULTS.md`'s
   "what's still missing" — I stop and ask rather than guessing a name). You can
   redirect before anything is written.
4. **I apply the draft** via `ai_workflow_apply.py`, running the validator
   (`VALIDATION_PLAN.md` Tiers 1–3) as part of the same pass, and report findings in
   chat — a workflow with hard errors is still applied (so you can see it and fix it
   together with me) but clearly flagged as not run-ready.
5. **You get a "reload to view" banner** (from the polling described above, only
   while your AI-updates session is enabled), reload, and give feedback. ("swap step
   3 for X", "this should target a different inventory").
6. **I re-fetch current state, apply the delta, re-validate.** Repeat 5–6 until
   you're satisfied.
7. **Explicit Validate pass** (full Tiers 1–4, via the canvas "Validate" button once
   built, or via the apply script's output) before any run is considered.
8. **Safety routing for config-mutating steps:** if the workflow contains
   `configure-replace-config`, `deploy-rendered-template`, or a git-writing
   `store-artifact`, the default recommendation is to route the first run through
   `open-change-request` (stage → diff → your approval → deploy) rather than a direct
   run, per `AI_DEFAULTS.md`'s policy defaults. You can override this deliberately for
   a workflow you've already trusted, but it's never my default suggestion.
9. **You click Run** (or approve the change request). I never trigger a run and never
   approve a change request — `workflows:execute` and `change_requests:approve` are
   deliberately outside the AI actor's RBAC grant, not just a self-imposed rule.

---

## What has to exist before step 4 works at all

Checklist, matching `VALIDATION_PLAN.md`'s build order — see `IMPLEMENTATION_PLAN.md`
for the phased breakdown, file list, and sequencing:

- [ ] `ai-assistant` system role + seeded, inactive-by-default user (RBAC seed
      extension above)
- [ ] `workflow_ai_sessions` table + repository/service/router slice (enable/disable
      endpoint, expiry) — the consent-flag mechanism above
- [ ] `backend/scripts/ai_workflow_apply.py` written (check active AI session for
      the target workflow → fetch-current → construct patch →
      `WorkflowService.update_workflow`/`create_workflow` as `ai-assistant` → report)
- [ ] `AI_DEFAULTS.md` resolver step inside the apply script — cross-checks every
      name in `AI_DEFAULTS.md` still resolves, fails loudly (not silently) if one
      doesn't, so drift in that file is caught automatically rather than producing a
      bad draft
- [ ] Auto-layout helper for node `position` (reuse `topological_generations` for
      x-ordering by dependency layer; simple vertical spacing within a layer) — a
      generated workflow needs to render without overlapping nodes
- [ ] `WorkflowValidationService` Tiers 1–2 at minimum (`VALIDATION_PLAN.md`) wired
      into the apply script's output
- [ ] Minimal "Validate" UI (findings panel + node badges) so step 7 isn't chat-only
- [ ] Canvas toolbar toggle for "Enable AI updates" + the polling banner described
      above

Once those exist, we can try the loop end-to-end on a first, deliberately read-only
use case (a backup/report workflow, not a config-mutating one) before trusting it
with anything that touches real devices.
