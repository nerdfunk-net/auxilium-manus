# Plan: Backend code quality fixes from the 2026-10-09 review

Source: `doc/analysis/BACKEND_CODE_QUALITY_20261009.md` (findings G1–G4, D1–D4, L1–L2, P1–P4).
Tree the "code before" blocks were taken from: `2fd2fdc`. Line numbers below are from that tree.
Status: **not started**.

This plan is the implementation. Do not re-review the backend, do not widen the file list, and do not choose a different design when a decision in §0 already locks it. Where a long function is split, move the existing statements in order. Do not rewrite conditions, messages, or calls inside a moved block.

Run tests from `backend/` with the project venv (`source ../.venv/bin/activate`).

| Phase | Findings | Summary | Depends on |
|---|---|---|---|
| 1 | G1, P2, P3 | One authenticated-remote helper; `clone` returns a result; repo config is typed inside `GitService` | — |
| 2 | G2 | One `ensure_working_tree`; the two sync entry points become wrappers | 1 |
| 3 | G4 | Connection test stops building its own clone URL | 1 |
| 4 | D1 | Shared `fail_device` and `build_success_failure_outcomes` | — |
| 5 | G3, P4 | One commit-log reader; git file and debug services stop raising HTTP errors | 1 |
| 6 | P1 | Narrow `except Exception` in the nine files the review listed | 1, 5 |
| 7 | L1 | Split the seven functions over 150 lines by moving blocks | — |
| 8 | D2, D4 | One custom-field fetch; shared source HTTP error mapping | — |
| 9 | L2, D3 | Move the named long functions out of the long files; do not delete the old Nautobot managers | 7 |
| 10 | — | Verification | 1–9 |

## 0. Decisions (do not reopen)

**D1 — Result objects for clone, pull, push, fetch, and commit (P2).** `open_or_clone` still raises. Its contract is "return a `Repo`". Every other public git operation returns a result and does not raise `GitCommandError` or `UnsafeURLError`. `_clone_fresh` stays raise-based and is private. Public `clone` catches and returns `CloneResult`.

**D2 — `GitRepoConfig` is internal (P3).** `GitService` methods keep accepting `dict`. The first line of each method is `config = as_repo_config(repository)`. The `"main"` default lives only in `as_repo_config`. Callers are not converted in this plan.

**D3 — Sync entry points keep their names (G2).** `clone_or_pull`, `remove_and_clone`, `sync_repository`, and `remove_and_sync` stay importable. Tests patch those names. The algorithm lives in `ensure_working_tree` only.

**D4 — Debug push uses `GitService.push` (G1).** The debug test file is still written and committed locally by `_commit_debug_change`. Only the remote push is replaced. Do not delete the read/write/delete debug tests.

**D5 — Commit-log shape (G3).** `models.git.commit_to_dict` is the only commit dict. `GitVersionControlService.get_commits` calls `GitCacheService.get_commits` and returns that list. It keeps the "branch not found" `ValueError`. It drops its own cache key `repo:{id}:commits:{branch}`. `GitFileService.get_file_history` keeps its return dict (`file_path`, `from_commit`, `total_commits`, `commits` with `change_type`). The walk moves into `GitCacheService.get_file_history`, which returns that dict. `GitFileService` only checks the cache and calls the cache service.

**D6 — Connection test stays a subprocess shallow clone (G4).** It must not clone into the shared working tree. Delete `_build_clone_url`. Take the clone URL from `GitAuthenticationService.setup_auth_environment`.

**D7 — Step helpers keep local names (D1).** Each executor keeps `_fail_device` and `_build_outcomes` as a one-line wrapper that passes `_STEP_ID` or the local outcome name. Call sites inside the executor do not change.

**D8 — Do not merge these pairs.** The review's normalized AST match replaced string constants longer than 8 characters, so these are not safe to fold blindly:

* `_run_config_mode_on_device_logged` and `_deploy_on_device_logged`
* `_do_request` in the pyATS and Mattermost clients
* `build_bgp_facts_outcomes` and `build_ospf_facts_outcomes`
* `_build_filter_outcomes` / `_build_update_content_outcomes`
* `_build_upload_outcomes` / `_build_deploy_outcomes`

Leave them. D1 covers the two groups whose bodies are the same token for token.

**D9 — Two Nautobot packages stay two packages (D2, D3).** Do not delete `InterfaceManager` or `DeviceManager`. Do not move inventory query code into `services/nautobot/devices/`.

**D10 — P1 is the nine files in the review table, not all 416 handlers.**

**D11 — Do not split** `services/credentials/credentials_service.py` or `services/sources/nautobot/query_service.py`. The credential service is not a second git stack. The live GraphQL path already sits in `live_query_mixin.py`.

---

## 1. Authenticated remote helper, clone result, typed repo config (G1, P2, P3)

### 1.1 `GitRepoConfig`

New file `backend/services/git/repo_config.py`.

Code after:

