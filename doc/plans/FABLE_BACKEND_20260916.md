# Plan: Fix SM1, SM2, SM3, B1, B2

Source: `doc/analysis/FABLE_BACKEND_20260916.md` §2.2 (SM), §3.2 (B), §6.
Status: **proposed**.

| # | Sev | Issue | Decision |
|---|---|---|---|
| SM1 | M | `POST /secret-manager/connections/{id}/test` always reports success | `ensure_started` must prove authentication for both adapters (D1) |
| SM2 | M | Secret Manager `addr`/`site_url` skip the outbound-URL policy, `verify_ssl=false` honoured in production, any global `ssh` credential usable as connection auth | outbound policy + https-only + TLS-verify required outside development; `generic`-type credential only; `secret_manager.*` becomes a protected resource (D2) |
| SM3 | M | `secret-set` `fixed_value` stores a literal secret in the workflow definition and in the workflows git repo | remove `fixed` mode; `attribute` is the only mode (D3) |
| B1 | M | Batfish `host` skips the outbound-URL policy; `init_snapshot` becomes a config-exfiltration channel | outbound policy on `http://{host}:{port}` at create/update/test and at resolve time (D4) |
| B2 | M | Ad-hoc Batfish query endpoints readable by the `viewer` role across private workflows | new `sources.batfish:query` permission, not granted to `viewer`; discovery stays `read` (D5) |

