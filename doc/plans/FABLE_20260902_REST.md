# Plan: FABLE_REST — §4.2 async hardening + CI workflow

Source: `doc/analysis/FABLE_BACKEND_20260902.md` §4.2 and §3 ("Security scanning" /
"No static type checker" rows), consolidated in §7 "First hardening pass" items 7 and 9.

Scope: two independent workstreams, either order.

| Part | Item | §7 ref | Clarity | Decision |
|---|---|---|---|---|
| A | Convert sync-only `async def` handlers to `def` | 7 | Clear | D1 |
| A | Cache the derived Fernet key once per process | 7 | **Already done** (S12 / `e1382fc`) — verify only | D2 |
| A | Thread-offload the residual blocking git / DNS in genuinely-async paths | 7 | Clear | D3 |
| B | `bandit` + ruff `S`/`ASYNC` rules | 9 | Clear | D4 |
| B | `pip-audit` dependency scan | 9 | Clear | D5 |
| B | `pyright` static type check | 9 | Needs a strictness/blocking decision | D6 |
| B | GitHub Actions workflow: guards + tests + all of the above | 9 | Clear | D7 |

Every item ends with the tests / checks that must pass before it is considered done.

---

## Implementation status — 2026-09-03 (branch `fix/fable-rest-async-hardening`)

**Done.** 2190 unit tests pass, coverage 82.39 % (ratchet 81 %), `ruff check .` clean,
four guard scripts pass.

Deviations from the plan as written:

- **No `ruff format --check` in CI.** The tree is not `ruff format`-clean (117 files
  would reflow, all pre-existing). CI enforces `ruff check` (lint) only; a repo-wide
  reformat is out of scope.
- **Standalone `bandit` dropped; ruff `S` is the bandit gate.** `bandit` ≤ 1.9.4
  crashes on the Python 3.14 AST (`'Constant' object has no attribute 's'`) and uses a
  separate `# nosec` suppression syntax. ruff's `S` (flake8-bandit) reimplements the
  same checks, runs on 3.14, and shares `# noqa`. `[tool.bandit]` and the `bandit`
  pin were removed.
- **`pyright` job is advisory (`continue-on-error: true`).** Basic mode surfaces ~149
  pre-existing findings (mostly `str | None` → `str` gaps). Config is committed; the
  job blocks nothing until the backlog clears. Tracked as a `TODO(FABLE_REST)` in the
  workflow.
- **`gitpython` bumped `3.1.57` → `3.1.59`** (requirements.txt) — pip-audit flagged
  PYSEC-2026-3783..3788 + 4 GHSAs, all fixed in 3.1.58/59. Git tests still pass.
- **pip-audit ignores `PYSEC-2026-2858`** (paramiko SHA-1 RSA keys, transitive via
  netmiko, no fixed release yet) via `--ignore-vuln` in the workflow, with a comment.
- **Fernet cache (D2):** confirmed already shipped in S12; added one regression test
  (`test_crypto.py::test_pbkdf2_stretches_once_across_many_service_constructions`).
- **D3 scope shrank:** `_base_url` in `services/pyats/client.py` and
  `services/mattermost/client.py` was a *sync* helper called from many `async def`
  methods, so it was made `async` (not left alone) and its call sites `await`ed.
  `nautobot`/`ise` clients call the validator directly in `async def` → direct swap to
  `validate_outbound_http_url_async`.

Files touched: `core/safe_urls.py`, `core/crypto.py` (test only), 29 router modules
(`async def` → `def`) + `routers/certificates.py`, `routers/hatchet_settings.py`
(per-handler), `services/{nautobot,ise,pyats,mattermost}/client.py`,
`workflow_steps/{add_to_ise,get_from_list,update_ise_tacacs_key}/executor.py` +
`hatchet/workflows/workflow_run.py` (`# noqa: S101`), `backend/pyproject.toml`,
`backend/requirements.txt`, `backend/requirements-dev.txt`,
`.github/workflows/backend-ci.yml`, 4 test files, `CLAUDE.md`,
`doc/analysis/FABLE_BACKEND_20260902.md`.