```python
"""Typed view of the repository dict GitService already receives.

Callers keep passing dicts. The branch default lives here and nowhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GitRepoConfig:
    url: str
    branch: str = "main"
    name: str = ""
    auth_type: str = "token"
    credential_name: str | None = None
    verify_ssl: bool = True
    git_author_name: str | None = None
    git_author_email: str | None = None
    id: int | None = None
    path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "branch": self.branch,
            "name": self.name,
            "auth_type": self.auth_type,
            "credential_name": self.credential_name,
            "verify_ssl": self.verify_ssl,
            "git_author_name": self.git_author_name,
            "git_author_email": self.git_author_email,
            "id": self.id,
            "path": self.path,
        }


def as_repo_config(repository: GitRepoConfig | dict[str, Any]) -> GitRepoConfig:
    if isinstance(repository, GitRepoConfig):
        return repository
    raw_id = repository.get("id")
    return GitRepoConfig(
        url=str(repository.get("url") or ""),
        branch=str(repository.get("branch") or "main"),
        name=str(repository.get("name") or ""),
        auth_type=str(repository.get("auth_type") or "token"),
        credential_name=repository.get("credential_name"),
        verify_ssl=bool(repository.get("verify_ssl", True)),
        git_author_name=repository.get("git_author_name"),
        git_author_email=repository.get("git_author_email"),
        id=int(raw_id) if raw_id is not None else None,
        path=repository.get("path"),
    )
```

`GitAuthenticationService.setup_auth_environment` keeps taking a dict. Pass `config.as_dict()` into it. Do not change `auth.py` in this phase.

### 1.2 `CloneResult` and `_run_on_origin`

In `backend/services/git/service.py`, next to `PullResult`.

Code before (`pull`, from line 263; `push` from 367 and `fetch` from 544 repeat the same block):

```python
try:
    validate_git_remote_url(repository.get("url", ""), resolve_dns=True)
    if repo is None:
        repo = self.open_or_clone(repository)
    branch = repository.get("branch", "main")
    with self._auth.setup_auth_environment(repository) as (
        auth_url, username, token, ssh_key_path,
    ):
        overrides = build_git_env_overrides(repository, ssh_key_path=ssh_key_path)
        origin = repo.remotes.origin
        original_url = None
        try:
            if token and not ssh_key_path:
                original_url = list(origin.urls)[0]
                origin.set_url(auth_url)
            with repo.git.custom_environment(**overrides):
                origin.pull(branch)
            # ... count commits, return PullResult(success=True, ...)
        finally:
            if original_url:
                try:
                    origin.set_url(original_url)
                except Exception:
                    pass
except GitCommandError as e:
    return PullResult(success=False, message=f"Pull failed: {str(e)}", branch=...)
except Exception as e:
    return PullResult(success=False, message=f"Unexpected error: {str(e)}", branch=...)
```

Code after. Add the helper and `CloneResult`. `pull`, `push`, and `fetch` keep their public signatures and their success-result fields (`commits_pulled`, `pushed`, `branch`). They lose the copied URL swap and the `except Exception` (that handler is finished in phase 6; delete it in this phase so it is not reintroduced).

```python
@dataclass
class CloneResult(GitResult):
    repo: Repo | None = None


def _restore_origin_url(origin: Any, original_url: str | None) -> None:
    if not original_url:
        return
    try:
        origin.set_url(original_url)
    except GitCommandError:
        logger.warning("Failed to restore origin URL after authenticated git call")


def _run_on_origin(self, repository: dict, repo: Repo | None, fn):
    """Validate URL, apply auth, run fn(origin, repo, branch), restore the URL.

    fn runs inside the authenticated environment. Remote failures raise
    GitCommandError or UnsafeURLError; this method does not catch them.
    """
    config = as_repo_config(repository)
    validate_git_remote_url(config.url, resolve_dns=True)
    if repo is None:
        repo = self.open_or_clone(config.as_dict())
    with self._auth.setup_auth_environment(config.as_dict()) as (
        auth_url, _username, token, ssh_key_path,
    ):
        overrides = build_git_env_overrides(config.as_dict(), ssh_key_path=ssh_key_path)
        origin = repo.remotes.origin
        original_url = None
        try:
            if token and not ssh_key_path:
                original_url = list(origin.urls)[0]
                origin.set_url(auth_url)
            with repo.git.custom_environment(**overrides):
                return fn(origin, repo, config.branch)
        finally:
            _restore_origin_url(origin, original_url)
```

`pull` after (the commit-count block stays exactly as it is today, lines 297–311):

```python
def pull(self, repository: dict, repo: Repo | None = None) -> PullResult:
    config = as_repo_config(repository)
    try:
        def _do(origin, repo, branch):
            head_before = repo.head.commit.hexsha if repo.head.is_valid() else None
            origin.pull(branch)
            head_after = repo.head.commit.hexsha if repo.head.is_valid() else None
            if head_before and head_after and head_before != head_after:
                commits_pulled = sum(1 for _ in repo.iter_commits(f"{head_before}..{head_after}"))
            else:
                commits_pulled = 0
            return commits_pulled

        commits_pulled = self._run_on_origin(repository, repo, _do)
        return PullResult(
            success=True,
            message=f"Successfully pulled {commits_pulled} commits",
            commits_pulled=commits_pulled,
            branch=config.branch,
        )
    except GitCommandError as exc:
        return PullResult(success=False, message=f"Pull failed: {exc}", branch=config.branch)
    except UnsafeURLError as exc:
        return PullResult(success=False, message=f"Repository URL is not allowed: {exc}", branch=config.branch)
```

