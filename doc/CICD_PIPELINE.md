# CI/CD Pipeline — Staged Change Requests

A review gate for config changes: a **stage run** renders device configs, pushes them to a
per-change git branch, and records a **Change Request**; a human (or a signed git webhook)
approves it; a separate **deploy run** then applies the change to devices. The review can
take arbitrarily long because it is a database row, not a suspended workflow.

This complements `doc/WORKFLOW-STEPS.md` (the `open-change-request` step contract) and
`doc/SCHEDULES.md` (the "external event → fresh WorkflowRun" dispatch pattern this reuses).
Read those for the parts this doc does not repeat.

**Status:** Implemented. Backend (data model, change-request service + routes,
the `open-change-request` step, the inbound git webhook, the
`use_change_request_branch` override on `git-pull`/`git-clone`, and the
reconcile/expire sweep in `PurgeWorkflowRunRetention`) and the full frontend
(Change Requests view, step ConfigPanel, git-repo webhook settings). See
`~/.claude/plans/that-sounds-intriguing-i-tidy-lake.md` for the phasing.

---

## 1. The problem

Auxilium Manus can already render configs (`render-jinja-template`), talk to git
(`git-*`), and apply config with rollback (`configure-replace-config`). What was missing:
an approval gate that outlives a long review. A mid-workflow `ctx.aio_wait_for_event`
pause cannot be used — the `execute_steps` durable task is capped at 24 h
(`backend/hatchet/workflows/workflow_run/__init__.py`). So the pipeline is two decoupled
`WorkflowRun`s joined by a `ChangeRequest` row.

## 2. How the pipeline looks

```
STAGE RUN (ordinary workflow)
  … → render-jinja-template → open-change-request
                                 │  (per-repo Redis lock cr-stage:{repo_id})
                                 │  git checkout -B manus/cr-42 <base>
                                 │  write rendered files, commit, push branch
                                 │  diff <base>..manus/cr-42  → diff artifact
                                 ▼
                    ChangeRequest(status="staged", branch, commit_sha,
                                  device_ids, run_inputs, diff_artifact_id)
  run finishes: status="success"

APPROVAL
  UI  "Approve & Deploy"  (change_requests:approve)   staged → deploying + dispatch
  webhook  POST /api/webhooks/git/{repo_id}  (HMAC)   commit_sha match:
      git_repositories.webhook_auto_deploy = false →  staged → approved   (UI "Deploy" later)
      git_repositories.webhook_auto_deploy = true  →  staged → deploying + dispatch

DEPLOY RUN (separate workflow, change_request_id=42, trigger_type=webhook|manual)
  git-clone (use_change_request_branch=true → checks out manus/cr-42)
    → get-from-config → configure-replace-config → compare-pyats-snapshot
  run finishes → reconcile → ChangeRequest.status = deployed | failed
```

### Status model

| status | meaning | leaves to |
|---|---|---|
| `staged` | branch pushed, awaiting review | `approved`, `deploying`, `rejected`, `expired` |
| `approved` | reviewed (webhook, no auto-deploy), awaiting a deploy click | `deploying`, `rejected` |
| `deploying` | a deploy run is in flight | `deployed`, `failed` |
| `deployed` | deploy run succeeded | — |
| `failed` | deploy run failed / dispatch failed | — |
| `rejected` | a reviewer declined it | — |
| `expired` | TTL elapsed while still `staged` | — |

Every transition is an atomic `UPDATE … WHERE id=:id AND status IN :expected`. A UI click
and a webhook that race resolve to exactly one deploy run.

## 3. How to use it

### 3.1 One-time setup

1. **Git repository** — Settings → Git Repositories. Add (or pick) the repo that will hold
   rendered configs. Optionally set:
   - **Webhook secret** — GitHub HMAC secret or GitLab token. Enables
     `POST /api/proxy/webhooks/git/{id}`.
   - **Webhook auto-deploy** — off (default): a signed webhook only marks the CR
     `approved`; a human still clicks **Deploy**. On: a signed webhook dispatches the
     deploy run immediately (full GitOps; the review happened in the PR).
   Copy the webhook URL shown in the dialog into your git host's webhook config
   (content-type `application/json`, events: *push* — and optionally *pull request* /
   *merge request*).
2. **Permissions** — grant `change_requests:read` (view CRs and diffs) and
   `change_requests:approve` (approve / deploy / reject). `viewer` gets `read`; `admin`
   gets both.