Every issue ends with the tests that must exist before it is considered done. Run from
`backend/` with the project venv: `source ../.venv/bin/activate`. Order of work: SM2 → B1 →
SM1 → B2 → SM3 (SM2 and B1 share one helper pattern; SM1 builds on SM2's constructor changes).

---

## 0. Decisions

**D1 — SM1.** `OpenBaoService.startup()` keeps its soft-fail semantics for app boot (the vault
credential store must not take the API down). It gains a read-only `healthy` property. The
Secret Manager adapters' `ensure_started()` is the *strict* variant: OpenBao checks `healthy`
after `startup()` and, on failure, shuts the service down (cancelling the renew task) and raises
`SecretManagerAuthError`; Infisical performs the Universal Auth login inside `ensure_started()`
(off the event loop) and lets the existing `SecretManagerAuthError` / `SecretManagerUnavailableError`
propagate. `SecretManagerClientRegistry.get_or_create` already only caches after
`ensure_started()` returns, so a failed connection is never cached.

**D2 — SM2.** Three independent controls, all enforced in `SecretManagerConnectionService`
(create *and* update, on the merged row) and again at client construction (rows that predate
the check):
1. `addr` / `site_url` must pass `core.safe_urls.validate_outbound_http_url` (`resolve_dns=True`
   at CRUD time, `resolve_dns=False` at construction — no DNS on the worker hot path).
2. Outside `development`: scheme must be `https` and `verify_ssl` must be `True`. This mirrors
   V1 (`VAULT_VERIFY_SSL`) exactly; a per-row setting cannot be a startup guard, so the check
   lives in the service.
3. `credential_name` resolves through a new `CredentialManager.secret_manager_auth(name)` that
   accepts **`generic` only** (not `ssh`). The row's auth material can therefore never be a
   device SSH credential.

Additionally `secret_manager.` is added to `PROTECTED_RESOURCES` (P3): write on it is
equivalent to reading credential secrets, so only an admin may grant it. Existing custom roles
that already hold it keep it (P3 gates *changes*, not existing grants).

**D3 — SM3.** `fixed` mode is removed, not dev-gated. The supported way to write a known value
is `attribute` mode reading a run input (`run_input.<name>`, supplied at trigger time and never
persisted in the definition) or an upstream `secret-get` / `generate-password` /
`secret-generate` result. A saved workflow with `mode: fixed` fails loudly at run time with a
`ValueError` naming the fix; nothing is silently rewritten. The frontend panel loses the mode
select and the `fixed_value` input. A `credential` mode (reference a global `generic`
credential) is a reasonable follow-up but is **not** part of this plan.

**D4 — B1.** `BatfishSourceConfigService` validates `f"http://{host}:{port}"` with
`validate_outbound_http_url` on create, update, inline test (`resolve_dns=True`) and in
`resolve_connection` (`resolve_dns=False`). `UnsafeURLError` is re-raised as
`BatfishValidationError` so the existing 400 mappings apply. Native-host development against
`127.0.0.1` therefore needs `ALLOW_LOOPBACK_SOURCE_URLS=true`, exactly like pyATS/OpenBao; the
doc bullet claiming otherwise is corrected and `doc/SECURITY-NOTES.md` gets the
"device configs are uploaded to the Batfish container" entry the Batfish doc promised.

**D5 — B2.** A new permission `sources.batfish:query` gates the nine
`POST /sources/batfish/{id}/query/*` routes. `seed_rbac` grants it to `admin` only (`viewer`
receives `read` actions only, unchanged code path). The two discovery routes stay on `read`:
they return network/snapshot *names* only and are needed by the workflow-step config pickers.
The Template Editor hides the Batfish tab when the user lacks `sources.batfish:query`. The
finer-grained "map `manus-workflow-*` back to the workflow and apply visibility" option from the
audit is deferred — it needs an ownership table for custom `network_name` values.

Out of scope (deliberately): SM4–SM12, B3–B9, C-items. SM7 (`repr=False`) touches
`services/secret_manager/config.py`, which this plan edits, but is left for the hardening pass
so the diff stays reviewable.

---

## 1. SM2 — outbound policy, TLS, credential type, protected resource

### 1.1 `services/credentials/manager.py` — `generic`-only resolver

**Before**

```python
_SSH_TYPES = frozenset({"ssh"})
_GENERIC_TYPES = frozenset({"ssh", "generic"})
_SHARED_SECRET_TYPES = frozenset({"shared_secret"})
```

```python
    def generic(self, name: str) -> GenericSecret:
        """Resolve an ``ssh`` or ``generic`` credential for a non-SSH transport."""
        match = self._match_by_name(name, _GENERIC_TYPES, "'ssh' or 'generic'")
        username, password = self._decrypt_password(
            match, name, "has no decryptable password"
        )
        return GenericSecret(username=username, password=password)
```

**After**

```python
_SSH_TYPES = frozenset({"ssh"})
_GENERIC_TYPES = frozenset({"ssh", "generic"})
# Secret Manager connection auth (AppRole role_id/secret_id, Infisical
# client_id/client_secret) may only come from a `generic` credential -- never
# from a device SSH credential, whose password would otherwise be POSTed to
# whatever addr/site_url the connection points at (SM2).
_SECRET_MANAGER_AUTH_TYPES = frozenset({"generic"})
_SHARED_SECRET_TYPES = frozenset({"shared_secret"})
```

```python
    def generic(self, name: str) -> GenericSecret:
        """Resolve an ``ssh`` or ``generic`` credential for a non-SSH transport."""
        match = self._match_by_name(name, _GENERIC_TYPES, "'ssh' or 'generic'")
        username, password = self._decrypt_password(
            match, name, "has no decryptable password"
        )
        return GenericSecret(username=username, password=password)

    def secret_manager_auth(self, name: str) -> GenericSecret:
        """Resolve the auth material of a Secret Manager connection.

        Accepts ``generic`` credentials only (see ``_SECRET_MANAGER_AUTH_TYPES``);
        an ``ssh`` credential is rejected with ``CredentialUnusableError`` so a
        device password can never be sent to a connection's ``addr``/``site_url``.
        """
        match = self._match_by_name(name, _SECRET_MANAGER_AUTH_TYPES, "'generic'")
        username, password = self._decrypt_password(
            match, name, "has no decryptable password"
        )
        return GenericSecret(username=username, password=password)
```

### 1.2 `services/secret_manager/config.py` — use the restricted resolver

**Before**

```python
    auth_id = ""
    auth_secret = ""
    credential_name = connection.get("credential_name")
    if credential_name:
        # Background/system-scoped, like git auth — global credentials only.
        try:
            secret = CredentialManager(db).generic(credential_name)
        except ValueError as exc:
            raise ValueError(
                f"Secret manager connection '{connection['name']}': {exc}"
            ) from exc
        auth_id = secret.username or ""
        auth_secret = secret.password
```

**After**

```python
    auth_id = ""
    auth_secret = ""
    credential_name = connection.get("credential_name")
    if credential_name:
        # Background/system-scoped, like git auth — global credentials only,
        # and `generic` type only (SM2: never a device SSH credential).
        try:
            secret = CredentialManager(db).secret_manager_auth(credential_name)
        except ValueError as exc:
            raise ValueError(
                f"Secret manager connection '{connection['name']}': {exc}"
            ) from exc
        auth_id = secret.username or ""
        auth_secret = secret.password
```

### 1.3 `services/secret_manager/transport_policy.py` — new module (one place for the URL/TLS rules)

**After** (new file)

```python
"""Transport policy for Secret Manager connections (SM2).

One function, called from ``SecretManagerConnectionService`` on create/update
(``resolve_dns=True``) and from both client adapters at construction
(``resolve_dns=False`` -- rows that predate the check, and no DNS on the
worker hot path). Mirrors ``core/production_guards`` for ``VAULT_ADDR`` /
``VAULT_VERIFY_SSL`` (V1), but per row, because a connection is a DB record,
not an environment variable.
"""

from __future__ import annotations

from urllib.parse import urlparse

from core.config import settings
from core.safe_urls import UnsafeURLError, validate_outbound_http_url

# Which backend_config key carries the base URL for each backend.
URL_KEY_BY_BACKEND: dict[str, str] = {"openbao": "addr", "infisical": "site_url"}


def validate_connection_transport(
    *,
    backend: str,
    backend_config: dict,
    verify_ssl: bool,
    resolve_dns: bool,
) -> str:
    """Return the normalized base URL or raise ``ValueError``.

    - The URL must satisfy ``validate_outbound_http_url`` (no link-local /
      metadata / loopback-unless-allowed targets, no userinfo).
    - Outside ``development`` the scheme must be ``https`` and
      ``verify_ssl`` must be ``True``.
    """
    url_key = URL_KEY_BY_BACKEND.get(backend)
    if url_key is None:
        raise ValueError(f"Unknown secret manager backend: {backend!r}")
    raw_url = str(backend_config.get(url_key) or "").strip()
    try:
        safe_url = validate_outbound_http_url(raw_url, resolve_dns=resolve_dns)
    except UnsafeURLError as exc:
        raise ValueError(f"backend_config.{url_key}: {exc}") from exc

    if settings.environment == "development":
        return safe_url

    if urlparse(safe_url).scheme.lower() != "https":
        raise ValueError(
            f"backend_config.{url_key} must use https outside development"
        )
    if not verify_ssl:
        raise ValueError(
            "verify_ssl=false is not allowed outside development; "
            "use a CA-signed certificate or the development environment"
        )
    return safe_url
```

### 1.4 `services/secret_manager/connection_service.py` — enforce on create and update

**Before**

```python
from core.models import SecretManagerConnection
from repositories import SecretManagerConnectionRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_VALID_BACKENDS = frozenset({"openbao", "infisical"})
_REQUIRED_BACKEND_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "openbao": ("addr", "mount"),
    "infisical": ("site_url", "project_id", "environment"),
}


def _validate_backend_config(backend: str, backend_config: dict[str, Any]) -> None:
    if backend not in _VALID_BACKENDS:
        raise ValueError(f"Unknown secret manager backend: {backend!r}")
    required = _REQUIRED_BACKEND_CONFIG_KEYS[backend]
    missing = [key for key in required if not str(backend_config.get(key) or "").strip()]
    if missing:
        raise ValueError(
            f"backend_config for '{backend}' is missing required field(s): {', '.join(missing)}"
        )
```

```python
            backend = str(data["backend"])
            backend_config = dict(data.get("backend_config") or {})
            _validate_backend_config(backend, backend_config)

            new_connection = self._repo.create(
                db=self._db,
                name=data["name"],
                backend=backend,
                credential_name=data.get("credential_name"),
                verify_ssl=data.get("verify_ssl", True),
```

```python
            # Validate the resulting backend+backend_config together, whichever
            # (or neither) of the two fields actually changed.
            if "backend" in update_kwargs or "backend_config" in update_kwargs:
                current = self._repo.get_by_id(connection_id, db=self._db)
                if current is None:
                    raise ValueError(f"Connection {connection_id} not found")
                backend = str(update_kwargs.get("backend", current.backend))
                backend_config = dict(
                    update_kwargs.get("backend_config", current.backend_config or {})
                )
                _validate_backend_config(backend, backend_config)
```

**After**

```python
from core.models import SecretManagerConnection
from repositories import SecretManagerConnectionRepository
from services.secret_manager.transport_policy import validate_connection_transport

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_VALID_BACKENDS = frozenset({"openbao", "infisical"})
_REQUIRED_BACKEND_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "openbao": ("addr", "mount"),
    "infisical": ("site_url", "project_id", "environment"),
}
_TRANSPORT_FIELDS = frozenset({"backend", "backend_config", "verify_ssl"})


def _validate_backend_config(backend: str, backend_config: dict[str, Any]) -> None:
    if backend not in _VALID_BACKENDS:
        raise ValueError(f"Unknown secret manager backend: {backend!r}")
    required = _REQUIRED_BACKEND_CONFIG_KEYS[backend]
    missing = [key for key in required if not str(backend_config.get(key) or "").strip()]
    if missing:
        raise ValueError(
            f"backend_config for '{backend}' is missing required field(s): {', '.join(missing)}"
        )


def _validate_connection(
    backend: str, backend_config: dict[str, Any], verify_ssl: bool
) -> dict[str, Any]:
    """Shape check + transport policy (SM2). Returns backend_config with the
    URL field normalized by ``validate_outbound_http_url``."""
    _validate_backend_config(backend, backend_config)
    safe_url = validate_connection_transport(
        backend=backend,
        backend_config=backend_config,
        verify_ssl=verify_ssl,
        resolve_dns=True,
    )
    url_key = "addr" if backend == "openbao" else "site_url"
    return {**backend_config, url_key: safe_url}
```

```python
            backend = str(data["backend"])
            verify_ssl = bool(data.get("verify_ssl", True))
            backend_config = _validate_connection(
                backend, dict(data.get("backend_config") or {}), verify_ssl
            )

            new_connection = self._repo.create(
                db=self._db,
                name=data["name"],
                backend=backend,
                credential_name=data.get("credential_name"),
                verify_ssl=verify_ssl,
```

```python
            # Validate the resulting backend+backend_config+verify_ssl together,
            # whichever (or none) of the three actually changed (SM2).
            if _TRANSPORT_FIELDS & update_kwargs.keys():
                current = self._repo.get_by_id(connection_id, db=self._db)
                if current is None:
                    raise ValueError(f"Connection {connection_id} not found")
                backend = str(update_kwargs.get("backend", current.backend))
                backend_config = dict(
                    update_kwargs.get("backend_config", current.backend_config or {})
                )
                verify_ssl = bool(update_kwargs.get("verify_ssl", current.verify_ssl))
                update_kwargs["backend_config"] = _validate_connection(
                    backend, backend_config, verify_ssl
                )
```

### 1.5 `services/secret_manager/openbao_client.py` — re-check at construction

**Before**

```python
from services.secret_manager.client import SecretVersionInfo
from services.secret_manager.config import SecretManagerConnectionConfig
from services.secret_manager.exceptions import (
    SecretManagerConfigError,
    SecretManagerUnavailableError,
)
from services.vault.client import OpenBaoService
```

```python
def _build_vault_config(cfg: SecretManagerConnectionConfig) -> VaultConfig:
    addr = str(cfg.backend_config.get("addr") or "").strip()
    mount = str(cfg.backend_config.get("mount") or "").strip()
    if not addr or not mount:
        raise SecretManagerConfigError(
            f"OpenBao connection '{cfg.name}' needs both 'addr' and 'mount' in backend_config"
        )
```

**After**

```python
from services.secret_manager.client import SecretVersionInfo
from services.secret_manager.config import SecretManagerConnectionConfig
from services.secret_manager.exceptions import (
    SecretManagerConfigError,
    SecretManagerUnavailableError,
)
from services.secret_manager.transport_policy import validate_connection_transport
from services.vault.client import OpenBaoService
```

```python
def _build_vault_config(cfg: SecretManagerConnectionConfig) -> VaultConfig:
    mount = str(cfg.backend_config.get("mount") or "").strip()
    try:
        # Rows can predate the CRUD-time check; re-validate without DNS (SM2).
        addr = validate_connection_transport(
            backend="openbao",
            backend_config=cfg.backend_config,
            verify_ssl=cfg.verify_ssl,
            resolve_dns=False,
        )
    except ValueError as exc:
        raise SecretManagerConfigError(f"OpenBao connection '{cfg.name}': {exc}") from exc
    if not mount:
        raise SecretManagerConfigError(
            f"OpenBao connection '{cfg.name}' needs 'mount' in backend_config"
        )
```

### 1.6 `services/secret_manager/infisical_client.py` — re-check at construction

**Before**

```python
from core.ssl_config import create_verified_ssl_context
from services.secret_manager.client import SecretVersionInfo
from services.secret_manager.config import SecretManagerConnectionConfig
from services.secret_manager.exceptions import (
```

```python
    def __init__(self, cfg: SecretManagerConnectionConfig) -> None:
        self._name = cfg.name
        site_url = str(cfg.backend_config.get("site_url") or "").strip()
        project_id = str(cfg.backend_config.get("project_id") or "").strip()
        environment = str(cfg.backend_config.get("environment") or "").strip()
        if not site_url or not project_id or not environment:
            raise SecretManagerConfigError(
                f"Infisical connection '{cfg.name}' needs 'site_url', 'project_id', "
                "and 'environment' in backend_config"
            )
```

**After**

```python
from core.ssl_config import create_verified_ssl_context
from services.secret_manager.client import SecretVersionInfo
from services.secret_manager.config import SecretManagerConnectionConfig
from services.secret_manager.transport_policy import validate_connection_transport
from services.secret_manager.exceptions import (
```

```python
    def __init__(self, cfg: SecretManagerConnectionConfig) -> None:
        self._name = cfg.name
        project_id = str(cfg.backend_config.get("project_id") or "").strip()
        environment = str(cfg.backend_config.get("environment") or "").strip()
        try:
            # Rows can predate the CRUD-time check; re-validate without DNS (SM2).
            site_url = validate_connection_transport(
                backend="infisical",
                backend_config=cfg.backend_config,
                verify_ssl=cfg.verify_ssl,
                resolve_dns=False,
            )
        except ValueError as exc:
            raise SecretManagerConfigError(
                f"Infisical connection '{cfg.name}': {exc}"
            ) from exc
        if not project_id or not environment:
            raise SecretManagerConfigError(
                f"Infisical connection '{cfg.name}' needs 'project_id' and 'environment' "
                "in backend_config"
            )
```

### 1.7 `services/auth/rbac_service.py` — protect `secret_manager.*` (P3)

**Before**

```python
# Permissions on these resources let a holder change who can do what; only
# admins may hand them out or take them away (policy P3).
PROTECTED_RESOURCES: tuple[str, ...] = ("rbac.", "users", "system.")
```

**After**

```python
# Permissions on these resources let a holder change who can do what, or
# read secret material by other means (secret_manager.connections:write can
# point a connection's auth credential at an arbitrary host -- SM2); only
# admins may hand them out or take them away (policy P3).
PROTECTED_RESOURCES: tuple[str, ...] = ("rbac.", "users", "system.", "secret_manager.")
```

### 1.8 `models/secret_manager.py` — document the rule on the request model

**Before**

```python
    credential_name: str | None = Field(
        None,
        description="Name of the stored credential holding this connection's own auth material",
    )
    verify_ssl: bool = Field(default=True, description="Verify TLS certificates")
```

**After**

```python
    credential_name: str | None = Field(
        None,
        max_length=255,
        description=(
            "Name of a global 'generic' credential holding this connection's own auth "
            "material (username = role_id / client_id, password = secret_id / client_secret). "
            "SSH credentials are rejected."
        ),
    )
    verify_ssl: bool = Field(
        default=True,
        description="Verify TLS certificates (must be true outside development)",
    )
```

### 1.9 Docs

`CLAUDE.md` → "RBAC Grant Policy" table, P3 row:

**Before**

```
| P3 | Any grant, override, or removal touching `rbac.*`, `users`, or `system.*` requires `admin`. |
```

**After**

```
| P3 | Any grant, override, or removal touching `rbac.*`, `users`, `system.*`, or `secret_manager.*` requires `admin`. |
```

`doc/SECRET_MANAGER_INTEGRATION.md` → "Data model" paragraph on `credential_name`:

**Before**

```
**`credential_name`** resolves this *connection's own* auth material via the
existing `CredentialManager` facade — `CredentialManager(db).generic(name)`,
a `generic`-type credential holding the OpenBao AppRole `secret_id` /
Infisical `client_secret` as its password field, and `role_id`/`client_id`
as its username. Reuses the existing credential-resolution seam (global-only,
background/system-scoped — no `acting_user_id`) instead of inventing a third
way to store "a secret needed to reach a secret store."
```

**After**

```
**`credential_name`** resolves this *connection's own* auth material via the
existing `CredentialManager` facade — `CredentialManager(db).secret_manager_auth(name)`,
which accepts a **`generic`-type credential only** (an `ssh` credential is
rejected, so a device password can never be sent to a connection's URL)
holding the OpenBao AppRole `secret_id` / Infisical `client_secret` as its
password field, and `role_id`/`client_id` as its username. Reuses the
existing credential-resolution seam (global-only, background/system-scoped —
no `acting_user_id`) instead of inventing a third way to store "a secret
needed to reach a secret store."

**Transport policy.** `addr` / `site_url` must pass
`core.safe_urls.validate_outbound_http_url` (no link-local, metadata, or —
unless `ALLOW_LOOPBACK_SOURCE_URLS=true` — loopback targets). Outside
`ENV=development` the URL must be `https://` and `verify_ssl` must stay
`true`, mirroring `VAULT_ADDR`/`VAULT_VERIFY_SSL` for the credential vault.
Enforced on create/update (`SecretManagerConnectionService`) and again when a
client is built (`services/secret_manager/transport_policy.py`).
`secret_manager.connections:*` is a protected permission (P3): only an admin
may grant it.
```

### 1.10 Tests

`tests/unit/test_secret_manager_connection_service.py` — the suite hits
`validate_outbound_http_url` with `resolve_dns=True`; patch it in `setUp` like the pyATS suite
does and add the new cases.

**Before**

```python
class SecretManagerConnectionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        SecretManagerConnection.metadata.create_all(
            engine, tables=[SecretManagerConnection.__table__]
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.service = SecretManagerConnectionService(self.db)
```

**After**

```python
class SecretManagerConnectionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        SecretManagerConnection.metadata.create_all(
            engine, tables=[SecretManagerConnection.__table__]
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.service = SecretManagerConnectionService(self.db)

        # No real DNS in unit tests: keep the URL as-is unless it is one of
        # the cases the transport-policy tests below exercise explicitly.
        validate_patcher = patch(
            "services.secret_manager.transport_policy.validate_outbound_http_url",
            side_effect=lambda url, *, resolve_dns=True: url.rstrip("/"),
        )
        self.mock_validate = validate_patcher.start()
        self.addCleanup(validate_patcher.stop)
        env_patcher = patch(
            "services.secret_manager.transport_policy.settings.environment", "development"
        )
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

    # ---- SM2: transport policy -------------------------------------------
    def test_create_rejects_unsafe_url(self) -> None:
        from core.safe_urls import UnsafeURLError

        self.mock_validate.side_effect = UnsafeURLError("URL resolves to link-local address")
        with self.assertRaisesRegex(ValueError, "backend_config.addr"):
            self._create(backend_config={"addr": "http://169.254.169.254", "mount": "m"})

    def test_create_outside_development_requires_https(self) -> None:
        with patch(
            "services.secret_manager.transport_policy.settings.environment", "production"
        ):
            with self.assertRaisesRegex(ValueError, "must use https"):
                self._create(backend_config={"addr": "http://vault.internal:8200", "mount": "m"})

    def test_create_outside_development_requires_verify_ssl(self) -> None:
        with patch(
            "services.secret_manager.transport_policy.settings.environment", "production"
        ):
            with self.assertRaisesRegex(ValueError, "verify_ssl=false"):
                self._create(verify_ssl=False)

    def test_create_in_development_allows_http_and_no_verify(self) -> None:
        connection_id = self._create(
            verify_ssl=False,
            backend_config={"addr": "http://127.0.0.1:8200", "mount": "m"},
        )
        self.assertTrue(self.service.get_connection(connection_id)["backend_config"]["addr"])

    def test_update_verify_ssl_alone_is_policy_checked(self) -> None:
        connection_id = self._create()
        with patch(
            "services.secret_manager.transport_policy.settings.environment", "production"
        ):
            with self.assertRaisesRegex(ValueError, "verify_ssl=false"):
                self.service.update_connection(connection_id, {"verify_ssl": False})

    def test_infisical_site_url_is_policy_checked(self) -> None:
        from core.safe_urls import UnsafeURLError

        self.mock_validate.side_effect = UnsafeURLError("URL host is not allowed")
        with self.assertRaisesRegex(ValueError, "backend_config.site_url"):
            self.service.create_connection(
                {**_INFISICAL_BASE, "backend_config": {**_INFISICAL_BASE["backend_config"],
                                                       "site_url": "http://metadata.google.internal"}}
            )
```

`tests/unit/test_credential_manager.py` (existing file for `CredentialManager`; add to it):

```python
    def test_secret_manager_auth_rejects_ssh_credential(self) -> None:
        self.svc.list_credentials.return_value = [
            {"id": 7, "name": "fleet-ssh", "type": "ssh", "visibility": "global",
             "status": "active", "username": "admin"}
        ]
        with self.assertRaisesRegex(CredentialUnusableError, "must be type 'generic'"):
            CredentialManager(self.db).secret_manager_auth("fleet-ssh")
        self.svc.get_decrypted_password.assert_not_called()

    def test_secret_manager_auth_accepts_generic_credential(self) -> None:
        self.svc.list_credentials.return_value = [
            {"id": 8, "name": "bao-approle", "type": "generic", "visibility": "global",
             "status": "active", "username": "role-id"}
        ]
        self.svc.get_decrypted_password.return_value = "secret-id"
        secret = CredentialManager(self.db).secret_manager_auth("bao-approle")
        self.assertEqual((secret.username, secret.password), ("role-id", "secret-id"))
```

`tests/unit/test_rbac_elevation.py` — extend the existing protected-permission test set with
one case: a non-admin `users:write` holder cannot grant `secret_manager.connections:write` via
override or via a custom role (same shape as the existing
`users_write_holder_cannot_override_protected_permission_for_self`), and an admin can.

`tests/unit/test_secret_manager_openbao_client.py` / `test_secret_manager_infisical_client.py`
(new; full content in §3.4) each include one constructor test: a row with
`verify_ssl=False` under `environment="production"` raises `SecretManagerConfigError`.

Done when: `pytest tests/unit -k "secret_manager or credential_manager or rbac_elevation"` is
green; `ruff check services/secret_manager services/credentials/manager.py services/auth/rbac_service.py`.

---

## 2. B1 — outbound policy for Batfish sources

### 2.1 `services/batfish/source_config_service.py`

**Before**

```python
from sqlalchemy.orm import Session

from repositories.settings_repository import SettingsRepository
from services.batfish.common.exceptions import BatfishValidationError
from services.batfish.credentials import BatfishConnection
from services.settings.source_keys import build_source_key, ensure_value_source_id
```

```python
def _validate_host(host: str) -> str:
    normalized = (host or "").strip()
    if not normalized:
        raise BatfishValidationError("Batfish host is required")
    if len(normalized) > 255:
        raise BatfishValidationError("Batfish host must be 255 characters or fewer")
    return normalized
```

```python
        safe_host = _validate_host(host)

        value = ensure_value_source_id(
            {"host": safe_host, "port": port},
            source_type="batfish",
            source_id=source_id,
        )
```

```python
        updated_value = dict(setting.value)
        if host is not None:
            updated_value["host"] = _validate_host(host)
        if port is not None:
            updated_value["port"] = port

        updated = self._settings.update(setting, {"value": updated_value})
        return self._to_public(updated.value)
```

```python
    def resolve_connection(self, source_id: str) -> BatfishConnection:
        setting = self._get_setting_or_raise(source_id)
        value = setting.value
        return BatfishConnection(host=value["host"], port=int(value.get("port", 9996)))

    def resolve_inline_connection(self, *, host: str, port: int) -> BatfishConnection:
        """Build a connection from unsaved dialog values (no persisted source yet)."""
        return BatfishConnection(host=_validate_host(host), port=int(port))
```

**After**

```python
from sqlalchemy.orm import Session

from core.safe_urls import UnsafeURLError, validate_outbound_http_url
from repositories.settings_repository import SettingsRepository
from services.batfish.common.exceptions import BatfishValidationError
from services.batfish.credentials import BatfishConnection
from services.settings.source_keys import build_source_key, ensure_value_source_id
```

```python
def _validate_host(host: str) -> str:
    normalized = (host or "").strip()
    if not normalized:
        raise BatfishValidationError("Batfish host is required")
    if len(normalized) > 255:
        raise BatfishValidationError("Batfish host must be 255 characters or fewer")
    return normalized


def _validate_target(host: str, port: int, *, resolve_dns: bool) -> str:
    """Apply the outbound HTTP policy to the coordinator target (B1).

    pybatfish turns ``host``/``port`` into ``http://{host}:{port}/v2/...``
    (``Session.get_base_url2``) and speaks unauthenticated HTTP to it, so the
    pair is subject to the same ``validate_outbound_http_url`` policy as every
    other source URL: no link-local / metadata targets, and loopback only when
    ``ALLOW_LOOPBACK_SOURCE_URLS=true`` (native-host development against
    ``127.0.0.1``). ``resolve_dns=True`` at CRUD/test time; ``False`` when a
    step resolves a stored source (no DNS on the worker hot path).
    """
    safe_host = _validate_host(host)
    try:
        validate_outbound_http_url(f"http://{safe_host}:{int(port)}", resolve_dns=resolve_dns)
    except UnsafeURLError as exc:
        raise BatfishValidationError(f"Batfish host is not allowed: {exc}") from exc
    return safe_host
```

```python
        safe_host = _validate_target(host, port, resolve_dns=True)

        value = ensure_value_source_id(
            {"host": safe_host, "port": port},
            source_type="batfish",
            source_id=source_id,
        )
```

```python
        updated_value = dict(setting.value)
        new_host = host if host is not None else str(updated_value.get("host") or "")
        new_port = port if port is not None else int(updated_value.get("port", 9996))
        # Re-validate the resulting pair whichever of the two changed (B1).
        updated_value["host"] = _validate_target(new_host, new_port, resolve_dns=True)
        updated_value["port"] = new_port

        updated = self._settings.update(setting, {"value": updated_value})
        return self._to_public(updated.value)
```

```python
    def resolve_connection(self, source_id: str) -> BatfishConnection:
        setting = self._get_setting_or_raise(source_id)
        value = setting.value
        port = int(value.get("port", 9996))
        # Rows can predate the policy; re-check without DNS (B1).
        host = _validate_target(str(value["host"]), port, resolve_dns=False)
        return BatfishConnection(host=host, port=port)

    def resolve_inline_connection(self, *, host: str, port: int) -> BatfishConnection:
        """Build a connection from unsaved dialog values (no persisted source yet)."""
        return BatfishConnection(
            host=_validate_target(host, int(port), resolve_dns=True), port=int(port)
        )
```

### 2.2 `routers/sources/batfish/ops.py` — keep DNS off the event loop

**Before**

```python
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
```

```python
    connection = _resolve_connection(request, config)
    batfish = service_factory.get_batfish_app_service()
```

**After**

```python
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
```

```python
    # _resolve_connection now does a DNS lookup (B1) -- off the event loop.
    connection = await asyncio.to_thread(_resolve_connection, request, config)
    batfish = service_factory.get_batfish_app_service()
```

### 2.3 Docs and env

`doc/BATFISH_INTEGRATION.md` → "Open items / verify during hardening":

**Before**

```
- **RESOLVED during implementation**: no `validate_outbound_http_url` call
  was needed. `BatfishSourceConfigService` does plain non-empty/length
  validation on `host` (`_validate_host`) rather than routing it through the
  URL/loopback-allowlist path every other source uses — `host` is a bare
  hostname/IP, not a URL, so that path doesn't apply. This also means the
  loopback case (native-backend dev pointing at `127.0.0.1`) needs no
  `ALLOW_LOOPBACK_SOURCE_URLS` exception the way pyATS/OpenBao do — there's
  no URL-shaped value for that guard to reject in the first place.
```

**After**

```
- **RESOLVED (2026-09 hardening, B1): `host`/`port` go through
  `validate_outbound_http_url`.** The earlier claim that "host is a bare
  hostname, not a URL, so the policy doesn't apply" was wrong — pybatfish
  builds `http://{host}:{port}/v2/...` from it one line in
  (`Session.get_base_url2`). `BatfishSourceConfigService._validate_target`
  now applies the same policy as every other source (no link-local/metadata
  targets, loopback only with `ALLOW_LOOPBACK_SOURCE_URLS=true`) on create,
  update, inline test-connection, and again in `resolve_connection`. Native
  host development against `127.0.0.1` therefore needs
  `ALLOW_LOOPBACK_SOURCE_URLS=true` in `backend/.env`, exactly like
  pyATS/OpenBao.
```

`doc/BATFISH_INTEGRATION.md` → "Configuring a source", the paragraph starting
"**Which host to use depends on where the backend process itself runs**": replace the sentence
"The loopback case needs `ALLOW_LOOPBACK_SOURCE_URLS=true` in `backend/.env` if the source URL
validation path treats a bare hostname the same way … (see "Open items" below)." with
"The loopback case needs `ALLOW_LOOPBACK_SOURCE_URLS=true` in `backend/.env` (the host/port pair
is validated with `validate_outbound_http_url`, same as every other source)."

`docker/batfish/README.md` step 5:

**Before**

```
   - **Backend running natively on the host** (the CLAUDE.md dev workflow):
     `host=127.0.0.1`, ports `9996`/`9997` (published below).
```

**After**

```
   - **Backend running natively on the host** (the CLAUDE.md dev workflow):
     `host=127.0.0.1`, ports `9996`/`9997` (published below). Loopback
     targets are refused by the outbound-URL policy unless
     `ALLOW_LOOPBACK_SOURCE_URLS=true` is set in `backend/.env`.
```

`doc/SECURITY-NOTES.md` — append two sections (the Batfish doc promised the first "once this
ships"; the second records the SM2 posture):

```
## Batfish: raw device configurations are uploaded to the coordinator

`batfish-init-snapshot` writes every device's running-config (live mode) or
every matched file of a git repository (git mode) into a temp directory and
uploads it as a snapshot to the configured Batfish coordinator, which stores
it in its `/data` volume. Configs may contain enable secrets, SNMP
communities, or pre-shared keys if the collecting step did not scrub them.
**Accepted as-is**: this is the same trust boundary as the git-mirrored config
backups, and the coordinator has no authentication of its own — which is why
(a) `docker/batfish/docker-compose.yaml` binds its ports to `127.0.0.1` only,
and (b) a source's `host`/`port` must pass `validate_outbound_http_url`
(`services/batfish/source_config_service.py::_validate_target`), so a
`sources.batfish:write` holder cannot point the upload at an arbitrary host.
Ad-hoc query results (routing tables, ACL verdicts, extracted facts) are gated
by the separate `sources.batfish:query` permission, which the read-only
`viewer` role does not hold.

## Secret Manager connections send their own auth material to a configured URL

A Secret Manager connection's `credential_name` (AppRole `role_id`/`secret_id`
or Infisical `client_id`/`client_secret`) is POSTed to the connection's
`addr`/`site_url` on every login. **Mitigated, not accepted**: the URL must
pass `validate_outbound_http_url`, must be `https` with `verify_ssl=true`
outside development, the credential must be of type `generic` (an `ssh`
device credential is rejected), and `secret_manager.connections:*` is a
protected permission only an admin can grant (P3). See
`doc/SECRET_MANAGER_INTEGRATION.md` → "Transport policy".
```

### 2.4 Tests

`tests/unit/test_batfish_source_config_service.py`:

**Before**

```python
class BatfishSourceConfigServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        settings_patcher = patch("services.batfish.source_config_service.SettingsRepository")
        self.mock_settings_cls = settings_patcher.start()
        self.addCleanup(settings_patcher.stop)
        self.mock_settings = self.mock_settings_cls.return_value

        self.service = BatfishSourceConfigService(db=MagicMock())
```

**After**

```python
class BatfishSourceConfigServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        settings_patcher = patch("services.batfish.source_config_service.SettingsRepository")
        self.mock_settings_cls = settings_patcher.start()
        self.addCleanup(settings_patcher.stop)
        self.mock_settings = self.mock_settings_cls.return_value

        # No real DNS in unit tests; the policy tests below override side_effect.
        validate_patcher = patch(
            "services.batfish.source_config_service.validate_outbound_http_url",
            side_effect=lambda url, *, resolve_dns=True: url,
        )
        self.mock_validate = validate_patcher.start()
        self.addCleanup(validate_patcher.stop)

        self.service = BatfishSourceConfigService(db=MagicMock())

    # ---- B1: outbound policy ----------------------------------------------
    def test_create_source_applies_outbound_policy_with_dns(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        self.mock_settings.create.return_value = _setting(
            "sources.batfish.lab", {"host": "batfish", "port": 9996, "source_id": "lab"}
        )
        self.service.create_source(source_id="lab", host="batfish", port=9996)
        self.mock_validate.assert_called_once_with("http://batfish:9996", resolve_dns=True)

    def test_create_source_rejects_disallowed_target(self) -> None:
        from core.safe_urls import UnsafeURLError

        self.mock_settings.get_by_key.return_value = None
        self.mock_validate.side_effect = UnsafeURLError("URL resolves to link-local address")
        with self.assertRaisesRegex(BatfishValidationError, "not allowed"):
            self.service.create_source(source_id="lab", host="169.254.169.254", port=80)
        self.mock_settings.create.assert_not_called()

    def test_update_port_only_revalidates_pair(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.batfish.lab", {"host": "batfish", "port": 9996, "source_id": "lab"}
        )
        self.mock_settings.update.return_value = _setting(
            "sources.batfish.lab", {"host": "batfish", "port": 9999, "source_id": "lab"}
        )
        self.service.update_source("lab", port=9999)
        self.mock_validate.assert_called_once_with("http://batfish:9999", resolve_dns=True)

    def test_resolve_connection_rechecks_without_dns(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.batfish.lab", {"host": "batfish", "port": 9996, "source_id": "lab"}
        )
        connection = self.service.resolve_connection("lab")
        self.assertEqual((connection.host, connection.port), ("batfish", 9996))
        self.mock_validate.assert_called_once_with("http://batfish:9996", resolve_dns=False)

    def test_resolve_connection_refuses_legacy_disallowed_row(self) -> None:
        from core.safe_urls import UnsafeURLError

        self.mock_settings.get_by_key.return_value = _setting(
            "sources.batfish.lab",
            {"host": "metadata.google.internal", "port": 80, "source_id": "lab"},
        )
        self.mock_validate.side_effect = UnsafeURLError("URL host is not allowed")
        with self.assertRaises(BatfishValidationError):
            self.service.resolve_connection("lab")

    def test_inline_connection_applies_policy_with_dns(self) -> None:
        self.service.resolve_inline_connection(host="10.0.0.5", port=9996)
        self.mock_validate.assert_called_once_with("http://10.0.0.5:9996", resolve_dns=True)
```

`tests/unit/test_batfish_router_auth.py` — add one test on `POST /sources/batfish/test-connection`
with inline `{host: "169.254.169.254", port: 80}` where the config service dependency is a
`MagicMock` whose `resolve_inline_connection` raises `BatfishValidationError("Batfish host is
not allowed: …")`; assert 400 and that `check_health` was never called.

Any existing test in `test_batfish_context_ref_resolver.py`, `test_batfish_preview_service.py`,
`test_batfish_*_executor.py`, or `test_batfish_discovery_router.py` that uses a **real**
`BatfishSourceConfigService` (not a mock) must patch
`services.batfish.source_config_service.validate_outbound_http_url` as above; the ones that
mock `resolve_connection` are unaffected.

Done when: `pytest tests/unit -k batfish` green; `ruff check services/batfish routers/sources/batfish`.

---

## 3. SM1 — connection test proves authentication

### 3.1 `services/vault/client.py` — expose health

**Before**

```python
class OpenBaoService:
    def __init__(self, cfg: VaultConfig) -> None:
        self._cfg = cfg
        self._client: httpx.Client | None = None
        self._tokens = VaultTokenManager(cfg, build_auth_strategy(cfg))
        self._cache = InProcessTTLCache(ttl_seconds=cfg.cache_ttl_seconds)
        self._renew_task: asyncio.Task | None = None
        self._healthy = False

    # ------------------------------------------------------------------ lifecycle
```

**After**

```python
class OpenBaoService:
    def __init__(self, cfg: VaultConfig) -> None:
        self._cfg = cfg
        self._client: httpx.Client | None = None
        self._tokens = VaultTokenManager(cfg, build_auth_strategy(cfg))
        self._cache = InProcessTTLCache(ttl_seconds=cfg.cache_ttl_seconds)
        self._renew_task: asyncio.Task | None = None
        self._healthy = False

    @property
    def healthy(self) -> bool:
        """True once a login (startup or renew) has succeeded and no renew has
        failed since. ``startup()`` soft-fails by design (the app must boot
        without OpenBao); callers that need a hard answer -- the Secret
        Manager adapter's ``ensure_started`` (SM1) -- read this instead."""
        return self._healthy

    # ------------------------------------------------------------------ lifecycle
```

### 3.2 `services/secret_manager/openbao_client.py` — strict `ensure_started`

**Before**

```python
from services.secret_manager.exceptions import (
    SecretManagerConfigError,
    SecretManagerUnavailableError,
)
```

```python
    async def ensure_started(self) -> None:
        await self._service.startup()
```

**After**

```python
from services.secret_manager.exceptions import (
    SecretManagerAuthError,
    SecretManagerConfigError,
    SecretManagerUnavailableError,
)
```

```python
    async def ensure_started(self) -> None:
        """Start the underlying client and *prove* the AppRole login worked.

        ``OpenBaoService.startup()`` deliberately swallows a failed login
        (the credential vault must not take the app down at boot); for a
        Secret Manager connection that would make ``POST …/test`` report
        success on a wrong secret_id (SM1). Shut the service down again on
        failure so its renew task does not leak, then raise.
        """
        await self._service.startup()
        if not self._service.healthy:
            await self._service.shutdown()
            raise SecretManagerAuthError(
                f"OpenBao connection '{self._name}': AppRole login failed -- check addr, "
                "mount, namespace, and the credential's role_id/secret_id"
            )
```

### 3.3 `services/secret_manager/infisical_client.py` — login in `ensure_started`

**Before**

```python
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
```

```python
    async def ensure_started(self) -> None:
        # No background renew loop — see _InfisicalTokenManager docstring.
        # Nothing to await; kept so the registry can treat every adapter
        # uniformly (await ensure_started() once before first use).
        return None
```

**After**

```python
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
```

```python
    async def ensure_started(self) -> None:
        """Perform the Universal Auth login now, off the event loop.

        There is no background renew loop (see _InfisicalTokenManager), but a
        connection must prove it can authenticate before the registry caches
        it -- otherwise ``POST …/test`` reports success without ever
        contacting Infisical (SM1). Raises ``SecretManagerConfigError`` /
        ``SecretManagerAuthError`` / ``SecretManagerUnavailableError``.
        """
        await asyncio.to_thread(self._tokens.current, self._client)
```

### 3.4 Tests — new files (the four 0 % modules)

`tests/unit/test_secret_manager_openbao_client.py` (new):

```python
"""OpenBaoSecretManagerClient: construction policy, strict ensure_started,
field merge semantics, error mapping. OpenBaoService is mocked -- its own
wire behaviour is covered by test_vault_client.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.secret_manager.config import SecretManagerConnectionConfig
from services.secret_manager.exceptions import (
    SecretManagerAuthError,
    SecretManagerConfigError,
    SecretManagerUnavailableError,
)
from services.vault.exceptions import VaultSecretNotFoundError, VaultUnavailableError


def _cfg(**overrides) -> SecretManagerConnectionConfig:
    base = dict(
        id=1,
        name="net",
        backend="openbao",
        verify_ssl=True,
        backend_config={"addr": "https://vault.internal:8200", "mount": "manus-network"},
        auth_id="role-id",
        auth_secret="secret-id",
    )
    return SecretManagerConnectionConfig(**{**base, **overrides})


class OpenBaoSecretManagerClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        env = patch("services.secret_manager.transport_policy.settings.environment", "development")
        env.start()
        self.addCleanup(env.stop)
        svc_patcher = patch("services.secret_manager.openbao_client.OpenBaoService")
        self.svc_cls = svc_patcher.start()
        self.addCleanup(svc_patcher.stop)
        self.svc = self.svc_cls.return_value
        self.svc.startup = AsyncMock()
        self.svc.shutdown = AsyncMock()
        from services.secret_manager.openbao_client import OpenBaoSecretManagerClient

        self.cls = OpenBaoSecretManagerClient

    # ---- construction -------------------------------------------------------
    def test_missing_auth_material_is_config_error(self) -> None:
        with self.assertRaises(SecretManagerConfigError):
            self.cls(_cfg(auth_secret=""))

    def test_verify_ssl_false_outside_development_is_config_error(self) -> None:
        with patch("services.secret_manager.transport_policy.settings.environment", "production"):
            with self.assertRaisesRegex(SecretManagerConfigError, "verify_ssl=false"):
                self.cls(_cfg(verify_ssl=False))

    def test_http_addr_outside_development_is_config_error(self) -> None:
        with patch("services.secret_manager.transport_policy.settings.environment", "production"):
            with self.assertRaisesRegex(SecretManagerConfigError, "must use https"):
                self.cls(_cfg(backend_config={"addr": "http://vault:8200", "mount": "m"}))

    # ---- ensure_started (SM1) -----------------------------------------------
    async def test_ensure_started_raises_when_login_failed(self) -> None:
        type(self.svc).healthy = property(lambda _self: False)
        client = self.cls(_cfg())
        with self.assertRaisesRegex(SecretManagerAuthError, "AppRole login failed"):
            await client.ensure_started()
        self.svc.shutdown.assert_awaited_once()

    async def test_ensure_started_ok_when_healthy(self) -> None:
        type(self.svc).healthy = property(lambda _self: True)
        client = self.cls(_cfg())
        await client.ensure_started()
        self.svc.shutdown.assert_not_awaited()

    # ---- field semantics ----------------------------------------------------
    def test_get_field_missing_path_returns_none(self) -> None:
        self.svc.read_kv.side_effect = VaultSecretNotFoundError("nope")
        self.assertIsNone(self.cls(_cfg()).get_field("network/r1/tacacs", "key"))

    def test_get_field_pinned_version_bypasses_cache(self) -> None:
        self.svc.read_kv.return_value = {"key": "old"}
        self.assertEqual(self.cls(_cfg()).get_field("p", "key", version=2), "old")
        self.svc.read_kv.assert_called_once_with("p", version=2)

    def test_set_field_merges_existing_fields(self) -> None:
        self.svc.read_kv.return_value = {"key": "old", "rotated_at": "t0"}
        self.svc.write_kv.return_value = 3
        version = self.cls(_cfg()).set_field("p", "key", "new")
        self.svc.write_kv.assert_called_once_with("p", {"key": "new", "rotated_at": "t0"})
        self.assertEqual(version, 3)

    def test_delete_last_field_deletes_path(self) -> None:
        self.svc.read_kv.return_value = {"key": "v"}
        self.cls(_cfg()).delete_field("p", "key")
        self.svc.delete_kv.assert_called_once_with("p")
        self.svc.write_kv.assert_not_called()

    def test_vault_unavailable_maps_to_unavailable(self) -> None:
        self.svc.read_kv.side_effect = VaultUnavailableError("down")
        with self.assertRaises(SecretManagerUnavailableError):
            self.cls(_cfg()).get_field("p", "key")

    def test_history_skips_destroyed_and_sorts_desc(self) -> None:
        self.svc.metadata_kv.return_value = {
            "versions": {"1": {"created_time": "a"}, "2": {"created_time": "b", "destroyed": True},
                         "3": {"created_time": "c"}}
        }
        history = self.cls(_cfg()).get_field_history("p", "key")
        self.assertEqual([h.version for h in history], [3, 1])
```

`tests/unit/test_secret_manager_infisical_client.py` (new):

```python
"""InfisicalSecretManagerClient wire shaping via httpx.MockTransport:
login, 401 retry-once, create-vs-update, 404 -> None, and the strict
ensure_started (SM1)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import httpx

from services.secret_manager.config import SecretManagerConnectionConfig
from services.secret_manager.exceptions import (
    SecretManagerAuthError,
    SecretManagerConfigError,
    SecretManagerPermissionError,
)


def _cfg(**overrides) -> SecretManagerConnectionConfig:
    base = dict(
        id=2,
        name="inf",
        backend="infisical",
        verify_ssl=True,
        backend_config={
            "site_url": "https://infisical.example",
            "project_id": "proj",
            "environment": "prod",
        },
        auth_id="client-id",
        auth_secret="client-secret",
    )
    return SecretManagerConnectionConfig(**{**base, **overrides})


class _Fake:
    """Scripted Infisical: records requests, answers per (method, path)."""

    def __init__(self, *, login_status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.login_status = login_status
        self.secrets: dict[str, str] = {}
        self.deny_next = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/v1/auth/universal-auth/login":
            if self.login_status != 200:
                return httpx.Response(self.login_status, json={})
            return httpx.Response(200, json={"accessToken": "tok", "expiresIn": 7200})
        if self.deny_next:
            self.deny_next -= 1
            return httpx.Response(401, json={})
        key = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            if key not in self.secrets:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"secret": {"secretValue": self.secrets[key]}})
        body = json.loads(request.content or b"{}")
        self.secrets[key] = body.get("secretValue", "")
        return httpx.Response(200, json={"secret": {"version": 1 if request.method == "POST" else 2}})


class InfisicalSecretManagerClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        env = patch("services.secret_manager.transport_policy.settings.environment", "development")
        env.start()
        self.addCleanup(env.stop)
        self.fake = _Fake()
        client_patcher = patch(
            "services.secret_manager.infisical_client.httpx.Client",
            side_effect=lambda **kw: httpx.Client(
                base_url=kw["base_url"], transport=httpx.MockTransport(self.fake.handler)
            ),
        )
        client_patcher.start()
        self.addCleanup(client_patcher.stop)
        from services.secret_manager.infisical_client import InfisicalSecretManagerClient

        self.cls = InfisicalSecretManagerClient

    def test_missing_project_is_config_error(self) -> None:
        with self.assertRaises(SecretManagerConfigError):
            self.cls(_cfg(backend_config={"site_url": "https://x", "environment": "prod"}))

    def test_verify_ssl_false_outside_development_is_config_error(self) -> None:
        with patch("services.secret_manager.transport_policy.settings.environment", "production"):
            with self.assertRaisesRegex(SecretManagerConfigError, "verify_ssl=false"):
                self.cls(_cfg(verify_ssl=False))

    # ---- ensure_started (SM1) -----------------------------------------------
    async def test_ensure_started_logs_in(self) -> None:
        await self.cls(_cfg()).ensure_started()
        self.assertEqual([r.url.path for r in self.fake.requests],
                         ["/api/v1/auth/universal-auth/login"])

    async def test_ensure_started_raises_on_bad_credentials(self) -> None:
        self.fake.login_status = 401
        with self.assertRaises(SecretManagerAuthError):
            await self.cls(_cfg()).ensure_started()

    async def test_ensure_started_raises_without_credentials(self) -> None:
        with self.assertRaises(SecretManagerConfigError):
            await self.cls(_cfg(auth_secret="")).ensure_started()

    # ---- wire shaping -------------------------------------------------------
    def test_get_field_404_returns_none(self) -> None:
        self.assertIsNone(self.cls(_cfg()).get_field("network/r1/tacacs", "key"))

    def test_set_field_creates_then_updates(self) -> None:
        client = self.cls(_cfg())
        self.assertEqual(client.set_field("p", "key", "v1"), 1)
        self.assertEqual(client.set_field("p", "key", "v2"), 2)
        methods = [r.method for r in self.fake.requests if r.url.path.endswith("/secrets/key")]
        self.assertEqual(methods, ["GET", "POST", "GET", "PATCH"])
        self.assertEqual(self.fake.secrets["key"], "v2")

    def test_401_triggers_relogin_and_one_retry(self) -> None:
        client = self.cls(_cfg())
        self.fake.secrets["key"] = "v"
        self.fake.deny_next = 1
        self.assertEqual(client.get_field("p", "key"), "v")
        logins = [r for r in self.fake.requests if r.url.path.endswith("/login")]
        self.assertEqual(len(logins), 2)

    def test_persistent_403_is_permission_error(self) -> None:
        client = self.cls(_cfg())
        self.fake.deny_next = 2
        with self.assertRaises(SecretManagerPermissionError):
            client.get_field("p", "key")

    def test_secret_path_is_query_param_and_field_is_path(self) -> None:
        self.cls(_cfg()).get_field("network/r1/tacacs", "key")
        get = [r for r in self.fake.requests if r.method == "GET"][0]
        self.assertTrue(get.url.path.endswith("/api/v4/secrets/key"))
        self.assertEqual(get.url.params["secretPath"], "network/r1/tacacs")
```

`tests/unit/test_secret_manager_router.py` (new):

```python
"""TestClient tests for routers/secret_manager.py: permission gating, 400/404
mapping, and the /test endpoint reporting *failure* on a failed login (SM1)."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import service_factory
from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_secret_manager_connection_service
from routers.secret_manager import router
from services.auth.rbac_service import RBACService
from services.secret_manager.exceptions import SecretManagerAuthError

_ROW = {
    "id": 1, "name": "net", "backend": "openbao", "credential_name": "bao",
    "verify_ssl": True, "is_active": True, "description": None,
    "backend_config": {"addr": "https://vault.internal:8200", "mount": "m"},
    "created_at": "2026-09-16T00:00:00+00:00", "updated_at": "2026-09-16T00:00:00+00:00",
}


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db
    return app


@pytest.fixture
def connection_service(app: FastAPI) -> MagicMock:
    svc = MagicMock()
    svc.get_connection.return_value = _ROW
    app.dependency_overrides[get_secret_manager_connection_service] = lambda: svc
    return svc


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    reg = MagicMock()
    reg.invalidate = AsyncMock()
    reg.get_or_create = AsyncMock()
    monkeypatch.setattr(service_factory, "get_secret_manager_registry", lambda: reg)
    return reg


def test_list_forbidden_without_permission(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: False)
    with TestClient(app) as client:
        response = client.get("/api/secret-manager/connections")
    assert response.status_code == 403
    assert "secret_manager.connections:read" in response.json()["detail"]


def test_create_maps_value_error_to_400(app: FastAPI, connection_service: MagicMock) -> None:
    connection_service.create_connection.side_effect = ValueError("backend_config.addr: bad")
    with TestClient(app) as client:
        response = client.post(
            "/api/secret-manager/connections",
            json={"name": "net", "backend": "openbao", "backend_config": {"addr": "x", "mount": "m"}},
        )
    assert response.status_code == 400
    assert "backend_config.addr" in response.json()["detail"]


def test_get_unknown_is_404(app: FastAPI, connection_service: MagicMock) -> None:
    connection_service.get_connection.return_value = None
    with TestClient(app) as client:
        response = client.get("/api/secret-manager/connections/99")
    assert response.status_code == 404


def test_test_endpoint_reports_auth_failure(
    app: FastAPI, connection_service: MagicMock, registry: MagicMock
) -> None:
    registry.get_or_create.side_effect = SecretManagerAuthError("AppRole login failed")
    with TestClient(app) as client:
        response = client.post("/api/secret-manager/connections/1/test")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert "AppRole login failed" in body["message"]
    registry.invalidate.assert_awaited_once_with(1)


def test_test_endpoint_reports_success_only_after_get_or_create(
    app: FastAPI, connection_service: MagicMock, registry: MagicMock
) -> None:
    with TestClient(app) as client:
        response = client.post("/api/secret-manager/connections/1/test")
    assert response.json() == {"success": True, "message": "Connected successfully"}
    registry.get_or_create.assert_awaited_once()


def test_update_invalidates_registry(
    app: FastAPI, connection_service: MagicMock, registry: MagicMock
) -> None:
    with TestClient(app) as client:
        response = client.put("/api/secret-manager/connections/1", json={"description": "x"})
    assert response.status_code == 200
    registry.invalidate.assert_awaited_once_with(1)
```

`tests/unit/test_secret_manager_registry.py` (new):

```python
"""SecretManagerClientRegistry: lazy build, no caching on failed
ensure_started (SM1), invalidate, unknown backend."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.secret_manager.config import SecretManagerConnectionConfig
from services.secret_manager.exceptions import SecretManagerAuthError, SecretManagerConfigError
from services.secret_manager.registry import SecretManagerClientRegistry


def _cfg(backend: str = "openbao") -> SecretManagerConnectionConfig:
    return SecretManagerConnectionConfig(
        id=1, name="net", backend=backend, verify_ssl=True, backend_config={},
        auth_id="a", auth_secret="b",
    )


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_backend_is_config_error(self) -> None:
        with patch("services.secret_manager.registry.load_connection_config",
                   return_value=_cfg("nope")):
            with self.assertRaises(SecretManagerConfigError):
                await SecretManagerClientRegistry().get_or_create(1, MagicMock())

    async def test_failed_ensure_started_is_not_cached(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock(side_effect=SecretManagerAuthError("bad"))
        registry = SecretManagerClientRegistry()
        with (
            patch("services.secret_manager.registry.load_connection_config", return_value=_cfg()),
            patch("services.secret_manager.registry._build_client", return_value=client),
        ):
            with self.assertRaises(SecretManagerAuthError):
                await registry.get_or_create(1, MagicMock())
            self.assertEqual(registry._clients, {})

    async def test_second_call_reuses_client(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock()
        registry = SecretManagerClientRegistry()
        with (
            patch("services.secret_manager.registry.load_connection_config", return_value=_cfg()),
            patch("services.secret_manager.registry._build_client", return_value=client) as build,
        ):
            await registry.get_or_create(1, MagicMock())
            await registry.get_or_create(1, MagicMock())
        build.assert_called_once()

    async def test_invalidate_shuts_client_down(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock()
        client.shutdown = AsyncMock()
        registry = SecretManagerClientRegistry()
        with (
            patch("services.secret_manager.registry.load_connection_config", return_value=_cfg()),
            patch("services.secret_manager.registry._build_client", return_value=client),
        ):
            await registry.get_or_create(1, MagicMock())
        await registry.invalidate(1)
        client.shutdown.assert_awaited_once()
        self.assertEqual(registry._clients, {})
```

`tests/unit/test_vault_client.py` — add one test: after a `startup()` whose `ensure_token`
raises `VaultError`, `service.healthy` is `False`; after a successful one it is `True`.

Done when: all four new files pass; coverage of `services/secret_manager/` ≥ 80 % in the
feature subset run; `pytest tests/unit -k "secret_manager or vault_client"` green.

---

## 4. B2 — `sources.batfish:query` for the ad-hoc endpoints

### 4.1 `services/auth/rbac_seed.py`

**Before**

```python
    ("sources.batfish", "read", "View Batfish sources"),
    ("sources.batfish", "write", "Create or update Batfish sources"),
    ("sources.batfish", "delete", "Delete Batfish sources"),
```

**After**

```python
    ("sources.batfish", "read", "View Batfish sources and list networks/snapshots"),
    ("sources.batfish", "write", "Create or update Batfish sources"),
    ("sources.batfish", "delete", "Delete Batfish sources"),
    # Ad-hoc questions from the Template Editor return routing tables, ACL
    # verdicts, and extracted facts for ANY network on the coordinator --
    # including networks built by workflows the caller cannot see (B2).
    # Deliberately not a "read" action, so the seeded viewer role never gets it.
    ("sources.batfish", "query", "Run ad-hoc Batfish questions from the template editor"),
```

`seed_rbac` needs no change: it grants every permission to `admin` and only `action == "read"`
to `viewer`. It runs idempotently at every boot, so existing deployments get the new
permission (admin-only) on the next start. **Migration note for operators:** custom roles that
should keep using the Template Editor's Batfish tab must be granted `sources.batfish:query`
by an admin.

### 4.2 `routers/sources/batfish/query.py`

**Before**

```python
router = APIRouter(
    prefix="/sources/batfish",
    tags=["sources-batfish"],
    dependencies=[Depends(require_permission("sources.batfish", "read"))],
)
```

**After**

```python
# `query`, not `read`: these endpoints answer questions against any network
# on the coordinator, regardless of which workflow built it (B2). The
# read-only `viewer` role holds `sources.batfish:read` (source list, network
# and snapshot names) but not this.
router = APIRouter(
    prefix="/sources/batfish",
    tags=["sources-batfish"],
    dependencies=[Depends(require_permission("sources.batfish", "query"))],
)
```

### 4.3 Frontend — hide the tab without the permission

`frontend/src/components/features/templates/components/options-dialog.tsx`

**Before**

```tsx
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useNetmikoDeviceSearchQuery } from "@/hooks/queries/use-netmiko-device-search-query";
```

```tsx
        <Tabs defaultValue="netmiko" className="flex min-h-0 flex-1 flex-col gap-0">
          <TabsList className="mx-6 mt-4 w-fit">
            <TabsTrigger value="netmiko">Netmiko</TabsTrigger>
            <TabsTrigger value="batfish">Batfish</TabsTrigger>
          </TabsList>
```

```tsx
          <TabsContent value="batfish" className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
            <BatfishOptionsTab
```

**After**

```tsx
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useNetmikoDeviceSearchQuery } from "@/hooks/queries/use-netmiko-device-search-query";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";
```

```tsx
  // The ad-hoc query endpoints need sources.batfish:query (not :read) -- see
  // doc/BATFISH_INTEGRATION.md "Template Editor integration". Hide the tab
  // rather than showing a form whose every "Run Query" returns 403.
  const user = useAuthStore((state) => state.user);
  const canQueryBatfish = hasPermission(user, "sources.batfish", "query");
```

(place the two lines with the other hooks at the top of the component body)

```tsx
        <Tabs defaultValue="netmiko" className="flex min-h-0 flex-1 flex-col gap-0">
          <TabsList className="mx-6 mt-4 w-fit">
            <TabsTrigger value="netmiko">Netmiko</TabsTrigger>
            {canQueryBatfish ? <TabsTrigger value="batfish">Batfish</TabsTrigger> : null}
          </TabsList>
```

```tsx
          {canQueryBatfish ? (
          <TabsContent value="batfish" className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
            <BatfishOptionsTab
```

(and the matching `) : null}` after that `</TabsContent>`; run `npm run lint` — the file's
prettier config will reflow the indentation).

### 4.4 Docs

`doc/BATFISH_INTEGRATION.md` → "Template Editor integration", the paragraph
"**New endpoints, one per question, under the existing source prefix**":

**Before**

```
(`routers/sources/batfish/query.py`, same `require_permission("sources.batfish",
"read")` as the rest of that router -- this is a read-only analysis call
against an already-built snapshot, no device contact, so no new permission
was added):
```

**After**

```
(`routers/sources/batfish/query.py`, gated by `require_permission("sources.batfish",
"query")` -- a dedicated permission, not `read`, because these endpoints answer
questions against *any* network on the coordinator regardless of which
workflow built it, and Batfish answers (routing tables, ACL verdicts, extracted
TACACS/SNMP facts) are sensitive; the seeded read-only `viewer` role holds
`sources.batfish:read` but not `:query`. Discovery (`…/networks`,
`…/networks/{network}/snapshots`) stays on `read` -- names only, needed by the
workflow-step config pickers. The Options modal hides the Batfish tab for
users without `:query`):
```

`doc/BATFISH_INTEGRATION.md` → "Security notes", third bullet: replace "`sources:batfish` read
access should be scoped by RBAC the same as `sources:pyats`/`sources:ise`" with
"ad-hoc query results are gated by `sources.batfish:query`, which the seeded `viewer` role does
not hold; workflow-run results stay behind `workflow_runs:read` + run visibility".

`CLAUDE.md` → "Adding New Permission" needs no change. `doc/SECURITY-NOTES.md` — covered by
the Batfish entry in §2.3.

### 4.5 Tests

`tests/unit/test_batfish_query_router_auth.py`:

**Before**

```python
    assert response.status_code == 403
    assert "sources.batfish:read" in response.json()["detail"]
```

**After** (every occurrence in this file — the nine `_forbidden_without_permission` tests)

```python
    assert response.status_code == 403
    assert "sources.batfish:query" in response.json()["detail"]
```

Add one test that the *discovery* router still requires only `read`
(`test_batfish_discovery_router.py` already asserts `"sources.batfish:read"`; leave it, it is
now the regression guard for D5).

`tests/unit/test_rbac_seed.py` (or wherever `seed_rbac` is tested — `grep -rn "seed_rbac" tests/unit`):
add `test_viewer_does_not_receive_batfish_query`: after `seed_rbac`, the `viewer` role holds
`sources.batfish:read` and not `sources.batfish:query`; `admin` holds both.

Done when: `pytest tests/unit -k "batfish or rbac_seed"` green; `cd frontend && npm run lint && npx tsc --noEmit`.

---

## 5. SM3 — remove `secret-set` `fixed` mode

### 5.1 `workflow_steps/secret_set/config.py`

**Before**

```python
def get_config() -> dict:
    return {
        "connection_id": None,
        "path_template": "network/{device.name}/tacacs",
        "field": "key",
        "mode": "fixed",
        "fixed_value": "",
        "source_path": "",
        "destination_path": "tacacs.shared_secret",
        "strict_templates": True,
    }
```

**After**

```python
def get_config() -> dict:
    return {
        "connection_id": None,
        "path_template": "network/{device.name}/tacacs",
        "field": "key",
        "source_path": "run_input.new_tacacs_key",
        "destination_path": "tacacs.shared_secret",
        "strict_templates": True,
    }
```

### 5.2 `workflow_steps/secret_set/executor.py`

**Before**

```python
"""Executor for the secret-set workflow step.

Writes an explicit value (a literal, or one read from another attribute path
— e.g. a static run-input the operator supplied at trigger time) to one
field of an external Secret Manager connection, per device — see
doc/SECRET_MANAGER_INTEGRATION.md. The written value is also sealed into the
device's attribute bag so later steps in the same run (a push-config step)
can use it without a second round trip to the secret manager.
```

```python
_STEP_ID = "secret-set"
_VALID_MODES = frozenset({"fixed", "attribute"})


def _parse_config(config: dict[str, Any]) -> tuple[int, str, str, str, str, str, str]:
    connection_id = config.get("connection_id")
    if not isinstance(connection_id, int):
        raise ValueError(f"{_STEP_ID}: connection_id is required")

    # Same defaults config.py declares for a freshly-dropped canvas node — a
    # node whose config was never actually edited (only displayed with an
    # illustrative default in the UI) must behave identically to one where
    # the user explicitly accepted that same value.
    path_template = str(config.get("path_template") or "network/{device.name}/tacacs").strip()
    if not path_template:
        raise ValueError(f"{_STEP_ID}: path_template is required")

    field = str(config.get("field") or "key").strip()
    if not field:
        raise ValueError(f"{_STEP_ID}: field is required")

    mode = str(config.get("mode") or "fixed").strip().lower()
    if mode not in _VALID_MODES:
        raise ValueError(f"{_STEP_ID}: mode must be 'fixed' or 'attribute'")

    fixed_value = str(config.get("fixed_value") or "")
    source_path = str(config.get("source_path") or "").strip()
    if mode == "fixed" and not fixed_value:
        raise ValueError(f"{_STEP_ID}: fixed_value is required in fixed mode")
    if mode == "attribute" and not source_path:
        raise ValueError(f"{_STEP_ID}: source_path is required in attribute mode")

    destination_path = str(config.get("destination_path") or "tacacs.shared_secret").strip()
    if not destination_path:
        raise ValueError(f"{_STEP_ID}: destination_path is required")

    return connection_id, path_template, field, mode, fixed_value, source_path, destination_path
```

```python
def _resolve_value(
    *, device: DeviceContext, mode: str, fixed_value: str, source_path: str
) -> str | None:
    if mode == "fixed":
        return fixed_value
    # attribute mode is a trusted consumer — its whole purpose is pushing a
    # secret value to external storage, same as update-ise-tacacs-key.
    value = resolve_device_attribute(device, source_path, reveal_secrets=True)
    if value == REDACTED_PLACEHOLDER or value is None:
        return None
    return str(value)
```

```python
    connection_id, path_template, field, mode, fixed_value, source_path, destination_path = (
        _parse_config(config)
    )
    strict = parse_strict_templates(config)
```

```python
    for device_id, device in context.devices.items():
        value = _resolve_value(
            device=device, mode=mode, fixed_value=fixed_value, source_path=source_path
        )
        if value is None:
```

**After**

```python
"""Executor for the secret-set workflow step.

Writes a value read from another attribute path — a run input the operator
supplied at trigger time (``run_input.<name>``), or a sealed value an
upstream secret-get / generate-password / secret-generate step produced — to
one field of an external Secret Manager connection, per device — see
doc/SECRET_MANAGER_INTEGRATION.md. The written value is also sealed into the
device's attribute bag so later steps in the same run (a push-config step)
can use it without a second round trip to the secret manager.

There is deliberately no "literal value" mode: step config is persisted in
plaintext in the workflow definition and version-controlled into the
workflows git repository, so a literal there would be a stored secret (SM3).
```

```python
_STEP_ID = "secret-set"
_REMOVED_MODE_HINT = (
    "mode 'fixed' (a literal fixed_value) is no longer supported because step config "
    "is stored in plaintext in the workflow definition; supply the value as a run input "
    "and set source_path to run_input.<name>, or read it from an upstream secret step"
)


def _parse_config(config: dict[str, Any]) -> tuple[int, str, str, str, str]:
    connection_id = config.get("connection_id")
    if not isinstance(connection_id, int):
        raise ValueError(f"{_STEP_ID}: connection_id is required")

    # A saved workflow from before SM3 may still carry mode/fixed_value --
    # fail loudly with the migration hint rather than silently ignoring it.
    if str(config.get("mode") or "").strip().lower() == "fixed" or config.get("fixed_value"):
        raise ValueError(f"{_STEP_ID}: {_REMOVED_MODE_HINT}")

    # Same defaults config.py declares for a freshly-dropped canvas node — a
    # node whose config was never actually edited (only displayed with an
    # illustrative default in the UI) must behave identically to one where
    # the user explicitly accepted that same value.
    path_template = str(config.get("path_template") or "network/{device.name}/tacacs").strip()
    if not path_template:
        raise ValueError(f"{_STEP_ID}: path_template is required")

    field = str(config.get("field") or "key").strip()
    if not field:
        raise ValueError(f"{_STEP_ID}: field is required")

    source_path = str(config.get("source_path") or "run_input.new_tacacs_key").strip()
    if not source_path:
        raise ValueError(f"{_STEP_ID}: source_path is required")

    destination_path = str(config.get("destination_path") or "tacacs.shared_secret").strip()
    if not destination_path:
        raise ValueError(f"{_STEP_ID}: destination_path is required")

    return connection_id, path_template, field, source_path, destination_path
```

```python
def _resolve_value(*, device: DeviceContext, source_path: str) -> str | None:
    # A trusted consumer — its whole purpose is pushing a secret value to
    # external storage, same as update-ise-tacacs-key.
    value = resolve_device_attribute(device, source_path, reveal_secrets=True)
    if value == REDACTED_PLACEHOLDER or value is None:
        return None
    return str(value)
```

```python
    connection_id, path_template, field, source_path, destination_path = _parse_config(config)
    strict = parse_strict_templates(config)
```

```python
    for device_id, device in context.devices.items():
        value = _resolve_value(device=device, source_path=source_path)
        if value is None:
```

### 5.3 `workflow_steps/registry.yaml` — `secret-set` entry

**Before**

```yaml
    overview: Write an explicit value to a Secret Manager connection.
    description: >
      Write a literal value, or one read from another attribute path (e.g. a
      static run-input the operator supplied at trigger time), to one field
      of an external Secret Manager connection per device. Also seals the
      written value into the device's attribute bag so a later step in the
      same run can use it. See doc/SECRET_MANAGER_INTEGRATION.md.
```

```yaml
        - name: mode
          description: fixed (use fixed_value) or attribute (read from source_path).
          data_type: string
          required: true
          default: fixed
        - name: fixed_value
          description: Literal value to write. Required in fixed mode.
          data_type: string
          required: false
        - name: source_path
          description: >
            Attribute path to read the value from (e.g.
            run_input.new_tacacs_key). Required in attribute mode.
          data_type: string
          required: false
```

**After**

```yaml
    overview: Write a value from an attribute path to a Secret Manager connection.
    description: >
      Write a value read from another attribute path — a run input the
      operator supplied at trigger time (run_input.<name>), or a sealed value
      from an upstream secret-get / generate-password / secret-generate step —
      to one field of an external Secret Manager connection per device. Also
      seals the written value into the device's attribute bag so a later step
      in the same run can use it. There is no literal-value mode: step config
      is stored in plaintext in the workflow definition. See
      doc/SECRET_MANAGER_INTEGRATION.md.
```

```yaml
        - name: source_path
          description: >
            Attribute path to read the value from (e.g.
            run_input.new_tacacs_key, or the destination_path of an upstream
            generate-password step). A sealed value is read as cleartext for
            this write only.
          data_type: string
          required: true
          default: run_input.new_tacacs_key
```

### 5.4 Frontend — `frontend/src/components/features/workflow-steps/secret-set/index.tsx`

**Before**

```tsx
  const mode = stringField(config, "mode", "fixed") === "attribute" ? "attribute" : "fixed";
  const strictTemplates = config.strict_templates !== false;
```

```tsx
      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium">mode</Label>
        <Select value={mode} onValueChange={(value) => setField("mode", value)}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="fixed">fixed — a literal value</SelectItem>
            <SelectItem value="attribute">attribute — read from another attribute path</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-[11px] text-muted-foreground">
          fixed writes the literal value typed below; attribute reads the value from
          another attribute path instead (e.g. a run input supplied at trigger time).
        </p>
      </div>

      {mode === "fixed" ? (
        <div className="space-y-1.5">
          <Label className="font-mono text-xs font-medium" htmlFor="secret-set-fixed-value">
            fixed_value
          </Label>
          <Input
            id="secret-set-fixed-value"
            className="h-8 font-mono text-xs"
            type="password"
            autoComplete="new-password"
            value={stringField(config, "fixed_value")}
            onChange={(event) => setField("fixed_value", event.target.value)}
          />
          <p className="text-[11px] text-muted-foreground">
            The literal value to write. Required in fixed mode; masked like any other
            credential input.
          </p>
        </div>
      ) : (
        <div className="space-y-1.5">
          <Label className="font-mono text-xs font-medium" htmlFor="secret-set-source-path">
            source_path
          </Label>
          <Input
            id="secret-set-source-path"
            className="h-8 font-mono text-xs"
            placeholder="run_input.new_tacacs_key"
            value={stringField(config, "source_path")}
            onChange={(event) => setField("source_path", event.target.value)}
          />
          <p className="text-[11px] text-muted-foreground">
            Attribute path to read the value from. Required in attribute mode; a
            sealed value here is read as trusted cleartext for this write only.
          </p>
        </div>
      )}
```

**After**

```tsx
  const strictTemplates = config.strict_templates !== false;
```

```tsx
      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-set-source-path">
          source_path
        </Label>
        <Input
          id="secret-set-source-path"
          className="h-8 font-mono text-xs"
          placeholder="run_input.new_tacacs_key"
          value={stringField(config, "source_path")}
          onChange={(event) => setField("source_path", event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Attribute path to read the value from — a run input supplied at trigger time
          (run_input.&lt;name&gt;) or the destination_path of an upstream secret step. A
          sealed value here is read as trusted cleartext for this write only. Blank uses
          the default shown above. There is no literal-value option: step config is
          stored in plaintext in the workflow definition.
        </p>
      </div>
```

Remove the now-unused `Select`, `SelectContent`, `SelectItem`, `SelectTrigger`, `SelectValue`
imports from this file (ESLint will flag them). In `help-panel.tsx` delete the `mode` and
`fixed_value` `HelpSection`s (lines ~55–75) and reword the "fixed, shared path" fan-out example
at line ~112 (it refers to a *path*, not the removed mode — keep the example, change the word
"fixed" to "static").

### 5.5 Docs

`doc/SECRET_MANAGER_INTEGRATION.md` → "Workflow steps" table, `secret-set` row:

**Before**

```
| `secret-set` | `connection_id`, `path_template`, `field`, `mode` (`fixed`\|`attribute`), `fixed_value`, `source_path`, `destination_path` | Writes an explicit value — a literal, or one read from another attribute path (`attribute` mode is a trusted, `reveal_secrets=True` consumer, same as `update-ise-tacacs-key`). Also seals the written value into `destination_path`. |
```

**After**

```
| `secret-set` | `connection_id`, `path_template`, `field`, `source_path`, `destination_path` | Writes the value read from `source_path` — a run input (`run_input.<name>`, supplied at trigger time, never persisted in the definition) or a sealed upstream value (a trusted, `reveal_secrets=True` consumer, same as `update-ise-tacacs-key`). Also seals the written value into `destination_path`. **No literal-value mode**: step config is stored in plaintext in `workflows.canvas_nodes` and pushed to the workflows git repository, so a literal there would be a stored secret; a saved `mode: fixed` fails at run time with a migration hint. |
```

### 5.6 Tests — `tests/unit/test_secret_set_executor.py`

**Before**

```python
BASE_CONFIG = {
    "connection_id": 1,
    "path_template": "network/{device.name}/tacacs",
    "field": "key",
    "mode": "fixed",
    "fixed_value": "new-key",
    "destination_path": "tacacs.shared_secret",
}
```

```python
class SecretSetExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_mode_requires_fixed_value(self) -> None:
        with self.assertRaises(ValueError):
            await _run(
                {**BASE_CONFIG, "fixed_value": ""},
                _context({"d1": _device("d1")}),
                set_field=AsyncMock(),
            )

    async def test_attribute_mode_requires_source_path(self) -> None:
        with self.assertRaises(ValueError):
            await _run(
                {**BASE_CONFIG, "mode": "attribute", "source_path": ""},
                _context({"d1": _device("d1")}),
                set_field=AsyncMock(),
            )

    async def test_missing_optional_keys_fall_back_to_config_py_defaults(self) -> None:
        # Regression: a canvas node whose config was never actually edited (only
        # displayed with an illustrative default in the UI) sends a config dict
        # with path_template/field/destination_path genuinely absent, not just
        # empty. Must behave identically to explicitly-set defaults, not raise.
        minimal_config = {"connection_id": 1, "mode": "fixed", "fixed_value": "new-key"}
        context = _context({"d1": _device("d1")})
        outcomes = await _run(minimal_config, context, set_field=AsyncMock(return_value=1))

        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["d1"]
        sealed = device.attribute_bags["tacacs"]["shared_secret"]
        self.assertEqual(unwrap_secret(sealed), "new-key")

    async def test_fixed_mode_writes_and_seals_value(self) -> None:
        context = _context({"d1": _device("d1")})
        outcomes = await _run(BASE_CONFIG, context, set_field=AsyncMock(return_value=2))

        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["d1"]
        sealed = device.attribute_bags["tacacs"]["shared_secret"]
        self.assertTrue(is_sealed_secret(sealed))
        self.assertEqual(unwrap_secret(sealed), "new-key")
        self.assertEqual(outcomes[0].context.metadata["node-1.written_count"], 1)
```

**After**

```python
BASE_CONFIG = {
    "connection_id": 1,
    "path_template": "network/{device.name}/tacacs",
    "field": "key",
    "source_path": "run_input.new_tacacs_key",
    "destination_path": "tacacs.shared_secret",
}


def _device_with_run_input(device_id: str, value: str) -> DeviceContext:
    return _device(device_id, attribute_bags={"run_input": {"new_tacacs_key": value}})
```

```python
class SecretSetExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_fixed_mode_is_rejected_with_hint(self) -> None:
        # SM3: a workflow saved before the literal mode was removed must fail
        # loudly, naming the migration path -- never silently write nothing.
        with self.assertRaisesRegex(ValueError, "run_input"):
            await _run(
                {**BASE_CONFIG, "mode": "fixed", "fixed_value": "new-key"},
                _context({"d1": _device("d1")}),
                set_field=AsyncMock(),
            )

    async def test_fixed_value_alone_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "no longer supported"):
            await _run(
                {**BASE_CONFIG, "fixed_value": "new-key"},
                _context({"d1": _device("d1")}),
                set_field=AsyncMock(),
            )

    async def test_blank_source_path_falls_back_to_default(self) -> None:
        context = _context({"d1": _device_with_run_input("d1", "new-key")})
        outcomes = await _run({**BASE_CONFIG, "source_path": ""}, context,
                              set_field=AsyncMock(return_value=1))
        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_missing_optional_keys_fall_back_to_config_py_defaults(self) -> None:
        # Regression: a canvas node whose config was never actually edited (only
        # displayed with an illustrative default in the UI) sends a config dict
        # with path_template/field/source_path/destination_path genuinely
        # absent, not just empty. Must behave identically to explicitly-set
        # defaults, not raise.
        minimal_config = {"connection_id": 1}
        context = _context({"d1": _device_with_run_input("d1", "new-key")})
        outcomes = await _run(minimal_config, context, set_field=AsyncMock(return_value=1))

        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["d1"]
        sealed = device.attribute_bags["tacacs"]["shared_secret"]
        self.assertEqual(unwrap_secret(sealed), "new-key")

    async def test_run_input_value_is_written_and_sealed(self) -> None:
        context = _context({"d1": _device_with_run_input("d1", "new-key")})
        set_field = AsyncMock(return_value=2)
        outcomes = await _run(BASE_CONFIG, context, set_field=set_field)

        set_field.assert_awaited_once_with(1, "network/d1/tacacs", "key", "new-key")
        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["d1"]
        sealed = device.attribute_bags["tacacs"]["shared_secret"]
        self.assertTrue(is_sealed_secret(sealed))
        self.assertEqual(unwrap_secret(sealed), "new-key")
        self.assertEqual(outcomes[0].context.metadata["node-1.written_count"], 1)
        # The plaintext never lands in metadata (unchanged invariant).
        self.assertNotIn("new-key", str(outcomes[0].context.metadata))
```

The remaining tests in the file (`test_attribute_mode_reads_sealed_source_value`,
`test_unresolved_source_routes_device_to_failure`, `test_connection_error_fails_whole_step`)
drop their `"mode": "attribute"` / `"fixed_value": ""` keys from the config dict and are
otherwise unchanged. Any test elsewhere that builds a `secret-set` config with `mode`
(`grep -rn '"mode": "fixed"' tests/` and the registry-catalog snapshot tests, if any) is updated
the same way.

Done when: `pytest tests/unit -k "secret_set or registry"` green; `ruff check workflow_steps/secret_set`;
`cd frontend && npm run lint && npx tsc --noEmit`.

---

## 6. Verification checklist (whole plan)

From `backend/` with the venv active:

```bash
ruff check services/secret_manager services/credentials/manager.py services/auth \
           services/batfish routers/sources/batfish routers/secret_manager.py \
           workflow_steps/secret_set services/vault/client.py
python scripts/check_asyncio_run.py && python scripts/check_http_500_leaks.py && \
python scripts/check_router_repositories.py && python scripts/check_text_sql.py
python -m pytest tests/unit          # ratchet 81 %; expect > 83 %
pyright services/secret_manager routers/secret_manager.py services/batfish   # advisory
```

From `frontend/`: `npm run lint && npx tsc --noEmit`.

Manual smoke (native dev, `ALLOW_LOOPBACK_SOURCE_URLS=true`, `ENV=development`):

1. Settings → Secret Manager → create an OpenBao connection with a **wrong** `secret_id` →
   Test must report *failure* with "AppRole login failed"; fix the secret → success.
2. Same with an Infisical connection and a wrong `client_secret` (uses `docker/infisical/`).
3. Set `credential_name` to an `ssh` credential → 400 at first use / Test reports the
   "must be type 'generic'" error.
4. Settings → Sources → Batfish → host `169.254.169.254` → 400 "Batfish host is not allowed".
5. Log in as a user holding only the `viewer` role → the Options modal shows no Batfish tab;
   `POST /api/proxy/sources/batfish/<id>/query/routes` returns 403 naming `sources.batfish:query`.
6. Open a workflow saved with a `secret-set` in `fixed` mode → run fails at that step with the
   migration hint; switch to a run input → succeeds.

Then update `doc/analysis/FABLE_BACKEND_20260916.md` §2.2 / §3.2 Status columns and §6 with
the commit SHA(s), as was done for the 2026-09-12 audit.