`push` after. Keep the `force` refspec and the `PushInfo.ERROR` check (lines 415–428) inside `_do`. Return `PushResult` the same way, catching only `GitCommandError` and `UnsafeURLError`.

`fetch` after. `_do` calls `origin.fetch()` and returns `GitResult(success=True, message=...)`. Same two except clauses.

`clone` after. `_clone_fresh` is unchanged and still raises. Replace `repository.get("branch", "main")` inside `_clone_fresh` with `as_repo_config(repository).branch`.

```python
def clone(self, repository: dict, target_path: str | Path | None = None) -> CloneResult:
    config = as_repo_config(repository)
    path = Path(target_path) if target_path else self.get_repo_path(config.as_dict())
    try:
        repo = self._clone_fresh(config.as_dict(), path)
        return CloneResult(success=True, message=f"Cloned {config.name}", repo=repo)
    except UnsafeURLError as exc:
        return CloneResult(success=False, message=f"Repository URL is not allowed: {exc}")
    except GitCommandError as exc:
        return CloneResult(success=False, message=str(exc))
```

### 1.3 Callers of `clone` that today expect an exception

`workflow_steps/git_clone/executor.py` currently calls `git_service.clone(repository)` and relies on the exception. After:

```python
result = git_service.clone(repository)
if not result.success:
    raise RuntimeError(result.message)
```

Do not change `open_or_clone` callers (`git_pull`, `git_push`, `WorkflowGitService`, `GitArtifactSink`, `working_tree_status`, `shared_utils.get_git_repo_by_id`). They still get a `Repo` or an exception.

### 1.4 Debug push

Code before (`services/git/debug_service.py` `_push_debug_commit`, from line 296): sets `origin` URL, `custom_environment`, `origin.push`, restores the URL, interprets flags.

Code after. Delete the URL-swap body. Keep `_debug_result` field names the current tests assert (`commit_sha`, `branch`, `verified`, `push_summary`).

```python
def _push_debug_commit(*, repo, repository, commit_sha, commit_message, test_file_path, git_service) -> dict:
    result = git_service.push(repository, repo=repo)
    if not result.success:
        return _debug_result(
            False,
            result.message,
            error=result.message,
            error_type="PushError",
            commit_sha=commit_sha,
            suggestion="Check repository permissions and credentials",
        )
    return _debug_result(
        True,
        "Push test successful - changes pushed to remote",
        commit_sha=commit_sha,
        commit_message=commit_message,
        branch=result.branch,
        remote="origin",
        file_path=str(test_file_path),
        verified=True,
    )
```

`test_push` already receives `git_auth_service`. Pass `service_factory.build_git_service()` (or the service the debug service already holds — construct `GitService()` in `GitDebugService.__init__` and use `self._git`) instead of using `git_auth_service` for the push. Leave `git_auth_service` in the signature so the router does not change. `_require_push_auth` stays; it answers "is push configured?" before the attempt.

### 1.5 Tests

Update, do not replace:

* `tests/unit/test_git_service_engine.py` — `clone` returns `CloneResult`. A `GitCommandError` from `Repo.clone_from` yields `success is False` and does not raise. `pull` / `push` / `fetch` still return result objects. Add one test that `pull`, `push`, and `fetch` call `origin.set_url` once each (the helper), by patching `origin.set_url` and asserting a single call for a token repo.
* `tests/unit/test_git_debug_service.py` — patch `GitService.push`. Assert the debug service does not call `origin.push`.
* `tests/unit/test_git_workflow_steps.py` — git-clone step raises `RuntimeError` when `CloneResult.success` is false.

Done when those three modules pass and `rg "origin.set_url" backend/services/git` shows the call only in `_run_on_origin` and `_restore_origin_url`.

---

## 2. One working-tree sync (G2)

### 2.1 `ensure_working_tree`

Add to `backend/services/git/sync.py`. This replaces the bodies of `clone_or_pull` and of `GitOperationsService.sync_repository` / `remove_and_sync`.

```python
class PullFailure(StrEnum):
    USE_CACHE = "use_cache"
    RECORD_ERROR = "record_error"


@dataclass
class WorkingTree:
    success: bool
    path: Path
    message: str
    used_cache: bool = False


def ensure_working_tree(
    repository: dict[str, Any],
    *,
    force: bool = False,
    on_pull_failure: PullFailure = PullFailure.USE_CACHE,
) -> WorkingTree:
    name = repository.get("name") or repository.get("id")
    if not str(repository.get("url") or "").strip():
        return WorkingTree(False, Path(), f"Git repository '{name}' has no URL configured")

    git_service = service_factory.build_git_service()
    repo_dir = git_service.get_repo_path(repository)
    repo_existed = (repo_dir / ".git").is_dir() and not force

    if not repo_existed:
        cloned = git_service.clone(repository)
        if not cloned.success:
            return WorkingTree(False, repo_dir, cloned.message)
        return WorkingTree(True, repo_dir, cloned.message)

    repo = git_service.open_or_clone(repository)
    pulled = git_service.pull(repository, repo=repo)
    if pulled.success:
        return WorkingTree(True, repo_dir, pulled.message)
    if on_pull_failure is PullFailure.USE_CACHE:
        logger.warning("Pull failed for '%s': %s — using cached copy", name, pulled.message)
        return WorkingTree(True, repo_dir, pulled.message, used_cache=True)
    return WorkingTree(False, repo_dir, pulled.message)
```