### 3.2 Build the stage workflow

Any workflow whose last step is **Open Change Request**. Typical shape:

```
get-nautobot-devices → fan-in → render-jinja-template → open-change-request
```

`open-change-request` config:

| field | purpose |
|---|---|
| `git_repository_id` | where the CR branch is pushed |
| `content_source` / `source_step_node_id` | the upstream `render-jinja-template` node whose output is committed |
| `filename_template` | e.g. `{device.name}.cfg` |
| `branch_template` | default `manus/cr-{run.id}` |
| `commit_message_template`, `title_template` | free text with `{run.id}`, `{workflow.name}` |
| `deploy_workflow_id` | the workflow that deploys this change (may also be chosen at approval time) |
| `expires_after_hours` | TTL for an un-actioned CR (default 168) |

**Placement rule:** `open-change-request` creates a branch on a shared working tree — it is
**not fan-out-safe**. Put it after any Fan In node, never inside a fan-out branch. Do not
run two stage workflows against the same repository concurrently (a per-repo Redis lock
serialises the git sequence, but keep pipelines one-per-repo).

### 3.3 Build the deploy workflow

An ordinary workflow, composed from existing steps. It reads the CR branch by setting
**`use_change_request_branch = true`** on its `git-clone` (or `git-pull`) step — when the
run was triggered by a CR approval, that step targets `manus/cr-{id}` instead of the repo
default branch (ordinary runs are unaffected). Prefer **`git-clone`**: it does a fresh
checkout of the CR branch. `git-pull` fetches the CR branch and merges it into whatever
the working tree is currently on, which is only equivalent when the CR branch
fast-forwards from the default branch. Typical shape:

```
git-clone (use_change_request_branch=true)
  → get-from-config → configure-replace-config → compare-pyats-snapshot
```

`configure-replace-config` gives you a device-native pre/post diff and IOS
`configure confirm` rollback; `compare-pyats-snapshot` validates operational state after.

### 3.4 Review and deploy

1. **Change Requests** (sidebar) lists every CR. Open one to see metadata, the unified
   diff, and links to the stage run and (once it exists) the deploy run.
2. `staged` → **Approve & Deploy** dispatches the deploy run (`staged → deploying`).
3. If a webhook marked it `approved` (auto-deploy off), click **Deploy**
   (`approved → deploying`).
4. **Reject** (with an optional reason) closes a `staged`/`approved` CR.
5. When the deploy run reaches a terminal status the CR flips to `deployed` or `failed`
   (visible on next poll / open).

### 3.5 The webhook

`POST /api/proxy/webhooks/git/{git_repository_id}` — unauthenticated, protected by:

- HMAC-SHA256 (`X-Hub-Signature-256`) for GitHub or shared-token (`X-Gitlab-Token`) for
  GitLab, constant-time compared against the repo's webhook secret. **Missing secret →
  `401` (fail closed).**
- Sliding-window rate limit per repo + client IP.
- Replay dedup on the delivery id (`X-GitHub-Delivery` / `X-Gitlab-Event-UUID`), 24 h.

Correlation: any pushed commit SHA equal to a `staged` CR's `commit_sha` triggers that CR
(the CR-branch push itself carries the SHA — no merge required). Responses:
`202 {"status":"approved"|"reviewed", "change_request_id": N}`, `200 {"status":"ignored"}`
(no match — never reveals whether CRs exist), `200 {"status":"duplicate"}` (replay),
`401`/`429` otherwise.

## 4. Implementation

### 4.1 Data model

- **`change_requests`** (`backend/core/models/change_requests.py`) — links
  `source_workflow_id` / `source_run_id` → `deploy_workflow_id` / `deploy_run_id`,
  `git_repository_id`, `base_branch`, `branch`, `commit_sha`, captured `device_ids` /
  `run_inputs`, `diff_artifact_id` / `diff_stats`, `status`, approval/rejection audit
  columns, `expires_at`. Partial unique index on `(git_repository_id, commit_sha)` where
  `status in ('staged','approved','deploying')`.
- **`workflow_runs.change_request_id`** (`backend/core/models/runs.py`) — nullable FK; the
  deploy run's link back to its CR (drives `reconcile` and the deploy-branch override).
- **`git_repositories.webhook_secret_encrypted`** (Fernet, `core.crypto.EncryptionService`)
  and **`git_repositories.webhook_auto_deploy`** (`backend/core/models/git.py`).
