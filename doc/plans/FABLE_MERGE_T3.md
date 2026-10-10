# Plan: T3 — make `tv` and `sid_iat` mandatory on every access token

Source: `doc/analysis/FABLE_MERGE_20261009.md` (T3, Low) · deferred in `doc/plans/FABLE_MERGE_20261009.md`
§1.5 / PD2 · tracked in `doc/OPEN_TODOS.md` ("Make `tv` / `sid_iat` mandatory…").
Status: **implemented 2026-10-10 (uncommitted).** Run everything from `backend/` with the project venv
(`source ../.venv/bin/activate`). Write the tests first (RED), then the change (GREEN).

## 0. Why this was deferred, and what is actually broken

The production change is ~15 lines in `core/auth.py::_load_active_user`. It was reverted in Phase 1 because
it failed **393 unit tests**. I re-applied the change temporarily on `main` (clean tree, reverted
afterwards) and measured: **397 failures in 37 files, 0 of them in production code paths.**

| Files | Failures | Cause |
|---|---|---|
| 30 router tests (largest: `test_ise_router_ops` 74, `test_sources_crud_routers` 64, `test_catalyst_center_ops_router` 24, `test_git_routers_ops` 21, `test_sources_nautobot_crud_router` 19, `test_git_repositories_router` 16) | ~370 | Router tests override `verify_token` with `{"sub": …, "user_id": 1}` **and** `get_db` with a bare `MagicMock()` |
| `test_require_permission_inactive_user` | 4 | `checker({"user_id": 1}, MagicMock())` — same two problems |
| `test_auth_change_password`, `test_auth_token_version`, `test_production_hardening` | 4 | One claim-less test, one test that *asserts the lenient behaviour* (must be inverted), two payload stubs |

Two independent causes, **both** must be fixed per test (fixing only one still fails):

1. **Payload lacks claims.** `lambda: {"sub": "tester", "user_id": 1}` has no `tv` / `sid_iat` (65 sites).
2. **The user row is a `MagicMock`.** Routers that use `require_permission(...)` go through
   `_require_active_user_id → _load_active_user → UserRepository(db).get_by_id → db.get(User, id)`.
   With `db = MagicMock()` that returns another `MagicMock`, so `user.token_version` is a `MagicMock` and
   `tv != user.token_version` is true. Today this passes only because of the `isinstance(user.token_version, int)`
   guard — exactly the tolerance T3 removes (24 `_override_db` helpers, all `yield MagicMock()`).
   Note `get_current_user` is overridden in most files, so the *router handler* never sees the mock, but the
   `require_permission` dependency still does.

The 393 are therefore **not** 393 independent edits: it is 65 identical lambdas + 24 identical `_override_db`
generators + ~6 hand-written cases. All of it is mechanical once there is one shared helper.

## 1. Decisions

**TD1 — One helper module, flat in `tests/unit/`.** `tests/unit` has no `__init__.py` and `pythonpath = ["."]`;
existing shared helpers are flat modules imported by bare name (`from _git_repo_builder import …`). Follow that:
`tests/unit/_auth_helpers.py` (the 09-10 plan's `tests/unit/helpers/tokens.py` would be the only sub-package in
the directory and needs an `__init__.py` + import-mode change — not worth it).

**TD2 — No autouse conftest shim.** A conftest fixture that patches `core.auth.UserRepository.get_by_id` or
`_load_active_user` for every test would make the suite green with zero edits, but it would also hide the very
check T3 adds (tests would no longer prove a stub token is *valid*). Explicit helpers, per test file.

**TD3 — Strict, no compat flag.** Per project memory (single-user dev system, no backward-compat shims): no
`ALLOW_LEGACY_TOKENS` setting. Rollout effect: any token minted before the T-series (no `tv`/`sid_iat`) gets
401 once, the frontend's 401 → `/auth/refresh` (already strict) → login redirect handles it. Every token minted
since S5 carries both claims, so a normal session is unaffected.

**TD4 — Land as one commit, after a green baseline.** Order: helper → mechanical sweep **with the production
code still lenient** (suite stays green, proves the sweep is correct) → production change → invert/add tests.
This keeps the "RED" step small and diagnosable instead of 397 failures at once.

**TD5 — A guard test stops regressions.** New routers copy-paste the nearest test; without a guard the minimal
`{"sub", "user_id"}` stub comes back and T3 starts failing for the next feature author. See §5.

## 2. Step 1 — shared test helper

New file `backend/tests/unit/_auth_helpers.py`.

before: *(does not exist; every file defines its own stub inline)*
```python
# tests/unit/test_router_auth.py (and ~29 siblings)
def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()

app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
```