`open_or_clone` can still raise `UnsafeURLError` or `GitCommandError`. Catch those two around the `repo_existed` branch and return `WorkingTree(False, ..., str(exc))`. Do not catch `Exception`.

Code before (`clone_or_pull`, `sync.py` lines 22–56): clones via `open_or_clone`, then pulls, and on pull failure logs and returns the path anyway.

Code after:

```python
def clone_or_pull(repository: dict[str, Any]) -> Path:
    tree = ensure_working_tree(repository, on_pull_failure=PullFailure.USE_CACHE)
    if not tree.success:
        raise RuntimeError(tree.message)
    return tree.path


def remove_and_clone(repository: dict[str, Any]) -> Path:
    tree = ensure_working_tree(repository, force=True, on_pull_failure=PullFailure.RECORD_ERROR)
    if not tree.success:
        raise RuntimeError(tree.message)
    return tree.path
```

Empty-URL and unsafe-URL messages stay the ones `clone_or_pull` raises today (`ValueError` for an empty URL, `ValueError` whose text contains `unsafe URL` for `UnsafeURLError`). Map those two cases before the generic `RuntimeError`:

```python
if not str(repository.get("url") or "").strip():
    raise ValueError(f"Git repository '{name}' has no URL configured")
# UnsafeURLError message from CloneResult.message already starts with
# "Repository URL is not allowed". clone_or_pull re-raises that as ValueError
# so existing tests on the "unsafe URL" wording still pass.
if not tree.success and "not allowed" in tree.message:
    raise ValueError(tree.message)
```

Put the empty-URL check in the wrappers, not only inside `ensure_working_tree`, so the exception type stays `ValueError`.

### 2.2 `GitOperationsService`

Code before (`sync_repository`, `operations.py` lines 192–241): its own clone-or-pull, with `UnsafeURLError` / `GitCommandError` / `Exception` mapped onto `SyncResult`.

Code after:

```python
def sync_repository(self, repository: dict[str, Any], force_clone: bool = False) -> SyncResult:
    tree = ensure_working_tree(
        repository,
        force=force_clone,
        on_pull_failure=PullFailure.RECORD_ERROR,
    )
    return SyncResult(
        success=tree.success,
        message=tree.message,
        commits_behind=0,
        commits_ahead=0,
        repository_path=str(tree.path) if tree.success else None,
    )


def remove_and_sync(self, repository: dict[str, Any]) -> SyncResult:
    return self.sync_repository(repository, force_clone=True)
```

Delete `_map_clone_error_message` if nothing else calls it. Keep `sync_and_record` and `remove_and_sync_and_record` unchanged: they already turn `success=False` into `SyncExecutionError` and an `error:<uuid>` status.

`_clone_fresh` still deletes the directory, so `force=True` does not need a second `rmtree`. `force_clone=True` on an existing git dir must still clone fresh. `GitService.clone` / `_clone_fresh` already removes `target_path` when it exists. `ensure_working_tree(..., force=True)` skips the pull and calls `clone`, which removes the dir. That preserves `remove_and_sync`.

### 2.3 Tests

* `tests/unit/test_git_sync.py` — still patches `build_git_service`. Assert `clone_or_pull` returns the path when `pull` returns `success=False` (`used_cache`). Assert `remove_and_clone` calls `clone` and does not call `pull`.
* `tests/unit/test_git_operations_service.py` — `sync_repository` returns `success=False` when `pull` fails. It must not call `clone` when `.git` exists. `remove_and_sync` calls `clone`.

Done when those two modules pass and `rg "def sync_repository|def clone_or_pull" backend` shows each function body calling `ensure_working_tree` only.

---

## 3. Connection test uses the shared auth URL (G4)

File: `backend/services/git/connection.py`.

Code before (`_build_clone_url`, from line 227, and the call at line 131): the service builds a clone URL itself, then `_test_clone` runs `git clone --depth 1` via `subprocess`.

Code after. Delete `_build_clone_url`. Inside `test_connection`, after the existing `validate_git_remote_url` call:

```python
repository = {
    "url": test_request.url,
    "branch": test_request.branch,
    "auth_type": test_request.auth_type,
    "credential_name": test_request.credential_name,
    "verify_ssl": test_request.verify_ssl,
}
with self._auth.setup_auth_environment(repository) as (clone_url, _username, _token, ssh_key_path):
    env = merge_git_environ(build_git_env_overrides(repository, ssh_key_path=ssh_key_path))
    return self._test_clone(clone_url=clone_url, branch=test_request.branch, test_path=test_path, env=env, test_request=test_request)
```