- Schema is created by `AutoSchemaMigration` at startup (`doc/MIGRATION_SYSTEM.md`); no
  migration files. Two gotchas of the auto-migration's `ADD COLUMN` path: a `NOT NULL`
  column needs a Python-side `default=` (not just `server_default`) to backfill existing
  rows — hence `webhook_auto_deploy` uses `default=False`; and it does not emit the FK
  `REFERENCES` clause, so `workflow_runs.change_request_id` is a plain nullable integer at
  the DB level until a real migration adds the constraint (the app never relies on the
  cascade).

### 4.2 Backend

| layer | file | role |
|---|---|---|
| Pydantic | `backend/models/change_requests.py` | request/response + `ChangeRequestStatus` literal |
| Repository | `backend/repositories/change_request_repository.py` | `BaseRepository`; `transition()` = atomic conditional update; `find_active_for_commit`, `list_visible`, `list_in_flight` |
| Service | `backend/services/change_requests/change_request_service.py` | `create_from_step`, `approve`, `mark_reviewed`, `deploy`, `reject`, `reconcile`, `expire_sweep` |
| Service | `backend/services/change_requests/webhook_service.py` | signature verify → correlate → approve/mark-reviewed |
| Helper | `backend/services/change_requests/repo_lock.py` | per-repo Redis advisory lock (fail-soft) |
| Helper | `backend/core/webhook_signatures.py` | `verify_github_signature`, `verify_gitlab_token` (`hmac` / `secrets.compare_digest`) |
| Run engine | `backend/services/execution/run_service.py` | `_create_and_dispatch_run(...)` — shared by manual / approve / webhook, reuses `resolve_dispatch_workflow(...).run_no_wait(...)` |
| Step | `backend/workflow_steps/open_change_request/` | `executor.py` + `config.py`; registered in `step_registry.py` and `registry.yaml` |
| Router | `backend/routers/change_requests.py` | JWT + `change_requests:read\|approve`: list / get / diff / approve / deploy / reject |
| Router | `backend/routers/webhooks.py` | unauthenticated `POST /webhooks/git/{repo_id}` |
| RBAC | `backend/services/auth/rbac_seed.py` | `change_requests:read`, `change_requests:approve` |
| Git | `backend/services/git/service.py` | `checkout_new_branch(repo, name, base_ref)`, `diff_refs(repo, a, b)` |
| Deploy branch | `backend/workflow_steps/common/git_workflow_step.py` + `change_request_context.py` | `use_change_request_branch` on `git-pull` / `git-clone` |
| Sweep | `backend/hatchet/workflows/purge_retention.py` | `expire_sweep()` + `reconcile_all_in_flight()` on the existing cron |

The `open-change-request` executor mirrors `git_push/executor.py`: load repo dict
(`git_repository_loader`), pull rendered content per device (`content_resolver`), take the
per-repo lock, `checkout_new_branch`, write files (`GitArtifactSink.write_text`),
`commit`, `push(branch=…)`, `diff_refs` → 2 MB-capped `comparison_diff` artifact, then
`ChangeRequestService.create_from_step(...)`. Outcomes `success` / `failure`; `ValueError`
→ `configuration`, `RuntimeError` → `execution`.

Approval never re-validates `run_inputs` — they were validated when the stage run was
triggered and are replayed verbatim into the deploy run.

### 4.2b HTTP endpoints

| method | path | auth | notes |
|---|---|---|---|
| `GET` | `/api/change-requests` | `change_requests:read` | list; optional `?status=` (repeatable) |
| `GET` | `/api/change-requests/{id}` | `change_requests:read` | reconciles on read |
| `GET` | `/api/change-requests/{id}/diff` | `change_requests:read` | the unified-diff artifact |
| `POST` | `/api/change-requests/{id}/approve` | `change_requests:approve` | `staged → deploying` + dispatch; body `{deploy_workflow_id?}` |
| `POST` | `/api/change-requests/{id}/deploy` | `change_requests:approve` | `approved → deploying` + dispatch (after a webhook review) |
| `POST` | `/api/change-requests/{id}/reject` | `change_requests:approve` | body `{reason?}` |
| `POST` | `/api/webhooks/git/{git_repository_id}` | **none** (HMAC / shared secret) | see §3.5 |

### 4.3 Frontend

Feature dir `frontend/src/components/features/change-requests/`.