after:
```python
"""Shared auth doubles for router/dependency tests (T3).

`core.auth._load_active_user` requires `tv` (== user.token_version) and `sid_iat`
(within SESSION_MAX_AGE_HOURS) on every token. These helpers produce a payload and a
DB double that satisfy that check so tests exercise the *real* guard instead of
bypassing it.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

from core.models.users import User


def token_payload(
    user_id: int = 1, *, tv: int = 0, username: str = "tester", **extra: Any
) -> dict[str, Any]:
    """A valid verify_token payload. Usable directly as a dependency override."""
    now = int(time.time())
    return {"sub": username, "user_id": user_id, "tv": tv, "sid_iat": now, "iat": now, **extra}


def make_user(user_id: int = 1, *, username: str = "tester", token_version: int = 0) -> User:
    user = User(username=username, password_hash="hash", is_active=True)
    user.id = user_id
    user.token_version = token_version
    user.must_change_password = False
    return user


def make_auth_db(user: User | None = None) -> MagicMock:
    """A `Session` double whose `db.get(User, id)` returns an active user with token_version 0.

    `UserRepository.get_by_id` is `self.db.get(User, user_id)`, so this is all `_load_active_user` touches.
    Everything else on the double is still a plain MagicMock, as before.
    """
    db = MagicMock()
    db.get.return_value = user or make_user()
    return db


def override_db(user: User | None = None):
    """Drop-in replacement for the per-file `_override_db` generators."""

    def _dep() -> Iterator[MagicMock]:
        yield make_auth_db(user)

    return _dep
```

Why `token_payload` takes no required args: FastAPI invokes an override with the *original dependency's*
signature; `verify_token` has a `credentials` param with a default, and a zero-arg callable is accepted.
Existing `lambda: {...}` already relies on this, so `app.dependency_overrides[verify_token] = lambda: token_payload()` keeps working unchanged. (Passing `token_payload` itself would make FastAPI treat its parameters as query params, so always wrap it in a zero-arg lambda.) (Verified in the sweep.)

**Tests (RED first)** — `tests/unit/test_auth_helpers.py`: `token_payload()` passes `_load_active_user(…, make_auth_db())`
with the *current* code, and `make_auth_db()` returns a user with `token_version == 0 and is_active is True`.
This pins the helper contract so a later `User` model change (new required auth column) breaks one test, not 37 files.

## 3. Step 2 — mechanical sweep (production code unchanged, suite stays green)

Two codemods, scoped to `tests/unit` only. Use scripted replacement, then review `git diff --stat`.

### 3.1 Payload lambdas (65 sites, 41 files)

before:
```python
app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
app.dependency_overrides[verify_token] = lambda: {"sub": "t", "user_id": 1}
```
after:
```python
from _auth_helpers import token_payload
...
app.dependency_overrides[verify_token] = token_payload
```
Variants with other users (`"sub": "alice"`, other ids) → `lambda: token_payload(7, username="alice")`.
`grep -rn 'verify_token\] = ' tests/unit | grep -v token_payload` must be empty afterwards.

### 3.2 `_override_db` generators (24 sites)

before (`test_router_auth.py`, `test_batfish_router_auth.py`, …):
```python
def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()

app.dependency_overrides[get_db] = _override_db
```
after:
```python
from _auth_helpers import make_auth_db

def _override_db() -> Iterator[MagicMock]:
    yield make_auth_db()
```
Keep each file's local `_override_db` name (small diff, no import churn in call sites). Files whose db
double carries test-specific behaviour (`db.scalar.return_value = …`, `db.query…`) call `make_auth_db()` and then
add to it:
```python
def _override_db() -> Iterator[MagicMock]:
    db = make_auth_db()
    db.scalar.return_value = existing_repo_row
    yield db
```
(`db.get` is only used for `User` lookups in these routers today; where a test also needs `db.get(Model, id)` to
return something else, give `db.get.side_effect = lambda model, pk: user if model is User else other`.)

### 3.3 Local `_make_user()` doubles

46 files override `get_current_user` with a local `_make_user`. Those users never reach `_load_active_user`
(it is bypassed), so they need **no** change for T3. Leave them; do not widen the diff.

### 3.4 Hand-written cases (about six)

| Test | Before | After |
|---|---|---|
| `test_require_permission_inactive_user.py` (×4 parametrised callers) | `checker({"user_id": 1}, MagicMock())` with `get_by_id` patched to `_user(is_active=…)` | `checker(token_payload(), MagicMock())`; the local `_user()` gets `token_version = 0` (or reuse `make_user`) |
| `test_auth_change_password.py::test_other_endpoints_blocked_while_must_change_password_is_set` | `verify_token` stub `{"sub": "alice", "user_id": 1}` + `get_by_id` patched to a `_user(must_change_password=True)` | stub → `token_payload(username="alice")`; `_user()` → `token_version=0` |
| `test_production_hardening.py` (2 sites, ~l. 505/573) | minimal payload lambdas | `token_payload` |
| `test_run_events_api.py`, `test_settings_token_redaction.py` | minimal payload lambda **and** `MagicMock` db | §3.1 + §3.2 |