---

## 0. Decisions (resolved)

### D1 — whole-file `def` conversion for routers with zero `await`; per-handler for the rest

FastAPI runs a `def` route handler in the threadpool and an `async def` handler on the
event loop. Nearly every handler in this codebase calls **synchronous** SQLAlchemy,
GitPython, `subprocess`, Fernet, and `socket.getaddrinfo`, so today one slow call
stalls every other in-flight request (analysis §4.2).

Only **6** router modules contain an `await` at all:
`routers/oidc.py`, `routers/netmiko.py`, `routers/certificates.py`,
`routers/hatchet_settings.py`, `routers/nautobot/custom_fields.py`,
`routers/git/devices.py`, plus the four `routers/sources/*/ops.py` +
`routers/sources/ise/crud.py` external-API modules.

**Pass 1 (mechanical, low risk):** in every router module that contains **no** `await`,
change each handler `async def` → `def`. Dependencies stay as they are (`get_db` is a
sync generator, `get_current_user` / `require_permission` are sync `def` — all work
unchanged under a threadpool handler). This is the bulk of the ~200 handlers and
covers the expensive git endpoints (`routers/git/operations.py`,
`routers/git/repositories.py::test-connection`), which is what makes D3 small.

**Pass 2 (per-handler, in the 6 mixed modules):** convert only the handlers that
contain no `await` and call no async helper; leave the genuinely-async ones alone.

Not in scope: async SQLAlchemy / `asyncpg` (analysis §4.2 option 4 — a separate, larger
migration).

### D2 — Fernet key caching is already implemented; this plan only adds a regression test

`core/crypto.py::_build_key` is already `@functools.lru_cache(maxsize=4)` and
`KDF_ITERATIONS` is already read from `Settings` (`settings.kdf_iterations`, floor
100 000). Shipped in `e1382fc` (finding S12). Nothing to build — add one test that
pins the behaviour so it cannot regress, and tick the box in the analysis.

### D3 — one async wrapper in `core/safe_urls.py`, used only by the four source API clients

After D1 Pass 1, the only place `socket.getaddrinfo` still runs on the event loop is
inside the **async** methods of the external-API clients
(`services/{nautobot,ise,pyats,mattermost}/client.py`), which call
`validate_outbound_http_url(..., resolve_dns=True)` directly before an `httpx` await.

- `services/git/service.py` needs **no** change: it is fully synchronous and is only
  reached from threadpool handlers (post-D1) or Hatchet worker threads.
- `services/git/devices.py` router already wraps `clone_or_pull` in
  `run_in_executor` — leave it.
- `services/*/source_config_service.py` and `services/settings/settings_service.py`
  call the validator from **sync** methods invoked by threadpool handlers — leave them.

Add:

```python
async def validate_outbound_http_url_async(url: str) -> str:
    return await asyncio.to_thread(validate_outbound_http_url, url, resolve_dns=True)
```

and switch **only the call sites that sit inside an `async def`** in the four
`client.py` files to `await validate_outbound_http_url_async(...)`.

### D4 — add `S` and `ASYNC` to ruff; keep `bandit` as a second, report-only tool

`ASYNC` (flake8-async) directly enforces §4.2 — it flags blocking calls inside
`async def`. `S` (flake8-bandit) overlaps `bandit` but runs in the same sub-second
ruff pass. Keep `bandit -r` too (analysis and `rules/python/security.md` both name it)
but run it `--severity-level medium --confidence-level medium` so it stays signal.

`S` will fire widely on first enable (subprocess `S603/S607`, `assert` in tests
`S101`, `try/except/pass` `S110`). Triage in this order: (1) `per-file-ignores` for
`tests/**` → `S101`; (2) fix real findings; (3) targeted `# noqa: Sxxx  # <reason>`
for the vetted-safe subprocess / `verify=False` sites already documented in
`doc/SECURITY-NOTES.md`. CI turns blocking only once `ruff check .` is clean (D7).