| area | file |
|---|---|
| Route stub | `frontend/src/app/(dashboard)/change-requests/page.tsx` |
| Page (master list + detail) | `change-requests-page.tsx` |
| Detail pane | `components/change-request-detail-pane.tsx` (Approve & Deploy / Deploy / Reject dialogs, diff) |
| Status badge | `components/change-request-status-badge.tsx` (7 statuses) |
| Diff view | `components/unified-diff-view.tsx` (line-coloured `<pre>`, truncation notice) — plus `unified-diff-view.test.ts` |
| Hooks | `hooks/use-change-requests-query.ts` (list, polls while any row `deploying`), `hooks/use-change-request-query.ts` (detail, polls while `deploying`), `hooks/use-change-request-diff-query.ts`, `hooks/use-change-request-mutations.ts` (`approve` / `deploy` / `reject`) |
| Types | `types/change-request.ts` |
| Query keys | `frontend/src/lib/query-keys.ts` → `changeRequests.{list,detail,diff}` |
| Sidebar | `frontend/src/components/layout/app-sidebar.tsx` — "Change Requests" (`change_requests:read`) |
| Step ConfigPanel | `frontend/src/components/features/workflow-steps/open-change-request/index.tsx` + `frontend/src/lib/plugin-ui-registry.ts` |
| Git repo dialog | `frontend/src/components/features/settings/dialogs/git-repository-dialog.tsx` (webhook secret, auto-deploy switch, copyable webhook URL) |

Detail-pane buttons are gated on `hasPermission(user, "change_requests", "approve")` and
the CR status; a `deploying` CR polls until terminal.

### 4.4 Rules & edge cases

| case | behaviour |
|---|---|
| Duplicate commit | Partial unique index → `create_from_step` raises `ConflictError`; the step fails with `execution`. |
| Button + webhook race | Atomic `transition()` — exactly one `deploying`; the loser gets `ConflictError` / a no-op. |
| Webhook, no secret set | `401` fail-closed. |
| Webhook replay | Deduped on delivery id (24 h) → `200 {"status":"duplicate"}`. |
| Webhook, no matching CR | `200 {"status":"ignored"}` — never leaks CR existence. |
| Pre-existing remote CR branch | `checkout -B` + force-push; not a failure (retry-friendly). |
| Deploy run fails | `reconcile` → CR `failed`, `deploy_error` copied from the run. |
| CR un-actioned past TTL | Sweep → `expired`. |
| `open-change-request` inside a fan-out branch | Unsupported — must be placed after Fan In. |
| Concurrent stage runs, same repo | Serialised by the `cr-stage:{repo_id}` Redis lock; still discouraged. |
| Deploy run without `use_change_request_branch` | Deploys the repo default branch — a config mistake, not enforced. |

### 4.5 Security notes

- The webhook endpoint is the one deliberate non-proxy, non-JWT entry point. It is
  protected by HMAC / shared-secret (constant-time), per-repo+IP rate limiting, replay
  dedup, and fail-closed-on-missing-secret. Bodies are non-committal. It must be reachable
  from the git host (ingress note).
- The webhook secret is stored Fernet-encrypted (`core.crypto`), never returned by the API
  (only `has_webhook_secret: bool`).
- `webhook_auto_deploy = true` means a valid signed push pushes config to devices with no
  Auxilium Manus UI interaction — enable it only for repos whose PR review is the gate.

### 4.6 Tests

Backend unit (`backend/tests/unit/`): `test_change_request_service.py` (state machine,
button↔webhook race, reconcile, expire, duplicate-commit conflict),
`test_open_change_request_executor.py` (branch templating, `checkout -B`, force-push, diff
artifact, CR row, failure paths), `test_webhook_signatures.py`, `test_webhook_service.py`
(auto-deploy vs mark-reviewed, bad/missing signature, fail-closed, replay dedup, GitLab
`checkout_sha`), `test_git_service_branch_diff.py`, `test_change_request_deploy_branch.py`
(`use_change_request_branch` override, `maybe_reconcile_deploy_run`),
`test_run_service_delete.py` (updated for the new FK). Frontend:
`components/change-requests/components/unified-diff-view.test.ts`.

**Not yet written:** end-to-end integration tests against a real Gitea
(`backend/tests/integration/` — opt-in, not in the coverage ratchet): a stage run pushing
`manus/cr-*` and an approve dispatching a deploy run; a signed inbound webhook advancing a
change request with replay/bad-signature cases.