Checkpoint: `python -m pytest tests/unit -q --no-cov` → **same pass count as before the sweep**
(green, production code still lenient). Commit nothing yet; this proves the sweep is behaviour-neutral.

## 4. Step 3 — production change (RED → GREEN)

### 4.1 Tests first — `tests/unit/test_auth_token_version.py`

The existing test **documents the leniency that T3 removes** and must be inverted:

before:
```python
    def test_claimless_token_for_active_user_is_not_proactively_rejected(self) -> None:
        # Pre-S5 shape ({sub,user_id,exp}); documents the §0 split — verify is
        # lenient, refresh is strict.
        self._patch_get_by_id(_user())
        user = _load_active_user({"user_id": 1}, MagicMock())
        self.assertEqual(user.id, 1)
```
after (and three siblings; all `_patch_get_by_id(_user())` with `token_version=0`):
```python
    def test_token_without_tv_is_rejected(self) -> None:
        self._patch_get_by_id(_user())
        with pytest.raises(HTTPException) as exc:
            _load_active_user({"user_id": 1, "sid_iat": _now_ts()}, MagicMock())
        self.assertEqual(exc.value.status_code, 401)

    def test_token_without_sid_iat_is_rejected(self) -> None:
        self._patch_get_by_id(_user())
        with pytest.raises(HTTPException) as exc:
            _load_active_user({"user_id": 1, "tv": 0}, MagicMock())
        self.assertEqual(exc.value.status_code, 401)

    def test_non_numeric_claims_are_rejected(self) -> None:
        self._patch_get_by_id(_user())
        for bad in ({"tv": "0", "sid_iat": _now_ts()}, {"tv": 0, "sid_iat": "now"}, {"tv": True, ...}):
            ...
    def test_user_without_integer_token_version_is_rejected(self) -> None:
        # a row whose token_version is not an int must never authenticate (fail closed)
```
`bool` is an `int` subclass in Python — reject `True`/`False` explicitly (`type(token_tv) is int`), otherwise a
forged `"tv": false` equals `token_version == 0`. (Signed tokens can't be forged without `SECRET_KEY`, so this is
defence in depth, but it costs one condition.)

Run: new tests **fail** against current `core/auth.py` → RED.

### 4.2 `backend/core/auth.py::_load_active_user`

before:
```python
    # Revocation (S5): every access token carries `tv` = the user's
    # token_version at mint time. ... Both sides are
    # isinstance-guarded so a mocked user row with a non-int token_version does
    # not trip this by accident — same philosophy as the `must_change_password
    # is True` check in get_current_user / _require_active_user_id.
    token_tv = token_payload.get("tv")
    if (
        isinstance(user.token_version, int)
        and isinstance(token_tv, int)
        and token_tv != user.token_version
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers=AUTHENTICATE_HEADER,
        )

    # Absolute session lifetime (S5): `sid_iat` is the original login time,
    # carried unchanged through every refresh. Enforced whenever the claim is
    # present — every token this code mints has it; the refresh path
    # (AuthService.refresh_access_token) additionally *requires* it, so a token
    # without it cannot be renewed and dies at its own `exp`.
    sid_iat_raw = token_payload.get("sid_iat")
    if isinstance(sid_iat_raw, int | float):
        session_age = datetime.now(UTC) - datetime.fromtimestamp(sid_iat_raw, UTC)
        if session_age > timedelta(hours=settings.session_max_age_hours):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
                headers=AUTHENTICATE_HEADER,
            )

    return user
```

after:
```python
    # Revocation (S5/T3): every access token carries `tv` = the user's
    # token_version at mint time; a bump (logout, password / username change,
    # deactivation) makes older tokens stale. The claim is mandatory and must
    # match exactly — a token without it, or a row whose token_version is not an
    # int, is rejected (fail closed).
    token_tv = token_payload.get("tv")
    if (
        type(token_tv) is not int  # bool is an int subclass; reject it explicitly
        or type(user.token_version) is not int
        or token_tv != user.token_version
    ):
        raise _invalid_token()

    # Absolute session lifetime (S5/T3): `sid_iat` is the original login time,
    # carried unchanged through every refresh, and is mandatory.
    sid_iat_raw = token_payload.get("sid_iat")
    if type(sid_iat_raw) not in (int, float) or datetime.now(UTC) - datetime.fromtimestamp(
        sid_iat_raw, UTC
    ) > timedelta(hours=settings.session_max_age_hours):
        raise _invalid_token()

    return user