### D5 — `pip-audit` against the pinned `requirements*.txt`, blocking

Deps are fully pinned (`==`). Run `pip-audit -r backend/requirements.txt -r
backend/requirements-dev.txt --strict`. A finding with no fix version gets an
explicit `--ignore-vuln GHSA-xxxx` line in the workflow with a comment, so the job
stays green and the exception is visible in review.

### D6 — `pyright` in `basic` mode, blocking, after a clean-up pass

Analysis: "96 % annotation coverage … ready for `pyright --level basic`". Configure
`[tool.pyright]` in `backend/pyproject.toml` with `typeCheckingMode = "basic"` and
`pythonVersion = "3.14"`. Before flipping CI to blocking, run it locally and fix or
`# pyright: ignore[...]` the residue. If the residue is large, land the workflow with
`continue-on-error: true` on the pyright step **only**, file a follow-up, and remove
the flag when clean — do not leave it indefinitely.

### D7 — one workflow, `.github/workflows/backend-ci.yml`, Python 3.14, no service containers

The unit suite uses in-memory SQLite + `fakeredis`, so no Postgres/Redis services are
needed. Jobs: `lint` (ruff + bandit), `types` (pyright), `audit` (pip-audit),
`guards` (the four `scripts/check_*.py`), `test` (`pytest`, enforces
`--cov-fail-under=81`). Triggers: `pull_request` + `push` to `main`. Path filter so
frontend-only PRs skip it.

---

## Part A — §4.2 async hardening

### A1. Convert sync-only handlers to `def`

#### A1.1 Problem

200 of 238 route handlers are `async def` but do only synchronous work; each blocks the
event loop for the duration of its DB / git / crypto / DNS call.

#### A1.2 Pass 1 — whole-file conversion (routers with no `await`)

Representative example — `routers/general_settings.py`.

before:

```python
@router.get(
    "/settings",
    response_model=GeneralSettingsResponse,
    dependencies=[Depends(require_permission("general_settings", "read"))],
)
async def get_general_settings(
    service: GeneralSettingsService = Depends(_service),
) -> GeneralSettingsResponse:
    return service.get_settings()


@router.put(
    "/settings",
    response_model=GeneralSettingsResponse,
    dependencies=[Depends(require_permission("general_settings", "write"))],
)
async def update_general_settings(
    body: GeneralSettings,
    service: GeneralSettingsService = Depends(_service),
) -> GeneralSettingsResponse:
    return service.update_settings(body)
```

after:

```python
@router.get(
    "/settings",
    response_model=GeneralSettingsResponse,
    dependencies=[Depends(require_permission("general_settings", "read"))],
)
def get_general_settings(
    service: GeneralSettingsService = Depends(_service),
) -> GeneralSettingsResponse:
    return service.get_settings()


@router.put(
    "/settings",
    response_model=GeneralSettingsResponse,
    dependencies=[Depends(require_permission("general_settings", "write"))],
)
def update_general_settings(
    body: GeneralSettings,
    service: GeneralSettingsService = Depends(_service),
) -> GeneralSettingsResponse:
    return service.update_settings(body)
```

Apply the identical change (`async def <handler>` → `def <handler>`, nothing else) to
every handler in each of these modules (no `await` anywhere in the file):

```
routers/auth.py                       routers/settings.py
routers/cache_settings.py             routers/system.py
routers/credentials.py                routers/templates.py
routers/dashboard.py                  routers/users.py
routers/general_settings.py           routers/workflows.py
routers/logging_settings.py           routers/workflow_runs.py
routers/workflow_background_tier.py   routers/workflow_schedules.py
routers/workflow_steps.py             routers/workflow_update_attribute.py
routers/workflow_update_content.py
routers/git/operations.py             routers/git/files.py
routers/git/repositories.py           routers/git/version_control.py
routers/git/main.py                   routers/git/debug.py
routers/rbac/*.py
routers/nautobot/*.py   (except custom_fields.py)
routers/sources/nautobot/crud.py      routers/sources/ise/*.py (except crud.py)
routers/sources/pyats/crud.py         routers/sources/mattermost/crud.py
```

