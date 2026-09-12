# Review: open questions and gaps in `FABLE_20260912.md`

Source plan: `doc/plans/FABLE_20260912.md`, itself sourced from
`doc/analysis/FABLE_BACKEND_20260912.md` §3.2 (V), §4.2 (T), §5.2 (R), §9.
Status: **resolved** — all four points applied to `FABLE_20260912.md` on 2026-09-12.

## Verdict

The plan is unusually rigorous. Every "Before" code snippet was checked against the live code
(`core/config.py`, `core/client_ip.py`, `core/production_guards.py`, `routers/auth.py`,
`services/auth/{login_rate_limiter,rbac_service}.py`, `repositories/rbac_repository.py`,
`services/users/user_service.py`, `services/credentials/credentials_service.py`,
`services/git/auth.py`, `services/vault/{client,token_manager,config,auth}.py`,
`docker/docker-compose.yml`, `backend/.env.example`, `docker/.env.example`) and matches line for
line, which means the plan's author actually read the code rather than guessing. The V4 test
expectations were hand-verified by computing `renew_interval_seconds()` against the stated
buffer/period/lease values and they check out exactly. The "Order of work" (§9) is genuinely
dependency-free — each numbered step touches a disjoint slice of the codebase, so "one commit
each, each green before the next" is a realistic claim, not just an aspiration.

One section has a real bug that contradicts the plan's own stated design decision and would ship
silently (none of the plan's listed tests would catch it). The rest are minor documentation/path
inaccuracies that would only trip up a literal, no-thinking implementation.

---

## 1. §2.1 R1 — `assert_may_take_over` blocks self-changes, contradicting D4

This is the one issue to fix before implementing.

D4 states the design intent explicitly:

```51:54:doc/plans/FABLE_20260912.md
**D4 — R1 subset rule.** A password reset or username change by a non-admin actor is allowed only
if every effective permission of the target is one the actor holds, and never when the target
holds a protected (`rbac.*`, `users`, `system.*`) permission. Admins and internal callers
(`actor_user_id=None`) bypass. Self-changes are not blocked here (that is T2, out of scope).
```

But the proposed helper never checks `actor_user_id == target_user_id`:

```746:761:doc/plans/FABLE_20260912.md
    def assert_may_take_over(self, actor_user_id: int | None, target_user_id: int) -> None:
        """R1: setting a user's password (or renaming them) hands the actor every
        permission the target holds. Allowed only when that set is a subset of the
        actor's own (P2) and contains no protected permission (P3). Admins and
        internal callers bypass, like every other policy helper."""
        if actor_user_id is None or self._is_admin(actor_user_id):
            return
        for permission, _source in self.get_effective_permissions(target_user_id):
            if _is_protected(permission) or not self.has_permission(
                actor_user_id, permission.resource, permission.action
            ):
                raise AccessDeniedError(
                    "Admin role required to reset the password or rename a user who holds "
                    f"{permission.resource}:{permission.action}"
                )
```

Trace the case D4 says must pass: a non-admin actor changes **their own** password via
`PUT /users/{id}`. That endpoint requires `users:write` (router-level `require_permission`), so
the actor necessarily holds `users:write`. `assert_may_take_over(actor, actor)` then iterates the
actor's own effective permissions — which includes `users:write` itself. `_is_protected` treats
resource `"users"` as protected:

```10:19:backend/services/auth/rbac_service.py
PROTECTED_RESOURCES: tuple[str, ...] = ("rbac.", "users", "system.")


def _is_protected(permission: Permission) -> bool:
    return any(
        permission.resource == prefix.rstrip(".") or permission.resource.startswith(prefix)
        for prefix in PROTECTED_RESOURCES
    )
```

So the loop hits `_is_protected(users:write) == True` on the actor's **own** permission and
raises `AccessDeniedError` — every non-admin `users:write` holder is blocked from changing their
own password or username through this endpoint, not just other people's. That is a regression
relative to today's behavior (self-update currently works, just without a current-password
check — that gap is T2, explicitly out of scope here) and it directly contradicts D4's "self-
changes are not blocked here." None of the tests listed in §2.4 exercise
`target_user_id == actor_user_id`, so this would ship without a failing test to catch it.

**Fix:** add `if actor_user_id == target_user_id: return` at the top of `assert_may_take_over`
(mirroring the self-check already used by `assert_not_self`), before the permission loop. Add a
test: `test_self_password_change_is_not_blocked_by_takeover_rule` (non-admin `users:write` holder
changes their own password → succeeds).

---

## 2. §5.3 V2 — the "three direct callers" list omits a fourth call site

