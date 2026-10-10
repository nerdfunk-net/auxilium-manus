# Review: T3 — mandatory `tv` and `sid_iat`

Reviewed: 2026-10-10, against the uncommitted working tree (not a commit).
Plan: `doc/plans/FABLE_MERGE_T3.md`.

**Verdict.** The plan is implemented. `_load_active_user` now fail-closes on a missing, non-int, or mismatched `tv` (bool excluded) and on a missing or non-numeric `sid_iat`, and absurd timestamps become 401. The router sweep uses `token_payload()` / `make_auth_db()`, the lenient claimless test is inverted, and the docs called out in §6 are updated. `73 passed` on the auth, helper, guard, and a sample of swept router tests. No production bypass of the new access-path check. Three leftovers should be fixed or explicitly accepted before this is treated as closed.

---

## What landed

| Plan step | In the tree |
|---|---|
| §2 helper | `backend/tests/unit/_auth_helpers.py` (`token_payload`, `make_user`, `make_auth_db`). `override_db` was left out; each file keeps a local `_override_db` that yields `make_auth_db()`, which §3.2 also allows. |
| §3 sweep | Every `verify_token` override in `tests/unit` goes through `token_payload()`. `_override_db` generators yield `make_auth_db()`. Hand-written cases in `test_require_permission_inactive_user`, `test_auth_change_password`, and `test_production_hardening` are updated. |
| §4 production | `backend/core/auth.py::_load_active_user` plus `_invalid_token()`, used only there. `verify_token` is unchanged. |
| §4.1 tests | `test_auth_token_version.py` rejects a claimless token, a missing `tv` or `sid_iat`, string / bool / NaN / overflow claims, and a non-int `token_version`. |
| §5 guard | `tests/unit/test_no_minimal_token_stubs.py`. |
| §6 docs | `doc/claude/auth.md`, `doc/OPEN_TODOS.md` (T3 section removed), `doc/plans/FABLE_MERGE_20261009.md`, `doc/analysis/FABLE_MERGE_20261009.md`. |

The access-path check matches the plan: `type(tv) is int` so `False` does not compare equal to `token_version == 0`, and `fromtimestamp` failures (`NaN`, `1e20`) are 401.

---

## Bugs

### 1. Refresh still accepts `tv: false` and mints a normal token

`_load_active_user` rejects `tv: false`. `AuthService.refresh_access_token` still uses `isinstance(token_version, int)`, and `False == 0`, so a user whose `token_version` is still the default `0` can refresh that token. Refresh then calls `create_access_token`, which writes an integer `tv`. Confirmed with a token signed by the dev `SECRET_KEY`: refresh returns a new token with `tv` of type `int` and value `0`. The same payload is 401 on `_load_active_user`.

```118:120:backend/services/auth/auth_service.py
        token_version = payload.get("tv")
        if not isinstance(token_version, int) or token_version != user.token_version:
            raise AuthenticationError("Invalid authentication token")
```

The plan left refresh alone on the grounds that it was already strict. Refresh does reject a missing `tv`. A bool still passes, which is the case §4.1 added `type() is int` to stop. `doc/claude/auth.md` now says refresh "is equally strict". That sentence overstates the code.

Building the token requires `SECRET_KEY`, and a holder of that key can mint `tv: 0` directly. The practical effect is narrower: one refresh turns a token the access path rejects into a token it accepts, for any user still on `token_version` 0.

Use the same `type(token_version) is int` test on refresh, and drop "equally strict" from `auth.md` until that lands.

### 2. A signed refresh with a bad `sid_iat` is a 500

The access path catches `OverflowError`, `OSError`, and `ValueError` from `fromtimestamp`. Refresh does not. `datetime.fromtimestamp(float("nan"))` raises `ValueError`; `1e20` raises `OverflowError`. `routers/auth.py::refresh_token` only maps `AuthenticationError` to 401, so those become an unhandled 500.

Same signing-key requirement as bug 1: `jwt.decode` runs first, so an unsigned token is still 401. Wrap the refresh `fromtimestamp` call the same way as `_load_active_user`.

### 3. `make_auth_db()` ignores the id in the token

`db.get` always returns user id 1 unless the caller passes a user in. `test_rbac_user_access_router.py` stubs `verify_token` with `token_payload(7, username="actor")` and `get_db` with `make_auth_db()`. `_load_active_user` asks for user 7 and receives user 1. `token_version` is 0 on both, so the check passes, and `require_permission` calls `has_permission` for user 1. The handler's actor is still 7 because `get_current_user` is overridden separately, and `has_permission` is patched to return true, so the actor assertions stay green.

```40:42:backend/tests/unit/test_rbac_user_access_router.py
    app.dependency_overrides[verify_token] = lambda: token_payload(7, username="actor")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: make_auth_db()
```

The permission gate in that test is running as a different user than the actor the test claims to exercise. Pass `make_auth_db(make_user(7, username="actor"))` (or a `db.get` side effect that honours the id) wherever the token's `user_id` is not 1.

---

## Checked, and sound

- A future `sid_iat` still passes the access path (`session_age` is negative, so the `>` cap does not fire). That matches the comparison in the plan. Changing it needs the signing key, and a holder of that key can mint a fresh `sid_iat` anyway.
- `user_id: true` still passes `isinstance(user_id, int)` in `_load_active_user`. That line was not part of T3. A signed token can set `user_id` to `1` directly.
- The regression guard only flags a `verify_token]` line that also contains `{` and not `token_payload`. That is the check §5 specifies. No claimless stub of that shape remains under `tests/unit`.
- `token_payload` is wrapped in a zero-arg lambda at every override, which is what the plan's corrected note requires. The helper docstring still says the function is usable directly as a dependency override; assigning it bare makes FastAPI treat `user_id` / `tv` / `username` as query params.