> Confirm the list at implementation time with:
> `grep -rL $'\tawait \|await ' routers` is unreliable — instead, for each router file
> run `grep -L "await " <file>` and only convert files that print. Re-run
> `python scripts/check_asyncio_run.py` after (unaffected — it bans `asyncio.run(`, not
> `def`).

Git blocking (`/git/{repo_id}/sync`, `/remove-and-sync`) is resolved here, because
`routers/git/operations.py` has no `await`:

before (`routers/git/operations.py`):

```python
@router.post("/sync", dependencies=[Depends(require_permission("git.operations", "execute"))])
async def sync_repository(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    git_operations_service=Depends(get_git_operations_service),
    git_cache_service=Depends(get_git_cache_service),
):
    try:
        return git_operations_service.sync_and_record(repo_id, git_cache_service)
    ...
```

after:

```python
@router.post("/sync", dependencies=[Depends(require_permission("git.operations", "execute"))])
def sync_repository(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    git_operations_service=Depends(get_git_operations_service),
    git_cache_service=Depends(get_git_cache_service),
):
    try:
        return git_operations_service.sync_and_record(repo_id, git_cache_service)
    ...
```

#### A1.3 Pass 2 — per-handler in the mixed modules

In `routers/certificates.py`, `routers/hatchet_settings.py`,
`routers/nautobot/custom_fields.py`: convert only the handlers whose body has no
`await` and calls no coroutine. Leave `async def` on every handler in
`routers/oidc.py`, `routers/netmiko.py`, `routers/git/devices.py`, and the four
`routers/sources/*/ops.py` modules (all genuinely async).

Example — `routers/hatchet_settings.py` (2 handlers, 1 `await`):

before:

```python
async def get_hatchet_settings(...):
    return service.get_settings()          # sync

async def test_hatchet_connection(...):
    return await service.test_connection() # async
```

after:

```python
def get_hatchet_settings(...):
    return service.get_settings()

async def test_hatchet_connection(...):
    return await service.test_connection()
```

#### A1.4 Tests / checks

- [ ] `python scripts/check_asyncio_run.py` → OK
- [ ] `python -m pytest` → 2 011+ pass, coverage ≥ 81 %
- [ ] `grep -rn "async def " routers/ | wc -l` drops from ~200 to roughly the count of
      `await`-using handlers (~25).
- [ ] Manual: `GET /general/settings`, `POST /git/{id}/sync`, `GET /workflows` still
      return the same payloads (existing router tests cover this — they call through
      `TestClient`, which handles `def` and `async def` identically).
- [ ] Add one test asserting a representative converted route is registered as a
      non-coroutine: `assert not asyncio.iscoroutinefunction(route.endpoint)` for
      `get_general_settings` in `tests/unit/routers/test_general_settings.py`.

### A2. Fernet key cache — verification only (already shipped in `e1382fc`)

#### A2.1 Current state (`core/crypto.py`, unchanged by this plan)

```python
@functools.lru_cache(maxsize=4)
def _build_key(secret: str, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_KDF_SALT, iterations=iterations)
    return base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))
```

#### A2.2 Add a regression test

new — `tests/unit/core/test_crypto_key_cache.py`:

```python
from __future__ import annotations

from unittest.mock import patch

from core import crypto


def test_build_key_is_cached_per_secret_iterations():
    crypto._build_key.cache_clear()
    with patch(
        "core.crypto.PBKDF2HMAC", wraps=crypto.PBKDF2HMAC
    ) as spy:
        crypto.EncryptionService(secret_key="x" * 40)
        crypto.EncryptionService(secret_key="x" * 40)
        crypto.EncryptionService(secret_key="x" * 40)
    assert spy.call_count == 1  # PBKDF2 stretched once, not per construction


def test_build_key_recomputes_for_a_different_secret():
    crypto._build_key.cache_clear()
    with patch("core.crypto.PBKDF2HMAC", wraps=crypto.PBKDF2HMAC) as spy:
        crypto.EncryptionService(secret_key="a" * 40)
        crypto.EncryptionService(secret_key="b" * 40)
    assert spy.call_count == 2
```