`_test_clone` stays a subprocess shallow clone into a temp directory. Do not call `GitService.clone` here (D6). Delete any second auth-URL string construction in this file.

`tests/unit/test_git_connection_service.py` must still pass, including the `file://` rejection and the `verify_ssl=False` case. Add one assertion that `_build_clone_url` is gone (`hasattr` is false).

---

## 4. Shared device failure helpers (D1)

New file `backend/workflow_steps/common/device_step_results.py`.

Code before (`workflow_steps/get_device_configs/executor.py` lines 71–91; the same function is in `upload_config`, `deploy_rendered_template`, `add_to_nautobot`, `get_nautobot_attributes`):

```python
def _fail_device(*, device, device_id, node_id, code, message):
    err = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    failed = device.model_copy(update={
        "status": DeviceStatus.FAILED,
        "errors": [*device.errors, err],
    })
    return device_id, failed, False
```

Code before (`_build_outcomes`, same file, lines 236–254; the same function is in the eight executors listed in the review):

```python
def _build_outcomes(context, success_devices, failed_devices) -> list[StepOutcome]:
    outcomes = [StepOutcome(name="success", context=context.model_copy(update={"devices": success_devices}))]
    if failed_devices:
        outcomes.append(StepOutcome(name="failure", context=context.model_copy(update={"devices": failed_devices})))
    return outcomes
```

Code after, in the new module:

```python
def fail_device(*, step_id: str, device: DeviceContext, device_id: str, node_id: str, code: str, message: str):
    err = DeviceError(node_id=node_id, step_id=step_id, code=code, message=message)
    failed = device.model_copy(update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]})
    return device_id, failed, False


def build_success_failure_outcomes(context, success_devices, failed_devices, *, failure_name: str = "failure"):
    outcomes = [StepOutcome(name="success", context=context.model_copy(update={"devices": success_devices}))]
    if failed_devices:
        outcomes.append(StepOutcome(
            name=failure_name,
            context=context.model_copy(update={"devices": failed_devices}),
        ))
    return outcomes
```

Code after, in each executor. Do this in all eight `_build_outcomes` files and all five `_fail_device` files. `update_config_context` passes `failure_name` only if its current literal is not `"failure"`; otherwise omit it.

```python
def _fail_device(*, device, device_id, node_id, code, message):
    return fail_device(step_id=_STEP_ID, device=device, device_id=device_id, node_id=node_id, code=code, message=message)

def _build_outcomes(context, success_devices, failed_devices):
    return build_success_failure_outcomes(context, success_devices, failed_devices)
```

If one of the eight copies uses a failure outcome name other than `"failure"`, pass that string and do not change it. Do not touch the pairs in D8.

New test `backend/tests/unit/test_device_step_results.py`:

* `fail_device` sets `DeviceStatus.FAILED`, appends one `DeviceError` with the given `step_id`, and returns `(device_id, device, False)`.
* `build_success_failure_outcomes` returns one outcome named `success` when there are no failures, and a second named `failure` (or the override) when there are.

Existing executor tests stay as they are. They cover the wrappers.

---

## 5. One commit reader; services do not raise HTTP (G3, P4)

### 5.1 Commits

Code before (`GitVersionControlService.get_commits`, `version_control_service.py` lines 28–62): checks the branch, then either returns its own cache entry or walks `repo.iter_commits` into a hand-built dict.

Code after:

```python
def get_commits(self, repo_id: int, branch_name: str, cache_service=None) -> list[dict]:
    repo = get_git_repo_by_id(repo_id)
    if branch_name not in [ref.name for ref in repo.refs]:
        raise ValueError(f"Branch '{branch_name}' not found")
    if cache_service is None:
        raise RuntimeError("get_commits requires the git cache service")
    return cache_service.get_commits(repo_id, repo.working_dir, branch_name)
```

`GitCacheService.get_commits` already returns the `commit_to_dict` shape (`hash`, `short_hash`, `message`, `author`, `date`, `files_changed`). Delete the hand-built dict and the `repo:{id}:commits:{branch}` cache in the version-control service. The subprocess fallback stays inside `GitCacheService._fetch_commits_subprocess` and must call the same keys as `commit_to_dict` (it already does, with `files_changed: 0`). Do not add a third shape.

`routers/git/version_control.py` already passes `cache_service`. No router change.

`tests/unit/test_git_version_control_service.py`: the test that expects `[{"hash": "cached"}]` from the version-control cache key must expect that list from `cache_service.get_commits` instead. The missing-branch test stays.

### 5.2 File history

Move the walk that is today `GitFileService.get_file_history` (from line 428: `_resolve_commits_for_file`, `_change_type_for_file_at_commit`, `_history_entry_from_commit`) into `GitCacheService.get_file_history`. The cache method's return value becomes the dict the file service returns today. Cache key: the key `GitCacheService` already builds (`file_history`, branch, path, optional `from_commit`). Delete the file service's own key helper if it differs; the cache service key wins (D5).

`GitFileService.get_file_history` after:

