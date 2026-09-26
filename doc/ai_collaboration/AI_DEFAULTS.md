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
| Name prefix | `[AI Draft] ` | Makes AI-originated workflows visually distinct in the workflow list until a human renames it (implies acceptance). Applies equally to a newly-*created* template's `name` (via `ai_template_apply.py`, added 2026-09-25) — the calling AI collaborator includes the prefix itself in the create patch; the script has no knowledge of this convention, same "dumb infrastructure" stance as the workflow apply script. Not applied when *editing* an existing template's name unless the edit is specifically a rename. |
| Folder | `/ai-drafts` | Keeps generated workflows out of the main folder tree until promoted. **Workflow-only** — `Template` has no `folder`/`visibility` columns at all, so there is no equivalent for AI-authored templates; don't go looking for one. |
| `get-nautobot-devices`'s `fan_out` | Unset (disabled) for ≤10 devices; **ask** the user when the target inventory's live device count is >10 | Corrected 2026-09-24 (was a flat `max_concurrency: 5`, never actually applied by any rule). See `AI_VOCABULARY.md`'s "fan-out threshold" for the check and the exact stop-and-ask wording. |
| `fan_out` block when the user says yes | `{"enabled": true, "mode": "per_device", "chunk_size": 1, "max_concurrency": 10}` | The user's own stated default (2026-09-24) for when fan-out is actually enabled — not a per-use-case guess. |
| Config-mutating steps (`configure-replace-config`, `deploy-rendered-template`, any `store-artifact`/`git-push` writing to a tracked repo) | **Direct run, not `open-change-request`** | Corrected 2026-09-24 (was the reverse). Route through `open-change-request` only when the user explicitly asks for change-request handling in that turn — never infer it from the step shape alone. See `doc/CICD_PIPELINE.md` for what `open-change-request` does when it *is* asked for. |
| `git-push` / `git-pull` / `git-clone` target branch | The git repository's own configured `branch` (Settings → Git Repositories) | Never set an explicit branch override on the step; use whatever the repository row is already configured with unless the user names a different branch in that turn. |
| `store-artifact`'s `strict_templates` | `true` (the step's own default — leave unset) | Fail the step loudly if a `filename_template` placeholder (e.g. `nautobot.location.name`) resolves empty for some device, rather than silently writing to a wrong/partial path. |
| `store-artifact`/`git-push`'s `commit_message_template` | `"commit {timestamp}"` (the step's own default — leave unset) | Use the step's built-in default unless the user asks for a specific message (e.g. including the run id or a description). |
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
  Settings → Git Repositories set up first, or must be flagged as blocked. (This is
  about git-mirroring a repo of template *files* — unrelated to `ai_template_apply.py`,
  which writes directly to the `templates` DB table and needs no git repository.)
- No safe-default resolution table exists for a template's own identity the way
  Inventories/Credentials/Sources above do — there's nothing to resolve. `category`
  is free text (the app only ever uses `"netmiko"` today; use that unless the
  request implies otherwise) and `credential_id` is optional (only needed for a
  template's pre-run commands, and if set must be a credential visible to
  `ai-assistant` — global, or `ai-assistant`'s own private one, which won't exist
  in practice).
- Only one inventory (`LAB`) exists — there's no real production inventory to
  distinguish from yet, so the "never default to production" rule is currently
  unenforceable by omission alone. Revisit this file once a second inventory exists.