#### A2.3 Checks

- [ ] New test passes.
- [ ] Update `doc/analysis/FABLE_BACKEND_20260902.md` §7 item 7: strike "cache the
      Fernet key" (done in S12) and note item 7 now = handler conversion + DNS offload.

### A3. Thread-offload the residual blocking DNS in async client paths

#### A3.1 The wrapper — `core/safe_urls.py`

before (top of file):

```python
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse
```

after:

```python
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from urllib.parse import urlparse
```

before (after `validate_outbound_http_url`):

```python
    if resolve_dns:
        _assert_resolved_hosts_allowed(host)

    return raw.rstrip("/")
```

after:

```python
    if resolve_dns:
        _assert_resolved_hosts_allowed(host)

    return raw.rstrip("/")


async def validate_outbound_http_url_async(url: str) -> str:
    """``validate_outbound_http_url(url, resolve_dns=True)`` off the event loop.

    ``_assert_resolved_hosts_allowed`` calls the blocking ``socket.getaddrinfo``.
    Callers that run inside ``async def`` (the external-API clients) must not stall
    the loop on DNS, so the whole validation is pushed to a worker thread.
    """
    return await asyncio.to_thread(validate_outbound_http_url, url, resolve_dns=True)
```

#### A3.2 Switch the four async client call sites

`services/nautobot/client.py` — both occurrences (lines ~79, ~129) are inside `async`
methods.

before:

```python
            base = validate_outbound_http_url(credentials.url, resolve_dns=True)
```

after:

```python
            base = await validate_outbound_http_url_async(credentials.url)
```

and update the import:

before:

```python
from core.safe_urls import UnsafeURLError, validate_outbound_http_url
```

after:

```python
from core.safe_urls import UnsafeURLError, validate_outbound_http_url_async
```

Apply the same swap in:

| File | Lines (approx) | Note |
|---|---|---|
| `services/nautobot/client.py` | 79, 129 | both in `async def` |
| `services/ise/client.py` | 66 | confirm enclosing method is `async def`; if sync, leave |
| `services/pyats/client.py` | 202 | `_resolve_base_url` — confirm `async`; if sync, leave |
| `services/mattermost/client.py` | 189 | confirm `async`; if sync, leave |

> If a `client.py` call site turns out to be in a **sync** helper reached only from a
> threadpool handler, leave it as `validate_outbound_http_url(...)` — wrapping a sync
> function in `to_thread` from sync code is impossible and unnecessary. Do **not**
> touch `services/*/source_config_service.py`, `services/settings/settings_service.py`,
> or `services/git/service.py` (all sync, all threadpool-reached after A1).

#### A3.3 Tests / checks

- [ ] `tests/unit/core/test_safe_urls.py`: add a case that
      `validate_outbound_http_url_async("http://10.0.0.1")` returns the normalized URL
      and that `...("http://169.254.169.254")` raises `UnsafeURLError` (same asserts as
      the sync tests, `await`ed).
- [ ] Existing nautobot/ise/pyats/mattermost client tests still pass (they mock
      `httpx`; the validator is real). If a test previously patched
      `validate_outbound_http_url`, repoint the patch to `validate_outbound_http_url_async`.
- [ ] `ruff check .` with `ASYNC` enabled (Part B) reports no `ASYNC2xx` blocking-call
      findings in `services/*/client.py`.

---

## Part B — CI workflow

### B1. Dev tooling — `backend/requirements-dev.txt`

before:

