# Git Status — review findings

Reviewed the uncommitted `git-status` step (working-tree inspection, shared git-step
outcome helper, registry entry, and config UI) on 2026-10-08.

URL checks, the per-repository lock, and secret redaction follow the existing git
steps. Three issues are specific to this change.

## High — `clean` / `dirty` does not stop the other branch

`run_git_workflow_step` returns a single outcome: `clean` or `dirty`
(`backend/workflow_steps/common/git_workflow_step.py`, the success return around
the `result_outcome(...)` call). The step runner still executes every downstream
node. A node whose incoming edge names an outcome the parent did not emit gets an
empty `WorkflowContext`.

Skip logic (`StepRunner._blocked_by_upstream_failure`) only treats a parent as
failed when that parent's `failure` outcome still carries devices. A dirty result
is stored under `dirty`, so a node wired to `clean` is not skipped.

Repository steps do real work with an empty device set. `git-push` defaults to
`commit_before_push: true` and, with no export paths, commits via `add_all` and
pushes (`backend/workflow_steps/git_push/executor.py`). A workflow
`git-status` → (`clean`) → `git-push` therefore publishes a dirty tree.
`git-clone` and `git-pull` on the inactive handle run as well.

`open-change-request` is unaffected: it returns failure when `context.devices` is
empty.

Per-device steps such as `list-contains` emit every outcome name and put devices
only in the matching bucket, so the inactive branch is a no-op. `git-status` both
omits the inactive outcome and targets steps that are not no-ops without devices.

## Medium — a failed check is also a `clean` outcome

`git-status` calls `run_git_workflow_step(..., success_outcome="clean")`
(`backend/workflow_steps/git_status/executor.py`). On a missing repository id, a
load error, or any exception from clone/fetch/auth/network, `_failure_outcomes`
emits two outcomes (`backend/workflow_steps/common/git_workflow_step.py`):

- `clean`, with `devices` cleared and `{node_id}.git_operation.success: false`
- `failure`, with devices marked failed when the incoming context had any

The persisted step status is still `failed` (`derive_step_result_status` sees the
`failure` outcome, or the `git_operation.success: false` metadata when there are
no devices). The runner keeps going.

When the incoming context has devices, identity-requiring steps on the `clean`
edge are skipped, because the `failure` outcome still holds those devices. When
the device set is empty, nothing is skipped, and the `clean` edge runs. The
stored outcome map still contains `clean` either way.

`backend/tests/unit/test_git_status_step.py::test_fetch_error_fails` asserts the
names do not include `success`. The extra outcome is named `clean`, so the test
passes.

## Low — the clean summary ignores disabled checks

`_summarize` in `backend/workflow_steps/git_status/executor.py` returns this
string whenever `status["clean"]` is true:

```text
clean: no uncommitted changes, no untracked files, in sync with origin
```

`clean` means "no enabled check added a reason". With `check_sync` off, local
commits that are not on origin leave `reasons` empty, the outcome is `clean`, and
the summary still says the tree is in sync with origin. The same line claims
there are no untracked files when `check_untracked` is off and untracked files
exist. Counts in the dirty summary are included whenever they are non-zero, even
when the matching check is disabled.

## Note — fetch errors can carry the remote URL

`GitService.fetch` puts `str(exception)` into `GitResult.message`. `collect_status`
raises that text, and `_failure_outcomes` stores it on
`{node_id}.git_operation.message`. `redact_secrets_in_data` does not scan free-text
messages. A failed `git fetch` often includes the remote URL; after
`origin.set_url(auth_url)` that URL can contain the token
(`backend/services/git/auth.py::build_auth_url`). The same path already exists for
`git-pull` and `git-push`.
