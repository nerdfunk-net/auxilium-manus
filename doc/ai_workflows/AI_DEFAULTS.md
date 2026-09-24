# AI_DEFAULTS.md

Defaults an AI collaborator (or the `ai_workflow_apply.py` tooling described in
`PROCESS.md`) resolves against when generating or editing a workflow, so it
doesn't have to ask "which credential/repo/inventory" for every use case.

**`backend/scripts/ai_defaults.yaml` is the source of truth for the values**
below — this doc carries the "why" and stays human-readable, but the tables
must match that file (small, changes rarely; keep both in sync by hand).
`backend/scripts/ai_defaults.py` loads it and live-resolves every name
against the current database (`python scripts/ai_defaults.py` from `backend/`,
with the project venv) — run it before drafting a patch to get current ids
and to catch a stale entry (renamed/deleted credential, git repo, source, or
inventory) with a clear error instead of guessing. `ai_workflow_apply.py`
also calls the same reference-existence check (via
`WorkflowValidationService` Tier 2) on whatever a patch actually contains,
and **refuses to write** if any credential/git-repository/source reference in
the patch no longer resolves — see that script's docstring.

## Rule: names are resolved live, IDs are never cached here

Everything below is a **name or category**, never a database ID. `credential_reference`
is already name-based at runtime, but `git_repository_id` and `inventory_id` are
numeric foreign keys — a row can be deleted and recreated, and a cached ID would then
silently point at nothing or at the wrong repository. Before every generation/update,
resolve each name in this file to its current ID via a live lookup (or fail loudly if
the name no longer exists — that's a signal this file is stale, not something to
paper over with a guess).

This file should be re-verified whenever credentials, git repositories, sources, or
inventories change. Last verified against the dev DB: 2026-09-23.

---

## Policy defaults

| Setting | Default | Why |
|---|---|---|
| `visibility` | `private` | AI drafts start visible only to the requesting user until reviewed. |
| `is_version_controlled` | `true` | Every AI edit gets a git-mirrored commit — free audit trail (see `doc/ARCHITECTURAL_OVERVIEW.md` → "Version-controlled workflows"). |
| Name prefix | `[AI Draft] ` | Makes AI-originated workflows visually distinct in the workflow list until a human renames it (implies acceptance). |
| Folder | `/ai-drafts` | Keeps generated workflows out of the main folder tree until promoted. |
| `fan_out.max_concurrency` | `5` | Conservative default; raise only when the use case explicitly needs higher throughput. |
| Config-mutating steps (`configure-replace-config`, `deploy-rendered-template`, any `store-artifact`/`git-push` writing to a tracked repo) | Route through `open-change-request`, not a direct run | Turns a wrong guess into a diff a human rejects, not a push that already happened — see `doc/CICD_PIPELINE.md`. |
| Target inventory for a first run | The "safe" inventory below | Never default to a production-scope inventory without the user explicitly asking to target it. |

---

## Credentials

Resolved by `credential_reference` (name) + inferred type, matching
`SHARED_SECRET_STEP_KINDS` / `GENERIC_STEP_KINDS` in
`frontend/.../workflow-import.ts`. Currently configured (global visibility):

| Name | Type | Use for |
|---|---|---|
| `cisco - noc` | `ssh` | Default SSH/Netmiko credential for device steps (`run-command`, `get-device-configs`, `configure-replace-config`, etc.) unless the use case names a different device group with its own credential. |
| `gitea` | `token` | Git remote auth for the `gitea` repository (see Git repositories below). |
| `mattermost` | `token` | Notification/chat steps targeting the `mattermost` source. |
| `nautobot` | `token` | Nautobot API auth (paired with the `nautobot` source, not usually referenced directly by `credential_reference` — resolved via the source). |
| `openbao` | `generic` | Vault/secret-manager-adjacent steps needing a generic secret, not device SSH. |
| `pyats` | `token` | pyATS shim auth. |
| `shared-secret` | `shared_secret` | `encrypt-attribute` / `decrypt-attribute` steps only. |

If a use case needs a credential not listed here, stop and ask — do not invent a name.

---

## Git repositories (by category)

`git_repository_id` is resolved from `(category, name)`. Where more than one active
repository shares a category, prefer the one listed here; ask if the use case's needs
diverge from that default.

| Category | Default repo name | Notes |
|---|---|---|
| `batfish` | `batfish` | |
| `cicd_pipeline` | `cicd-pipeline` | Used by `open-change-request` staging branches. |
| `device_configs` | `device-configs` | Two repos currently share this category (`device-configs`, `gitea`) — default to `device-configs`; use `gitea` only if the use case names it explicitly. |
| `templates`, `agent`, `csv_imports`, `csv_exports`, `workflows`, `workflow_steps` | *(none configured yet)* | No default — ask, or treat the feature as blocked on repo setup. |

---

## Sources

`*_source_id` config fields, resolved by name (Settings → Sources):

| Config field | Default value |
|---|---|
| `nautobot_source_id` | `nautobot` |
| `mattermost_source_id` | `mattermost` |
| `batfish_source_id` | `batfish` |
| `pyats_source_id` | `pyats` |
| `ise_source_id` | *(none configured)* — ask if an ISE step is needed. |

---

## Inventories

| Purpose | Inventory name | id | type | scope |
|---|---|---|---|---|
| **Safe default** (use for any newly generated workflow unless told otherwise) | `LAB` | 1 | `filter` | `global` |
| Production | *(none configured yet)* | — | — | — |

Only target a non-`LAB` inventory when the user explicitly asks for it by name in the
same turn — never infer "they probably mean production."

---

## What's still missing

- No `templates`/`agent`/`csv_imports`/`csv_exports`/`workflows`/`workflow_steps` git
  category has a configured repository yet — any use case needing those will need
  Settings → Git Repositories set up first, or must be flagged as blocked.
- Only one inventory (`LAB`) exists — there's no real production inventory to
  distinguish from yet, so the "never default to production" rule is currently
  unenforceable by omission alone. Revisit this file once a second inventory exists.