```
# Dev / test tooling (install into the project venv):
#   ../.venv/bin/pip install -r requirements-dev.txt
-r requirements.txt
pytest==9.1.1
pytest-cov==7.1.0
fakeredis==2.37.1
```

after:

```
# Dev / test tooling (install into the project venv):
#   ../.venv/bin/pip install -r requirements-dev.txt
-r requirements.txt
pytest==9.1.1
pytest-cov==7.1.0
fakeredis==2.37.1

# Static analysis / security (also run in .github/workflows/backend-ci.yml)
ruff==0.14.4
bandit==1.8.6
pip-audit==2.9.0
pyright==1.1.406
```

> Pin to the latest patch available at implementation time; the versions above are
> placeholders. `ruff` was previously invoked ad hoc — pinning it here makes local and
> CI runs identical.

### B2. Ruff config — `backend/pyproject.toml`

before:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
ignore = ["B008"]
```

after:

```toml
[tool.ruff]
line-length = 100
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "S", "ASYNC"]
ignore = [
    "B008",     # FastAPI Depends() in defaults is the framework idiom
    "S101",     # asserts: allowed in tests (see per-file-ignores) — keep flagged elsewhere
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S", "ASYNC"]          # test fixtures use asserts, tmp paths, sync sleeps
"scripts/**" = ["S603", "S607"]     # dev/CI helpers shell out to known binaries
"migrations/**" = ["S"]

[tool.ruff.lint.flake8-bandit]
# `requests`/`httpx` calls without an explicit timeout are caught by S113; keep on.
```

Triage steps before turning CI blocking (D4):

1. `cd backend && ruff check . --select S,ASYNC --statistics` — get the counts.
2. Fix `ASYNC` findings (they are §4.2 bugs — mostly resolved by Part A).
3. For each surviving `S` finding: real fix, or `# noqa: Sxxx  # <one-line reason>`
   cross-referencing `doc/SECURITY-NOTES.md` where the risk is already accepted
   (Netmiko host-key off, `verify_ssl=False`, git creds in argv).
4. `bump target-version` may surface new `UP` autofixes — run `ruff check . --fix` and
   review the diff.
5. Only when `ruff check .` exits 0 does B5's `lint` job lose `continue-on-error`.

### B3. Pyright config — `backend/pyproject.toml` (append)

new:

```toml
[tool.pyright]
include = ["core", "models", "repositories", "services", "routers", "hatchet", "workflow_steps", "main.py", "dependencies.py", "service_factory.py"]
exclude = ["**/__pycache__", ".venv", "tests", "scripts", "migrations"]
pythonVersion = "3.14"
typeCheckingMode = "basic"
reportMissingImports = true
reportMissingModuleSource = false
```

Pre-CI cleanup: `cd backend && pyright` locally; fix or `# pyright: ignore[rule]`
(with reason) the residue. If large, land B5 with `continue-on-error: true` on the
`types` job only + a follow-up issue; remove the flag once clean.

### B4. Bandit config — `backend/pyproject.toml` (append)

new:

```toml
[tool.bandit]
exclude_dirs = ["tests", "scripts", ".venv", "migrations"]
# S105-108 style: ruff's flake8-bandit is primary; this run is the medium/medium net.
```

### B5. Workflow — `.github/workflows/backend-ci.yml` (new file, repo root)

```yaml
name: backend-ci

on:
  push:
    branches: [main]
    paths: ["backend/**", ".github/workflows/backend-ci.yml"]
  pull_request:
    paths: ["backend/**", ".github/workflows/backend-ci.yml"]

defaults:
  run:
    working-directory: backend

concurrency:
  group: backend-ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - run: pip install -r requirements-dev.txt
      - name: ruff (E,F,I,UP,B,S,ASYNC)
        run: ruff check --output-format=github .
      - name: ruff format --check
        run: ruff format --check .
      - name: bandit
        run: bandit -c pyproject.toml -r . --severity-level medium --confidence-level medium

  types:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - run: pip install -r requirements-dev.txt
      - name: pyright
        run: pyright

  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - run: pip install pip-audit==2.9.0
      - name: pip-audit
        run: pip-audit --strict -r requirements.txt -r requirements-dev.txt
        # Add: --ignore-vuln GHSA-xxxx-xxxx-xxxx  # <reason, no fix released as of YYYY-MM-DD>

  guards:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - run: pip install -r requirements-dev.txt
      - run: python scripts/check_asyncio_run.py
      - run: python scripts/check_http_500_leaks.py
      - run: python scripts/check_router_repositories.py
      - run: python scripts/check_text_sql.py

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - run: pip install -r requirements-dev.txt
      - name: pytest (unit) + coverage ratchet
        run: python -m pytest
        # addopts in pyproject.toml already enforces --cov-fail-under=81
```

Notes:

- `working-directory: backend` matches how the guards and `pytest` resolve paths
  locally.
- No `services:` block — `tests/unit` uses in-memory SQLite + `fakeredis`. Add a
  `postgres` service + `manus_test` seeding **only** if `tests/integration` is ever
  wired into CI (out of scope; opt-in per `backend/tests/integration/README.md`).
- `setup-python` with `3.14`: if GitHub's runner image lags on 3.14, pin to
  `3.14.4` and add `allow-prereleases: true`, or switch to `actions/setup-python`
  with `uv`.
- Jobs run in parallel; a red `lint`/`types` does not mask a red `test`.
- Branch protection on `main`: require `lint`, `types`, `audit`, `guards`, `test`.

### B6. Tests / checks

- [ ] Workflow YAML validates: `actionlint .github/workflows/backend-ci.yml` (or push a
      draft PR and read the Actions tab).
- [ ] All five jobs green on a no-op PR.
- [ ] `ruff check .` exits 0 locally with the new `select` (D4 triage complete).
- [ ] `pyright` exits 0 locally, or `types` job carries a documented
      `continue-on-error` + follow-up issue link.
- [ ] `pip-audit --strict` exits 0, or every `--ignore-vuln` has an inline reason +
      date.
- [ ] `bandit -c pyproject.toml -r . --severity-level medium --confidence-level medium`
      exits 0.
- [ ] Removing `working-directory` breaks the guards (sanity: confirms path handling).
- [ ] Update `doc/analysis/FABLE_BACKEND_20260902.md` §3 rows "Security scanning" and
      "No static type checker" from ❌ to ✅ with the workflow path.
- [ ] Update `CLAUDE.md` "Development Workflow" to mention `ruff format --check`,
      `bandit`, `pyright`, `pip-audit` and that CI runs them.

---

## 3. Suggested landing order

1. **B2 + B4 + D4 triage** — enable ruff `S`/`ASYNC` + `bandit`, get `ruff check .`
   clean. (Surfaces the §4.2 blocking calls as `ASYNC` findings — informs Part A.)
2. **A1 Pass 1** — whole-file `def` conversion for zero-`await` routers.
3. **A3** — `validate_outbound_http_url_async` + the four client call sites.
4. **A1 Pass 2** — per-handler conversion in the mixed modules.
5. **A2** — add the Fernet-cache regression test; tick analysis §7.
6. **B3** — pyright config + local cleanup.
7. **B1 + B5** — add dev deps + the workflow; enable branch protection.
8. Docs: analysis §3/§7, `CLAUDE.md`.

Steps 1–5 are backend code and can be one PR (`fix/fable-rest-async-hardening`);
steps 6–8 a second (`ci/backend-workflow`).

---

## 4. Out of scope (tracked elsewhere)

- Async SQLAlchemy / `asyncpg` migration (analysis §4.2 option 4).
- `os.environ` git env mutation — S7, already fixed (`cd709d4`).
- Generic per-user rate limiting — S9, still open, separate plan.
- `pyright` `standard`/`strict` mode — revisit after `basic` is green for a release.
- Integration-test CI job — opt-in, needs live Nautobot/Gitea/Postgres/device.