```python
def get_file_history(self, repo_id, file_path, from_commit=None, cache_service=None, cache_enabled=True, cache_ttl=600):
    if cache_service is None:
        raise RuntimeError("get_file_history requires the git cache service")
    return cache_service.get_file_history(
        repo_id, str(get_repo_path_for(repo_id)), file_path,
        from_commit=from_commit, enabled=cache_enabled, ttl=cache_ttl,
    )
```

Use the existing repository lookup (`get_git_repo_by_id`) to obtain the path. Do not open a second `Repo` in the file service for this method.

On `InvalidGitRepositoryError` or `GitCommandError`, the cache service raises `NotFoundError("Git repository or commit not found")`. It does not call `raise_internal_server_error`.

### 5.3 HTTP mapping moves to the routers (P4)

Code before: `GitFileService` and `GitDebugService` call `raise_internal_server_error`.

Code after, in both services: delete that import. Unexpected failures raise `RuntimeError` with the same message string the helper logged (the message text stays; the HTTP status does not get decided here). `NotFoundError` stays `NotFoundError`.

Code after, in `routers/git/files.py` and `routers/git/debug.py`, around each service call:

```python
try:
    return service.get_file_history(...)
except NotFoundError as exc:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
except RuntimeError as exc:
    raise_internal_server_error(logger, str(exc), exc)
```

Apply that to every endpoint in those two routers. Do not add it to routers that already map `NotFoundError`.

### 5.4 Tests

* `tests/unit/test_git_cache_service.py` — `get_file_history` returns the dict with `total_commits` and `commits`.
* `tests/unit/test_git_file_service.py` — file service test patches the cache service and asserts it does not call `Repo` for history.
* `tests/unit/test_git_version_control_service.py` — as in §5.1.

Done when `rg "raise_internal_server_error" backend/services/git` prints nothing.

---

## 6. Narrow the broad handlers in the nine listed files (P1)

Do not edit handlers outside this list:

| File | Replace |
|---|---|
| `services/git/service.py` | Already done in phase 1 if `except Exception` is gone. If any remain, catch `GitCommandError` and `UnsafeURLError` only. |
| `services/git/debug_service.py` | `except Exception` around a git call becomes `except (GitCommandError, OSError)`. `_restore_origin_url` is gone (phase 1). |
| `services/git/file_service.py` | `except Exception` that called `raise_internal_server_error` becomes `except (InvalidGitRepositoryError, GitCommandError, OSError)` raising `RuntimeError`. |
| `services/git/operations.py` | `except Exception` in status filling stays a log-and-continue only for `GitCommandError`, `InvalidGitRepositoryError`, and `OSError`. Delete any `except Exception` that maps a sync onto `SyncResult`; phase 2 removed that path. |
| `services/cache/redis_cache_service.py` | `except Exception` becomes `except (RedisError, OSError, TypeError, ValueError)`. Import `RedisError` from `redis`. A programming error must propagate. |
| `services/network/netmiko/connection.py` | `except Exception` around a Netmiko call becomes `except (NetmikoTimeoutException, NetmikoAuthenticationException, ConnectionException, OSError)`. Read the names from the netmiko imports already in the file; do not add a new library. |
| `services/sources/nautobot/persistence_service.py` | `except Exception` that maps to a failed inventory operation becomes `except (SQLAlchemyError, ValueError)`. |
| `routers/sources/nautobot/ops.py` | `except Exception` becomes the `raise_internal_server_error` path only after `except HTTPException: raise`. Specific domain errors already mapped to 400/404 stay mapped. The bare `except Exception` that is the last branch of a router handler may stay as `raise_internal_server_error` — that is the HTTP boundary. Count it as done when it is the last clause and every earlier clause lists a concrete type. |
| `routers/sources/ise/ops.py` | Same rule as the Nautobot ops router. |

Code before (the pattern in `GitService.pull`):

```python
except Exception as e:
    return PullResult(success=False, message=f"Unexpected error: {str(e)}", ...)
```

Code after: that clause is deleted. `GitCommandError` and `UnsafeURLError` are the only failures turned into a result. Anything else propagates.

Do not "fix" handlers by catching `Exception` and re-raising. Delete the clause or name the types.

`tests/unit/test_redis_cache_service.py` must still pass. Add one test: a `RuntimeError` raised by the Redis client is not swallowed. If the current test suite patches Redis with a generic `Exception`, change the patch to `RedisError`.

---

## 7. Split the seven long functions (L1)

Rule for every function in this phase: the orchestrator is the only new control flow, and it is a straight sequence of calls. Each helper receives the values the original function already computed and returns what the next block already used. No helper calls another helper. No message text changes.