```
with a small module-level helper replacing the four copies of the 401 construction in this file:
```python
def _invalid_token() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication token",
        headers=AUTHENTICATE_HEADER,
    )
```
(`fromtimestamp` raises `OverflowError`/`OSError`/`ValueError` for absurd values such as `1e20`/`NaN`; wrap in
`try/except (OverflowError, OSError, ValueError)` → `_invalid_token()` — add a test with `float("nan")`.)

Do **not** touch `verify_token` (it only decodes) or `AuthService.refresh_access_token` (already strict).

## 5. Step 4 — guard against regression (TD5)

New `tests/unit/test_no_minimal_token_stubs.py`:
```python
def test_no_test_stubs_verify_token_with_a_claimless_payload():
    offenders = [
        f"{p.name}:{i}"
        for p in Path(__file__).parent.glob("test_*.py")
        for i, line in enumerate(p.read_text().splitlines(), 1)
        if "verify_token]" in line and "token_payload" not in line and "{" in line
    ]
    assert not offenders, "use _auth_helpers.token_payload() (T3): " + ", ".join(offenders)
```
Cheap, and the failure message tells the next author the fix.

## 6. Step 5 — docs

| File | Before | After |
|---|---|---|
| `doc/claude/auth.md` ("Revocation") | "…so a pre-`tv` token cannot be refreshed. Legacy pre-`tv`/`sid_iat` tokens die at their own `exp` (≤ 60 min) since they cannot be renewed." | "`tv` and `sid_iat` are mandatory on every request: `_load_active_user` rejects a token missing either (401). Tokens minted before S5 are no longer accepted; the client is sent to login." |
| `doc/claude/auth.md` JWT block comment | `"sid_iat": …  # original login time; carried UNCHANGED…` | add "(required)" to `sid_iat` and `tv` comments |
| `doc/OPEN_TODOS.md` | T3 section | delete the section (task-completion rule: remove the item once done) |
| `doc/plans/FABLE_MERGE_20261009.md` | status table "⏸ T3 deferred", §1.5 deferred banner, "Not done" line | "✅ T3 fixed — see `FABLE_MERGE_T3.md`"; §1.5 points here |
| `doc/analysis/FABLE_MERGE_20261009.md` | T3 row "⏸ deferred" | "✅ fixed" |

Finish with the project's grep check: `grep -rn "isinstance(user.token_version\|pre-.tv\|claim-less\|claimless" backend doc` must
return only the new test names / this plan.

## 7. Verification

1. After §3 (production code lenient): `python -m pytest tests/unit -q --no-cov` — same pass count as baseline.
2. After §4.1 (tests added, code lenient): exactly the new T3 tests fail.
3. After §4.2: `python -m pytest tests/unit -q` **with coverage** (ratchet `--cov-fail-under=81`) — 0 failures.
4. `ruff check core/auth.py tests/unit/_auth_helpers.py tests/unit/test_auth_*.py tests/unit/test_no_minimal_token_stubs.py`
   (scope to touched files only, per the ruff-scope rule; for the sweep use `git diff --name-only` as the file list).
5. `pyright core/auth.py` — no new errors (`type(x) is not int` narrows fine; check `sid_iat_raw` is narrowed to `int | float`
   for `fromtimestamp`, else assign via `float(sid_iat_raw)` after the type check).
6. Manual smoke against a running dev stack: log in (cookie token works), log out in another tab (old token → 401), and
   hand-craft a claim-less token signed with the dev `SECRET_KEY` → 401 from `/api/proxy/auth/me`.
7. Regression sweeps: `python scripts/check_router_repositories.py` and the other guards from `doc/claude/development.md` (no router code changes, expected clean).

## 8. Effort, risk, rollback

- **Effort:** S–M, mostly mechanical: ~41 test files touched by scripted replacement + 1 helper + 1 guard test; 1 production file.
- **Risk:** low. Production exposure is only legacy tokens (≤ 60 min lifetime, none in a fresh public deployment).
  The sweep is verified behaviour-neutral (§7.1) *before* the strict check lands, so a red suite afterwards points at real logic, not at stubs.
- **Rollback:** revert `core/auth.py` only (§4.2). The helper/sweep is compatible with both the lenient and the strict guard.
- **Out of scope:** `jti` denylist (T5), per-session logout, any change to refresh semantics.

## 9. Open question for you

Whether to keep `_invalid_token()` as a private helper in `core/auth.py` (touches the other three `HTTPException`
constructions in the file for consistency) or limit the diff to the two new checks. Default in this plan: add the helper and
use it in `_load_active_user` only; leave `verify_token` / `require_*` untouched.