The plan enumerates "the three direct `resolve_credentials` callers" that need
`discard_ephemeral_ssh_key` wrapping: `services/git/connection.py::test_connection`,
`services/git/debug_service.py::_collect_auth_and_push_diagnostics`, and
`services/git/debug_service.py::test_push`. That's accurate for non-test code, but
`backend/tests/integration/test_mutations_optin.py` also calls
`GitAuthenticationService().resolve_credentials(...)` directly, twice (`_delete_remote_branch`
and `test_git_push_to_scratch_branch`), without discarding the ephemeral key:

```35:38:backend/tests/integration/test_mutations_optin.py
def _delete_remote_branch(repo_dict: dict, branch: str) -> None:
    auth = GitAuthenticationService()
    username, token, _ = auth.resolve_credentials(repo_dict)
```

Low real-world impact — it's an opt-in mutation test that currently exercises token auth against
Gitea, not a vault-backed SSH key, and V2's own stale-file purge (`EPHEMERAL_SSH_KEY_MAX_AGE_SECONDS
= 60 * 60`) would clean up a leaked file within an hour regardless. But the "three callers" count
is not quite complete; worth either fixing this test too or adding one sentence acknowledging
test-only call sites are out of scope.

---

## 3. §1.9 — the frontend test reference doesn't match the current file

The plan says to add/update `frontend/src/lib/__tests__/api-proxy.test.ts`, asserting that
`buildForwardHeaders` drops `x-real-ip` and `forwarded`. Two inaccuracies:

- The actual file is co-located, not in a `__tests__` directory:
  `frontend/src/lib/api-proxy.test.ts`.
- `buildForwardHeaders` is not exported from `api-proxy.ts`:

```97:97:frontend/src/lib/api-proxy.ts
async function buildForwardHeaders(sourceHeaders: Headers, authorization?: string) {
```

The existing suite only exercises the exported `proxyRequest` / `normalizeProxyPath` (e.g. the
"strips a Location header from the backend response" test). The new header-stripping assertion
will need to go through `proxyRequest` the same way, not call `buildForwardHeaders` directly.

---

## 4. §1.6 vs §4.1 — two independent diffs to the same function, shown against the same baseline

Both sections patch `core/production_guards.py::validate_non_development_secrets`: §1.6 (T1, the
*last* step in §9's order) adds `trusted_proxy_ips_configured`, and §4.1 (V1, the *second* step)
adds `vault_verify_ssl`. Each section's "Before" block is taken from the original, unmodified
function — so §1.6's "Before" won't literally match the file once V1 has already landed (it will
already contain `vault_verify_ssl`). The two diffs don't conflict (different parameters, different
insertion points in the body), so this doesn't break anything functionally, but a literal
implementer diffing text against the current file state could be confused about which "Before" is
current at step 8. Worth a one-line note in §1.6 or §4.1 flagging that both sections touch the same
function independently and the "Before" snapshots are both relative to the pre-plan baseline, not
to each other.

---

## 5. Smaller, non-blocking observations

- **`discard_ephemeral_ssh_key` always touches the ephemeral directory.** The proposed
  implementation calls `ephemeral_ssh_keys_directory()` (which `mkdir`s and `chmod`s
  `data/ssh_keys/tmp/`) even when the path being discarded is a permanent `local`-backend export
  that will be left alone. Harmless — it's idempotent and cheap — but it means every git-auth
  teardown creates an always-empty `tmp/` directory on disk even on deployments that never use
  vault-backed SSH keys.
- **Two-step `assert_allowed`/`record` split (§1.3) reintroduces a check-then-act window.** Under
  concurrent requests, two callers can both pass `assert_allowed` before either calls `record`,
  letting a burst slightly exceed the configured budget. The original single-function `check()`
  had a similar (smaller) window across its own two pipeline round-trips, so this isn't a new
  class of problem — just worth knowing it's not perfectly atomic under load. Not worth blocking
  on for a login-rate-limit use case.
- **Fail-closed still means "Redis down ⇒ no logins in production"** for both new limiters (same
  as the existing single limiter today via `fail_closed=settings.environment != "development"`).
  Not a regression introduced by this plan, but doubling the limiter count doubles the number of
  Redis round trips on a failed login attempt (up to 4 vs. 2 today). Purely a minor performance
  note.

---

## Suggested resolution before/while implementing

1. Add the missing self-exemption to `assert_may_take_over` (§1 above) and a test for it — this is
   the one change that must happen before merging, since it silently breaks self-service password
   changes for every non-admin `users:write` holder.
2. Either extend V2's ephemeral-key cleanup to `tests/integration/test_mutations_optin.py`'s two
   direct `resolve_credentials` calls, or add a sentence scoping test helpers out.
3. Fix the frontend test file path (`frontend/src/lib/api-proxy.test.ts`, no `__tests__` dir) and
   route the new assertion through the exported `proxyRequest`, not the private
   `buildForwardHeaders`.
4. Add a one-line cross-reference between §1.6 and §4.1 noting both edit
   `validate_non_development_secrets` independently, so the "Before" blocks aren't read as
   contradicting each other.