| Function | File | After |
|---|---|---|
| `_process_one_device` (line 315, 257 lines) | `workflow_steps/configure_replace_config/executor.py` | `_resolve_replace_target`, `_run_replace`, `_record_replace`. Orchestrator calls them in that order. |
| `execute` (line 126, 200 lines) | `workflow_steps/undefined_and_unused/executor.py` | `_load_candidates`, `_classify`, `_outcomes`. |
| `_compare_one_device` (line 279, 181 lines) | `workflow_steps/compare_pyats_snapshot/executor.py` | `_load_snapshot_pair`, `_diff_snapshot`, `_snapshot_device_result`. |
| `run_git_workflow_step` (line 181, 158 lines) | `workflow_steps/common/git_workflow_step.py` | `_prepare_git_step`, `_run_locked_git_operation`, `_git_step_outcome` in the same file. |
| `execute` (line 291, 154 lines) | `workflow_steps/open_change_request/executor.py` | `_open_change_request_record`, `_stage_change_request_branch`, `_open_change_request_outcome`. |
| `execute` (line 428, 153 lines) | `workflow_steps/config_to_attributes/executor.py` | `_parse_config_to_attributes`, `_apply_config_to_attributes`, `_config_to_attributes_outcome`. |
| `execute` (line 275, 153 lines) | `workflow_steps/batfish_validate_facts/executor.py` | `_load_batfish_facts`, `_validate_batfish_facts`, `_batfish_facts_outcome`. |

Code before: one function whose body is the current statements from the line in the table through its last line.

Code after, shape only (the bodies are those statements, cut in order):

```python
def execute(...):
    loaded = _load_candidates(...)          # first third of the old body
    classified = _classify(loaded, ...)     # middle third
    return _outcomes(classified, ...)       # last third
```

The cut is at the existing blank-line / comment boundaries already in the function. If a function has no blank-line thirds, cut before the first device loop and after the loop, and leave the loop body in the middle helper. Do not extract code from inside the loop.

Each orchestrator must be under 40 lines. Each helper must be under 120 lines. If a helper is still over 120, split that helper once more on the same rule. Stop there.

Existing unit tests for these steps are the spec. Do not add tests that assert helper call order. Run the unit modules whose names match the step (`test_git_workflow_steps.py`, and the executor tests that already import these modules). A missing test module is not a reason to write one in this phase.

---

## 8. One custom-field fetch, shared source error mapping (D2, D4)

### 8.1 Custom fields

Code before: `NautobotMetadataService.get_device_custom_fields` and `NautobotSourceMetadataService.get_custom_fields` both request `extras/custom-fields/?content_types=dcim.device`.

Code after. `NautobotMetadataService.get_device_custom_fields` is unchanged (it returns `result.get("results", [])`).

`NautobotSourceMetadataService.get_custom_fields` drops its `rest_request` call:

```python
async def get_custom_fields(self) -> list[dict]:
    if self._custom_fields_cache is not None:
        return self._custom_fields_cache
    raw = await NautobotMetadataService(self._nautobot, self._credentials).get_device_custom_fields()
    transformed = []
    for field in raw:
        # the existing label / key shaping loop, unchanged
        ...
    self._custom_fields_cache = transformed
    return transformed
```

The shaping loop is the loop already in `get_custom_fields` (from the `for field in response["results"]` body). Point it at `raw` instead of `response["results"]`. Keep the empty-list return when the fetch returns an empty list. Delete the `"results" not in response` branch; an empty list is that case.

`tests/unit/test_sources_nautobot_metadata_service.py` and `tests/unit/test_nautobot_metadata_creation.py` must pass. The source-service test should patch `NautobotMetadataService.get_device_custom_fields`, not `rest_request`, if it currently patches `rest_request` on the source service's client. Patching the client is still valid if the metadata service uses that same client; prefer patching `get_device_custom_fields` so the test fails when a second request is added.

### 8.2 Shared CRUD error mapping

New function in `backend/routers/source_http.py`.

Code before (the ladder inside `build_source_crud_router`, `source_crud_factory.py` lines 87–96, repeated for get, update, and delete, and again by hand in `routers/sources/nautobot/crud.py`):

```python
try:
    return response_model(**service.create_source(**create_kwargs(request)))
except conflict_error as exc:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
except bad_request as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
except HTTPException:
    raise
except Exception as exc:
    raise_internal_server_error(logger, f"Failed to create {display_name} source: ", exc)
```

Code after:

```python
def map_source_crud_error(exc: Exception, *, not_found: tuple[type[Exception], ...],
                          conflict: tuple[type[Exception], ...],
                          bad_request: tuple[type[Exception], ...],
                          logger, message: str) -> None:
    if isinstance(exc, not_found):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, conflict):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, bad_request):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if isinstance(exc, HTTPException):
        raise exc
    raise_internal_server_error(logger, message, exc)
```

`build_source_crud_router` handlers become:

```python
try:
    return response_model(**service.create_source(**create_kwargs(request)))
except Exception as exc:
    map_source_crud_error(exc, not_found=(), conflict=(conflict_error,),
                          bad_request=bad_request, logger=logger,
                          message=f"Failed to create {display_name} source: ")
```

Use the same call for get (`not_found=(not_found_error,)`), update, and delete. This `except Exception` is the HTTP boundary from phase 6; it is allowed because `map_source_crud_error` re-raises unknown exceptions as a 500 only through `raise_internal_server_error`, and known types become 404/409/400.

`routers/sources/nautobot/crud.py` keeps its own routes (import and export stay). Replace each hand-written except ladder in that file with `map_source_crud_error`, passing the exception types that ladder already names. Do not generate Nautobot routes from `build_source_crud_router`.

