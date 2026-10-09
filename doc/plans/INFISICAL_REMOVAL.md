# Review: Infisical removal

Reviewed: 2026-10-09, against the uncommitted working tree (staged deletions of
`infisical_client.py`, its tests, and `docker/infisical/`, plus the unstaged
backend, frontend, and doc edits). Not a commit.

**Verdict.** No medium, high, or critical security issues. New Infisical
connections are rejected, leftover rows fail closed before any credential is
sent, and the OpenBao URL, TLS, and credential-type checks are unchanged.
One functional bug should be fixed before this is treated as done: a leftover
`backend = 'infisical'` row makes the connection list return 500.

---

## Security

These paths were checked and do not regress.

| Area | Result |
|---|---|
| New Infisical connections | Blocked at the request model (`SecretManagerBackend` is `openbao` only), in `SecretManagerConnectionService` (`_VALID_BACKENDS`), and in `registry._build_client`. |
| Credential exfiltration (SM2) | `secret_manager_auth()` still accepts only `generic` credentials. The OpenBao adapter posts AppRole material only to a validated `addr`. |
| SSRF / transport policy | `addr` still goes through `validate_connection_transport()` → `validate_outbound_http_url`. Outside development the URL must be `https` and `verify_ssl` must stay true. |
| Auth / RBAC | The router is unchanged: `secret_manager.connections:{read,write,delete}`, and `/test` stays rate-limited (10/min). |
| API responses | Responses expose `credential_name` and `backend_config` only. Decrypted secrets are not returned. |
| Runtime fail-closed | A leftover `backend='infisical'` row raises `SecretManagerConfigError` in `registry._build_client` before any HTTP client is built. Credentials are resolved in memory and are not transmitted. The test endpoint returns that error string; it does not include the secret. |
| Field/path injection (SM5) | Unchanged in `service.py` / `validation.py`. Removing Infisical removes the field-in-URL-path vector that existed only in the deleted client. |
| Leftover imports | No remaining `infisical_client` / `Infisical` imports in backend Python or frontend TypeScript. |
| Docker dev stack | `docker/infisical/` is deleted. No orphaned Infisical service under `docker/`. |

---

## Bugs

### 1. A leftover Infisical row makes the connection list return 500

`SecretManagerConnectionResponse.backend` is now `SecretManagerBackend`, which
has only `openbao`:

```python
# backend/models/secret_manager.py
class SecretManagerBackend(StrEnum):
    OPENBAO = "openbao"

class SecretManagerConnectionResponse(BaseModel):
    backend: SecretManagerBackend
```

The list and get-by-id handlers build that model for every row:

```python
# backend/routers/secret_manager.py::get_connections
connections = connection_service.get_connections(active_only=active_only)
responses = [SecretManagerConnectionResponse(**c) for c in connections]
return SecretManagerConnectionListResponse(connections=responses, total=len(responses))
```

Pydantic rejects `backend='infisical'`. The handler catches that as a generic
exception and `raise_internal_server_error` turns it into a 500. The client
sees the sanitized internal-error response, not the row. One old row hides
every connection, including OpenBao ones.

`secret_manager_connections.backend` is still `String(50)` with no check
constraint, and this change adds no data migration, so existing rows stay.
`doc/SECRET_MANAGER_INTEGRATION.md` tells the operator to delete or recreate
them. The Settings page and the workflow connection picker both load this
list, so that is the page that crashes.

Create and update already refuse `infisical` (422 from the request model on
create; `ValueError` → 400 from the service when an update touches transport
fields). Delete by id still works: it reads the raw dict and does not build
`SecretManagerConnectionResponse`. An admin who knows the id can delete the
row through the API. The UI cannot show it.

Workflow steps that reference the id fail at client build with
`Unknown secret manager backend: 'infisical'`. No credential is POSTed to
`site_url`.

Fix: either migrate leftover rows (delete them, or mark them unusable in a
way the response model accepts) or let list/get return an unknown backend
without failing the whole list, so an admin can see and delete the row.
A response-model change alone does not make the row usable.

---

## Stale copy

These do not change runtime behavior.

- `backend/models/secret_manager.py` — `credential_name` description still
  says `client_id` / `client_secret`.
- `backend/services/credentials/manager.py` — `secret_manager_auth()` docstring
  still mentions `site_url`.
- `frontend/src/components/features/settings/dialogs/secret-manager-help-dialog.tsx`
  — step 6 still says "Add connection: backend **OpenBao**". The backend
  selector was removed from the connection dialog.
