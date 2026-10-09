# Review: Phases 1–3 of `FABLE_MERGE_20261009.md`

Reviewed: 2026-10-09, against the uncommitted working tree (not a commit).
Plan: `doc/plans/FABLE_MERGE_20261009.md`. Source findings: `doc/analysis/FABLE_MERGE_20261009.md`.

**Verdict.** Phases 1–3 follow the plan, and the unit tests that cover them pass
(`173 passed`: vault client, git repo lock, webhook signatures, git repository models,
webhook service, RBAC elevation, vault hardening, credentials vault, health ready,
service factory, secret-manager OpenBao client). Three implementation bugs should be
fixed before this is treated as done. Phases 4–10 are not in the diff.

T3 (mandatory `tv` / `sid_iat`) is deferred in the plan itself, after the change broke
far more than the PD2 threshold of ~40 tests. That deferral is correct.

---

## What landed

| Phase | Items | In the diff |
|---|---|---|
| 1 | T2, R3, R4, R5, T4 | Yes. T3 deferred, as the plan allows. |
| 2 | W1, W2, W3, W4 | Yes. |
| 3 | V5–V14, SM6, SM7 | Yes, including `field(repr=False)` (V6/SM7) and KV v2 check-and-set (V10/SM6). |
| 4–10 | SM5, SM8, SM9, S9, W6, S14/R6, Q*, D*, … | No. |

The admin user dialog disables username and password on the signed-in user's own row
and omits an unchanged username from `PUT /users/{id}` (`user-dialog.tsx`,
`permissions-settings-canvas.tsx`). The backend still rejects a self password or
username change if a client sends one.

`doc/analysis/FABLE_MERGE_20261009.md` marks most of these rows fixed, but **V6/SM7 and
V10/SM6 are still listed as open** even though the code contains both. The plan header
still says "Nothing here is implemented yet."

---

## Bugs

### 1. Vault credential delete returns 500, not 503

`CredentialsService.delete_credential` now keeps the database row and raises
`CredentialVaultUnavailableError` when OpenBao rejects the KV delete. That closes the
fail-open hole (V9): the secret is not orphaned.

Create and update map that exception to 503. Delete does not. It falls through to the
generic handler, which always responds 500:

```python
# backend/routers/credentials.py::delete_credential
try:
    service.delete_credential(cred_id, acting_user_id=current_user.id)
except CredentialNotFoundError as exc:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
except Exception as exc:
    raise_internal_server_error(logger, "Failed to delete credential", exc)
```

`CredentialVaultNotConfiguredError` (vault enabled, management client missing) takes the
same path. Create and update map that one to 422. The plan assumed the router already
mapped these for every credential route, so no router change was made. The delete route
needs the same `except` arms as update: 503 for `CredentialVaultUnavailableError`, 422
for `CredentialVaultNotConfiguredError`.

### 2. `merge_kv` cannot rewrite a soft-deleted KV v2 secret

A 404 on the data path is treated as "create with `cas=0`":

```python
# backend/services/vault/client.py::merge_kv
try:
    current, version = self.read_kv_with_version(path)
except VaultSecretNotFoundError:
    current, version = {}, 0  # cas=0: create only if it still does not exist
merged = {**current, **new_fields}
return merged, self.write_kv(path, merged, cas=version)
```

`cas=0` succeeds only when the path has never existed. A soft-deleted secret
(`vault kv delete`, or a destroyed latest version) still has metadata, so OpenBao
rejects `cas=0`. The retry reads 404 again and the update fails. The previous
read-then-write restored that path.

In-app `delete_kv` uses the metadata endpoint, so a delete started by this app removes
the path and a later create is fine. An out-of-band soft delete leaves credential
updates and `OpenBaoSecretManagerClient.set_field` stuck.

On 404, read `current_version` from the metadata endpoint and send that as `cas`.
Use `cas=0` only when the metadata is missing too.

### 3. A Redis blip stalls every git mutation for 90 seconds, then fails it

`RedisCacheService.set_if_absent` returns `False` both when another worker holds the
lock and on any Redis error. `acquire_git_repo_lock` cannot tell those apart, so it
polls for `_ACQUIRE_TIMEOUT_SECONDS` (90) and raises `RuntimeError`.

Raising when the lock is actually held is what W4 asked for. Raising after a 90-second
spin when Redis is down is not: the working tree was never contended, and the step just
sits. `RuntimeError` is classified as an execution failure, so the step is marked failed.

There are two Redis-down behaviours:

- Redis is already down when the cache client is first built. `build_cache_service()`
  swallows the constructor error and returns `None`. The lock is skipped (fail-soft).
- Redis dies after that singleton exists. Every later acquire waits 90 seconds and fails.

The module docstring describes the first case as "Redis unavailable." Callers that see
`False` from `set_if_absent` need a distinct signal for "Redis error" versus "held",
and an error should fail immediately (or skip, if that is still the policy) rather than
consume the full acquire timeout.

---

## Smaller issues

**Self-rename error text.** `UserService.update_user` tells the caller to use the
change-password dialog for both password and username changes. That dialog cannot rename
anyone. Self-service rename does not exist; an admin renames you (PD1).

**Webhook budget is spent before the signature check.** `GitWebhookService` calls
`limiter.check` after "secret configured" and before `verify_github_signature` /
`verify_gitlab_token`. A caller who never presents a valid signature still consumes that
repository and client IP's 60/minute budget. GitHub's address is a different key, so this
does not drop GitHub deliveries unless both share an IP.

**Existing `REFRESH_TOKEN_MAX_AGE_HOURS=24` will refuse to boot.** The session cap stays
12, and refresh may no longer exceed it. That matches T4 / PD3. Any environment that set
24 explicitly has to be lowered before restart.

**`/health/ready` stays 200 when OpenBao is down.** `vault.ok` is reported, and the HTTP
status still depends only on database and Redis. That is the plan's V12 decision. A probe
that only watches the status code will not pull the API out of rotation. Alert on
`vault.ok == false`.

**Short webhook secrets already stored keep working** until the repository is re-saved.
W2 only rejects a new value shorter than 16 characters. An empty string still clears the
secret. Both match the plan.

**V5 removes the management token from workers, not the SecretID from their environment.**
`production_guards` is unchanged, as PD6 decided. Moving the management AppRole material
out of the worker environment is still a deployment step (`doc/VAULT_INTEGRATION.md`).

---

## Still open (not this diff)

Medium items the plan has not implemented yet: SM5 (secret field / path injection),
SM8 (blocking HTTP on the event loop), SM9 (`version` coercion), S9 / SM10 / B3
(per-user rate limits), W6 (content redaction), S14 / R6 (inventory ownership on rename),
B4 (Batfish session cache), and the Infisical verb check. D1 (`SECURITY.md`) is also
still absent.