### 8.3 Test-connection credential resolvers

Code before (`routers/sources/pyats/ops.py` lines 42–58, and the same shape in `catalyst_center/crud.py`, `ise/crud.py`, `mattermost/ops.py`):

```python
def _resolve_credentials(request, config):
    try:
        if request.source_id:
            return config.resolve_credentials(request.source_id)
        return config.resolve_inline_credentials(...)
    except PyATSSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PyATSValidationError, UnsafeURLError, SourceCredentialError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Code after. The `if source_id` body stays in each file (the inline kwargs differ). Only the except clauses change:

```python
try:
    ...
except Exception as exc:
    map_source_crud_error(
        exc,
        not_found=(PyATSSourceNotFoundError,),
        conflict=(),
        bad_request=(PyATSValidationError, UnsafeURLError, SourceCredentialError),
        logger=logger,
        message="Failed to resolve pyATS credentials: ",
    )
```

Substitute the exception types already imported in each of the four files. Do not invent a shared `resolve_inline_credentials` signature.

`tests/unit/test_source_crud_factory.py` must pass. Add two cases to it: a conflict maps to 409, an unknown `RuntimeError` still becomes the internal-server-error path (assert the helper calls `raise_internal_server_error`, or assert a 500 if the test uses the router).

---

## 9. Long files, without deleting the old managers (L2, D3)

### 9.1 Move blocks out of the long files

Same move-don't-rewrite rule as phase 7. New modules export the moved functions. The original module imports them back so existing `from <old module> import <name>` keeps working. Do not change the function bodies.

| Source | New module | What moves |
|---|---|---|
| `workflow_steps/add_to_ise/executor.py` | `workflow_steps/add_to_ise/create_device.py` | `_create_one_device`, `_resolve_device_fields` |
| `services/nautobot/devices/update.py` | `services/nautobot/devices/update_fields.py` | `_prepare_update_field` and the field-prep helpers it calls |
| `services/nautobot/devices/update.py` | `services/nautobot/devices/update_primary_ip.py` | the primary-IP block inside `update_device` |
| `services/execution/step_runner/runner.py` | `services/execution/step_runner/persist_node.py` | `_execute_and_persist_node` |
| `services/workflow/workflow_validation_service.py` | `services/workflow/validation_tier3.py` | `_tier3_capability_flow` |

`update_device` after is the current function with the field-prep and primary-IP sections replaced by a call to the moved functions. Interface updates stay in `update.py` (they already delegate to `InterfaceManagerService`).

Skip `debug_service.py`, `file_service.py`, `configure_replace_config/executor.py`, and `netmiko/connection.py`. Phases 1, 5, 6, and 7 already change those. Skip `credentials_service.py` and `query_service.py` (D11).

### 9.2 Old interface stack

Code after, docstring on `DeviceCommonService.interface_manager` and `device_manager` in `services/nautobot/devices/common.py`. No other edit in that file.

```python
@property
def interface_manager(self) -> InterfaceManager:
    """Legacy. Device create/update uses InterfaceManagerService.

    Do not add callers. Delete this property when the last caller is gone.
    """
```

Write the same sentence on `device_manager`, naming `DeviceUpdateService` / `DeviceCreationService` as the path for device writes. Do not remove the properties. Do not change `services/nautobot/managers/__init__.py` exports.

---

## 10. Verification

From `backend/`, in order:

```bash
python -m pytest \
  tests/unit/test_git_service_engine.py \
  tests/unit/test_git_sync.py \
  tests/unit/test_git_operations_service.py \
  tests/unit/test_git_debug_service.py \
  tests/unit/test_git_connection_service.py \
  tests/unit/test_git_workflow_steps.py \
  tests/unit/test_git_cache_service.py \
  tests/unit/test_git_file_service.py \
  tests/unit/test_git_version_control_service.py \
  tests/unit/test_device_step_results.py \
  tests/unit/test_redis_cache_service.py \
  tests/unit/test_source_crud_factory.py \
  tests/unit/test_sources_nautobot_metadata_service.py \
  tests/unit/test_nautobot_metadata_creation.py \
  -q
```

Then the full unit suite:

```bash
python -m pytest tests/unit -q
```

Static checks, all of which must be true:

| Check | Expected |
|---|---|
| `rg "origin.set_url" backend/services/git` | only `_run_on_origin` and `_restore_origin_url` |
| `rg "def _build_clone_url" backend` | no matches |
| `rg "raise_internal_server_error" backend/services/git` | no matches |
| `rg "repo:\{.*\}:commits:" backend/services/git` | no matches (the version-control cache key is gone) |
| `rg "except Exception" backend/services/git/service.py` | no matches |
| `def clone` return annotation | `CloneResult` |
| `clone_or_pull` and `sync_repository` | each calls `ensure_working_tree` and contains no `origin.pull` / `Repo.clone_from` |

Out of scope, even if a test failure tempts a drive-by fix: merging `services/nautobot` with `services/sources/nautobot`, deleting `InterfaceManager`, splitting `credentials_service.py` or `query_service.py`, and editing `except Exception` outside the nine files in phase 6.
