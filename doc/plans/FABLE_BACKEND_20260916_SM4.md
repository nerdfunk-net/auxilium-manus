# Plan: Fix SM4 — Hatchet workers never see connection changes

Source: `doc/analysis/FABLE_BACKEND_20260916.md` §2.2 SM4, §6 item 6.
Status: **Ready to implement.** Analysis below is against the current tree (post
SM1/SM2/SM3); no further code reading is required to implement this.

| # | Sev | Issue | Decision | Status |
|---|---|---|---|---|
| SM4 | M | `SecretManagerClientRegistry` caches one client per connection id for the process lifetime; `registry.invalidate()` runs only in the API process, so Hatchet workers keep using an edited, deactivated, or deleted connection until restart | On every `get_or_create`, PK-read `(name, is_active, updated_at)` with `populate_existing=True` and rebuild/refuse when the row moved, is inactive, or is gone (D1) | **Open** |

Every section ends with the tests that must exist before it is considered done. Run from
`backend/` with the project venv: `source ../.venv/bin/activate`.

---

## 0. Decisions

**D1 — Re-check the row, do not TTL, do not Redis.** The audit's cheapest option is the
right one: `get_or_create` always reads the connection's `(is_active, updated_at)` via one
indexed PK query and either reuses the cached client, rebuilds it, or refuses. A 60 s TTL
leaves the kill-switch (`is_active = False` / `DELETE`) delayed, which is the part of SM4
that is not "stale config" but "deactivation does not stop in-flight workers". Redis pub/sub
across the API process and the two Hatchet workers (`hatchet/worker.py`,
`hatchet/dynamic_worker.py`) stays deferred — it is already listed as such in
`doc/SECRET_MANAGER_INTEGRATION.md` and is not needed once every process re-reads the row
on use.

**D2 — The freshness read must bypass SQLAlchemy's identity map.** Worker tasks hold one
`SessionLocal()` for the whole `StepRunner.execute_all` / `execute_subgraph` call
(`hatchet/workflows/workflow_run/phase1.py` lines 220–245,
`hatchet/workflows/device_group_execution.py` lines 53–79). Secret steps take that session
via `object_session(run)`. `BaseRepository.get_by_id` is `s.query(Model).filter(id==).first()`,
which returns the identity-map instance without hitting the database when the row is already
loaded and not expired. `SessionLocal` is `autoflush=False` and the worker session does not
commit around step boundaries, so a connection loaded on device 1 of a `secret-get` (or by
an earlier secret step in the same task) would hide an API-process `UPDATE`/`DELETE`
committed in between. The new lookup therefore uses
`.execution_options(populate_existing=True)` so the SELECT always runs and overwrites the
cached instance. That also makes the subsequent `load_connection_config` → `get_connection`
→ `get_by_id` in the same session see the same committed row (no second round trip, no
stale `credential_name` / `backend_config` on rebuild).

**D3 — Cache key is `updated_at`; `is_active` / missing are hard refusals.**
`SecretManagerConnectionService.update_connection` already writes
`update_kwargs["updated_at"] = datetime.now(UTC)` on every accepted field change (including
`is_active`, `credential_name`, `backend_config`, `description`). Deactivate and edit
therefore both move `updated_at`. The registry still checks `is_active` independently so a
row that is inactive is dropped and refused even if `updated_at` happened not to change.
A missing row (deleted) is the same: drop the cached client, raise the existing
`ValueError(f"Secret manager connection {connection_id} not found")`. Description-only
updates cause a needless rebuild; that is accepted — cheaper than missing a credential
rotation.

**D4 — Keep router `invalidate()`.** `PUT`/`DELETE`/`POST …/test` in
`routers/secret_manager.py` already call `registry.invalidate(connection_id)` in the API
process. That is still useful (eagerly stops the API process's OpenBao renew loop; `/test`
still forces a fresh login). It does not, and cannot, reach the worker processes.
`service_factory.get_secret_manager_registry()` is process-local, constructed lazily, and
torn down independently in `main.py` and `hatchet/worker_services.py`. Do not add a
cross-process signal in this plan.

**D5 — Rebuild stays inside the process-wide lock; the PK read does not.** Today's
`get_or_create` holds `self._lock` across `load_connection_config` + `ensure_started` (SM8,
out of scope). Moving the rebuild out of the lock would let two coroutines construct two
clients and leak the loser (OpenBao renew task). Keep construction inside the lock. Do the
PK read *before* acquiring the lock so a cache-hit on connection A is not queued behind
connection B's login, and so the lock is not held across the new SELECT. After a stale
pop, shut the old client down outside the lock (same shape as today's `invalidate`).

**D6 — Residual, accepted.** Rotating the *credential row's* password while leaving the
connection row untouched does not bump `secret_manager_connections.updated_at`. Workers keep
the SecretID captured at client construction until the next rebuild. OpenBao then fails
closed on re-login (the audit already called this "safe but confusing"). Workaround: any
save of the connection row (including toggling `is_active`). Watching the credentials table
is out of scope.

Out of scope (deliberately): SM5–SM12, B-items, Redis pub/sub, a TTL, moving
`ensure_started` off the lock (SM8), resolving the client once per step instead of once per
device (`SecretManagerService.get_field` → `get_or_create` per device is pre-existing).

---

## 1. Why the current code is wrong (grounded in the tree)

Three processes each hold a `SecretManagerClientRegistry` singleton via
`service_factory.get_secret_manager_registry()` (`service_factory.py` lines 303–315):

- FastAPI (`main.py` lifespan calls `stop_secret_manager_services` on shutdown)
- live Hatchet worker (`hatchet/worker_services.py` `start_all`, line 75)
- background-tier Hatchet worker (same `start_all`)

`service_factory` "holds no cross-process state" (`worker_services.py` lines 5–6). Each
registry is a `dict[int, SecretManagerClient]` (`registry.py` line 40) filled on first
`get_or_create` and emptied only by `invalidate` / `shutdown_all`.

The only callers of `invalidate` are in the API process:

```125:126:backend/routers/secret_manager.py
        await service_factory.get_secret_manager_registry().invalidate(connection_id)
```

```151:152:backend/routers/secret_manager.py
        connection_service.delete_connection(connection_id)
        await service_factory.get_secret_manager_registry().invalidate(connection_id)
```

```178:181:backend/routers/secret_manager.py
    registry = service_factory.get_secret_manager_registry()
    await registry.invalidate(connection_id)
    try:
        await registry.get_or_create(connection_id, db)
```

Every workflow step goes through `SecretManagerService` → `get_or_create` on the *worker*
registry (`service.py` lines 33–35, 41–43, 62–64;
`workflow_steps/secret_{get,set,generate}/executor.py`). Today's cache-hit path returns
the cached client without reading the row:

```43:52:backend/services/secret_manager/registry.py
    async def get_or_create(self, connection_id: int, db: Session) -> SecretManagerClient:
        async with self._lock:
            client = self._clients.get(connection_id)
            if client is not None:
                return client
            cfg = load_connection_config(connection_id, db)
            client = _build_client(cfg)
            await client.ensure_started()
            self._clients[connection_id] = client
            return client
```

`load_connection_config` *does* refuse a missing or `is_active=False` row
(`config.py` lines 36–40), but it runs only on cache miss. After first use, deactivate /
delete / edit of `addr`/`mount`/`project_id`/`credential_name` is invisible to that worker
until process restart. That is SM4.

`updated_at` is already a real column (`core/models/secret_manager.py` lines 40–45,
`nullable=False`, `onupdate=func.now()`) and is already bumped on every service update
(`connection_service.py` line 154). No migration.

---

## 2. Repository — `get_by_id_fresh`

File: `backend/repositories/secret_manager/secret_manager_connection_repository.py`

Do **not** change `BaseRepository.get_by_id`. Other domains must not inherit a surprise
always-SELECT. Add the method only on this repository.

**Before** (end of file, after `name_exists`)

```python
    def name_exists(self, name: str, db: Session | None = None) -> bool:
        with self._db_session(db or self._db) as s:
            return (
                s.query(SecretManagerConnection)
                .filter(SecretManagerConnection.name == name)
                .count()
                > 0
            )
```

**After**

```python
    def name_exists(self, name: str, db: Session | None = None) -> bool:
        with self._db_session(db or self._db) as s:
            return (
                s.query(SecretManagerConnection)
                .filter(SecretManagerConnection.name == name)
                .count()
                > 0
            )

    def get_by_id_fresh(
        self, connection_id: int, db: Session | None = None
    ) -> SecretManagerConnection | None:
        """PK lookup that always hits the database and overwrites the identity
        map (``populate_existing``). A worker session that already loaded this
        row must still see commits from the API process (SM4)."""
        with self._db_session(db or self._db) as s:
            return (
                s.query(SecretManagerConnection)
                .filter(SecretManagerConnection.id == connection_id)
                .execution_options(populate_existing=True)
                .first()
            )
```

`id` is the integer primary key (`index=True` plus PK). This is one indexed `WHERE id = ?`.
Stay on the existing `s.query(...)` style; do not introduce `sqlalchemy.text()`.

---

## 3. Connection service — generation snapshot

File: `backend/services/secret_manager/connection_service.py`

Add a frozen dataclass next to the existing module-level constants (after
`_TRANSPORT_FIELDS`, before `_validate_backend_config`). The registry stores `updated_at`
as the datetime object returned by SQLAlchemy, **not** the ISO string `_to_dict` produces
— string round-tripping would make equality depend on `isoformat()` formatting.

**Before** (imports + constants)

```python
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

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
```

**After**

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

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


@dataclass(frozen=True)
class SecretManagerConnectionGeneration:
    """Cache key for ``SecretManagerClientRegistry`` (SM4).

    ``updated_at`` is the ORM datetime, not the ISO string ``_to_dict`` emits.
    """

    name: str
    is_active: bool
    updated_at: datetime
```

Add `get_generation` next to `get_connection` (after line 103). It is the only new
business method; it does not log, matching `get_connection`'s "missing → None" shape
rather than raising.

**Before**

```python
    def get_connection(self, connection_id: int) -> dict[str, Any] | None:
        try:
            connection = self._repo.get_by_id(connection_id, db=self._db)
            return self._to_dict(connection) if connection else None
        except Exception as e:
            logger.error("Error getting secret manager connection %s: %s", connection_id, e)
            raise

    def get_connections(self, active_only: bool = False) -> list[dict[str, Any]]:
```

**After**

```python
    def get_connection(self, connection_id: int) -> dict[str, Any] | None:
        try:
            connection = self._repo.get_by_id(connection_id, db=self._db)
            return self._to_dict(connection) if connection else None
        except Exception as e:
            logger.error("Error getting secret manager connection %s: %s", connection_id, e)
            raise

    def get_generation(self, connection_id: int) -> SecretManagerConnectionGeneration | None:
        """Return the cache-key columns for *connection_id*, always from the DB.

        ``None`` means the row is gone (deleted). Used by
        ``SecretManagerClientRegistry.get_or_create`` so worker processes notice
        edits, deactivations, and deletes without a cross-process invalidate.
        """
        connection = self._repo.get_by_id_fresh(connection_id, db=self._db)
        if connection is None:
            return None
        return SecretManagerConnectionGeneration(
            name=str(connection.name),
            is_active=bool(connection.is_active),
            updated_at=connection.updated_at,
        )

    def get_connections(self, active_only: bool = False) -> list[dict[str, Any]]:
```

Do **not** wrap `get_generation` in the `try/except Exception: logger.error; raise`
copied onto the other methods. A PK miss is a normal `None`; a real DB failure should
propagate without an extra log line that the caller cannot distinguish from
`get_connection`'s. (The audit already flagged those wrappers as noise.)

`get_connection` / `load_connection_config` stay on `get_by_id`. After `get_generation`
has run in the same session, the identity map holds the fresh instance, so the rebuild
path's `load_connection_config` decrypts the *current* credential without a second SELECT.

---

## 4. Registry — freshness check on every `get_or_create`

File: `backend/services/secret_manager/registry.py`

Replace the module. The public methods stay `get_or_create` / `invalidate` / `shutdown_all`;
callers (`SecretManagerService`, the router, `stop_secret_manager_services`) do not change.

**Before** (full current file)

```python
"""Lazy, per-connection ``SecretManagerClient`` cache.

Unlike ``core/vault.py``'s two-singleton pattern (exactly one OpenBao
connection, known at boot from env vars), Secret Manager connections are DB
rows discovered at first use — there is no fixed set to start eagerly. Each
connection gets its own live client instance on first use, cached for the
process lifetime, or until :meth:`invalidate` (called by the connection
update/delete router so an edited connection doesn't keep serving a stale
client).
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session

from services.secret_manager.client import SecretManagerClient
from services.secret_manager.config import SecretManagerConnectionConfig, load_connection_config
from services.secret_manager.exceptions import SecretManagerConfigError

logger = logging.getLogger(__name__)


def _build_client(cfg: SecretManagerConnectionConfig) -> SecretManagerClient:
    if cfg.backend == "openbao":
        from services.secret_manager.openbao_client import OpenBaoSecretManagerClient

        return OpenBaoSecretManagerClient(cfg)
    if cfg.backend == "infisical":
        from services.secret_manager.infisical_client import InfisicalSecretManagerClient

        return InfisicalSecretManagerClient(cfg)
    raise SecretManagerConfigError(f"Unknown secret manager backend: {cfg.backend!r}")


class SecretManagerClientRegistry:
    def __init__(self) -> None:
        self._clients: dict[int, SecretManagerClient] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, connection_id: int, db: Session) -> SecretManagerClient:
        async with self._lock:
            client = self._clients.get(connection_id)
            if client is not None:
                return client
            cfg = load_connection_config(connection_id, db)
            client = _build_client(cfg)
            await client.ensure_started()
            self._clients[connection_id] = client
            return client

    async def invalidate(self, connection_id: int) -> None:
        """Drop and shut down a connection's cached client (e.g. after it was
        edited or deleted), so the next use rebuilds it from the current row."""
        async with self._lock:
            client = self._clients.pop(connection_id, None)
        if client is not None:
            await client.shutdown()

    async def shutdown_all(self) -> None:
        async with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            try:
                await client.shutdown()
            except Exception:
                logger.warning("Error shutting down secret manager client", exc_info=True)
```

**After** (full file)

```python
"""Lazy, per-connection ``SecretManagerClient`` cache.

Unlike ``core/vault.py``'s two-singleton pattern (exactly one OpenBao
connection, known at boot from env vars), Secret Manager connections are DB
rows discovered at first use — there is no fixed set to start eagerly. Each
connection gets its own live client instance on first use.

The cache is process-local (API + each Hatchet worker has its own). Router
``invalidate()`` only drops the API process's entry; workers notice edits,
deactivations, and deletes by re-reading ``(is_active, updated_at)`` on every
``get_or_create`` (SM4).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from services.secret_manager.client import SecretManagerClient
from services.secret_manager.config import SecretManagerConnectionConfig, load_connection_config
from services.secret_manager.connection_service import SecretManagerConnectionService
from services.secret_manager.exceptions import SecretManagerConfigError

logger = logging.getLogger(__name__)


def _build_client(cfg: SecretManagerConnectionConfig) -> SecretManagerClient:
    if cfg.backend == "openbao":
        from services.secret_manager.openbao_client import OpenBaoSecretManagerClient

        return OpenBaoSecretManagerClient(cfg)
    if cfg.backend == "infisical":
        from services.secret_manager.infisical_client import InfisicalSecretManagerClient

        return InfisicalSecretManagerClient(cfg)
    raise SecretManagerConfigError(f"Unknown secret manager backend: {cfg.backend!r}")


@dataclass(frozen=True)
class _CachedClient:
    client: SecretManagerClient
    updated_at: datetime


class SecretManagerClientRegistry:
    def __init__(self) -> None:
        self._clients: dict[int, _CachedClient] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, connection_id: int, db: Session) -> SecretManagerClient:
        generation = SecretManagerConnectionService(db).get_generation(connection_id)
        if generation is None:
            await self.invalidate(connection_id)
            raise ValueError(f"Secret manager connection {connection_id} not found")
        if not generation.is_active:
            await self.invalidate(connection_id)
            raise ValueError(
                f"Secret manager connection '{generation.name}' is not active"
            )

        async with self._lock:
            cached = self._clients.get(connection_id)
            if cached is not None and cached.updated_at == generation.updated_at:
                return cached.client
            stale = self._clients.pop(connection_id, None)

        if stale is not None:
            await stale.client.shutdown()

        async with self._lock:
            cached = self._clients.get(connection_id)
            if cached is not None and cached.updated_at == generation.updated_at:
                return cached.client
            cfg = load_connection_config(connection_id, db)
            client = _build_client(cfg)
            await client.ensure_started()
            self._clients[connection_id] = _CachedClient(
                client=client, updated_at=generation.updated_at
            )
            return client

    async def invalidate(self, connection_id: int) -> None:
        """Drop and shut down a connection's cached client (e.g. after it was
        edited or deleted), so the next use rebuilds it from the current row."""
        async with self._lock:
            cached = self._clients.pop(connection_id, None)
        if cached is not None:
            await cached.client.shutdown()

    async def shutdown_all(self) -> None:
        async with self._lock:
            cached_clients = list(self._clients.values())
            self._clients.clear()
        for cached in cached_clients:
            try:
                await cached.client.shutdown()
            except Exception:
                logger.warning("Error shutting down secret manager client", exc_info=True)
```

Notes the implementer must not "simplify" away:

- Error strings are byte-for-byte those in `load_connection_config` (`config.py` lines
  38–40). Step executors surface `ValueError` as a configuration failure; changing the
  wording would churn executor tests that match on the message and operators who grep logs.
- `ensure_started` still runs *before* the insert, so a failed login is still not cached
  (SM1 invariant, `test_failed_ensure_started_is_not_cached`).
- Compare `updated_at` with `==`, never `<` / timestamps. Both values come from the same
  column in the same dialect. Mixed aware/naive equality is `False` (rebuild every call) —
  that cannot happen on PostgreSQL (`DateTime(timezone=True)` + `datetime.now(UTC)` on
  update). Do not call `.replace(tzinfo=…)` or `.timestamp()`.
- The double-checked insert after shutdown covers the window where another coroutine
  rebuilt the same generation while we awaited `stale.client.shutdown()`.
- `invalidate` now pops a `_CachedClient`. `shutdown_all` iterates `.client`. The router
  and `stop_secret_manager_services` do not touch `_clients` directly.

No change to `config.py` `load_connection_config`. It remains the decrypt-and-build path.

No change to `service.py`, the three executors, `service_factory.py`, `main.py`, or
`hatchet/worker_services.py`.

No change to `routers/secret_manager.py`. Keep the three `invalidate` calls.

---

## 5. Docs

### 5.1 `doc/SECRET_MANAGER_INTEGRATION.md` — architecture paragraph

**Before** (lines 97–104)

```
Each configured connection gets its **own live client instance** — new
infrastructure, not a reuse of the existing two-singleton `core/vault.py`
pattern, because that pattern is hardcoded to exactly one OpenBao connection
read from env vars. `SecretManagerClientRegistry` is a `dict[int,
SecretManagerClient]` keyed by `secret_manager_connections.id`, built lazily
on first use per connection, with an `invalidate(id)` call from the
connection update/delete router so an edited connection doesn't keep serving
a stale client.
```

**After**

```
Each configured connection gets its **own live client instance** — new
infrastructure, not a reuse of the existing two-singleton `core/vault.py`
pattern, because that pattern is hardcoded to exactly one OpenBao connection
read from env vars. `SecretManagerClientRegistry` is a process-local
`dict[int, (client, updated_at)]` keyed by `secret_manager_connections.id`,
built lazily on first use per connection. The connection update/delete/test
router calls `invalidate(id)` in the **API** process (eagerly stops that
process's OpenBao renew loop and forces `/test` to log in again). Each
Hatchet worker has its own registry and never receives that call; instead
`get_or_create` re-reads `(is_active, updated_at)` from PostgreSQL on every
use (PK lookup, `populate_existing`) and rebuilds or refuses when the row
moved, is inactive, or is gone. Deactivating or deleting a connection is
therefore a kill-switch for the *next* `secret-get`/`secret-set`/
`secret-generate` call in every process, without restarting the worker.
In-flight HTTP calls already using the old client are not aborted.
```

### 5.2 Same file — Deferred / follow-ups, Redis bullet (lines 515–517)

**Before**

```
- **Redis-backed shared client/token cache** across API + worker processes
  — v1 keeps the existing in-process pattern, same acceptable-for-now status
  as `VAULT_INTEGRATION.md`'s own deferred Redis cache.
```

**After**

```
- **Redis-backed shared client/token cache** across API + worker processes
  — still deferred. SM4 closed the "workers never see connection changes"
  gap with a PK re-read of `(is_active, updated_at)` on every `get_or_create`;
  Redis pub/sub would only remove that SELECT. Same acceptable-for-now status
  as `VAULT_INTEGRATION.md`'s own deferred Redis cache. Rotating the
  *credential row* behind a connection (same `credential_name`, new password)
  still does not bump `secret_manager_connections.updated_at`; re-save the
  connection, or accept fail-closed at the next OpenBao re-login.
```

No CLAUDE.md change. No frontend change.

---

## 6. Tests

### 6.1 `tests/unit/test_secret_manager_registry.py` — replace the file

The four existing tests patch `load_connection_config` and pass `MagicMock()` as `db`.
After D1, `get_or_create` calls `SecretManagerConnectionService(db).get_generation`
*before* that patch fires; a MagicMock session would be handed to the real service and
blow up. Every test must mock `SecretManagerConnectionService` on the **registry** module
(the import site).

**After** (full file)

```python
"""SecretManagerClientRegistry: lazy build, SM4 freshness, no caching on
failed ensure_started (SM1), invalidate, unknown backend."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from services.secret_manager.config import SecretManagerConnectionConfig
from services.secret_manager.connection_service import SecretManagerConnectionGeneration
from services.secret_manager.exceptions import SecretManagerAuthError, SecretManagerConfigError
from services.secret_manager.registry import SecretManagerClientRegistry

_TS = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
_TS_LATER = datetime(2026, 9, 16, 13, 0, 0, tzinfo=UTC)


def _cfg(backend: str = "openbao") -> SecretManagerConnectionConfig:
    return SecretManagerConnectionConfig(
        id=1, name="net", backend=backend, verify_ssl=True, backend_config={},
        auth_id="a", auth_secret="b",
    )


def _generation(
    *, is_active: bool = True, updated_at: datetime = _TS, name: str = "net"
) -> SecretManagerConnectionGeneration:
    return SecretManagerConnectionGeneration(
        name=name, is_active=is_active, updated_at=updated_at
    )


def _patch_generation(generation: SecretManagerConnectionGeneration | None):
    service = MagicMock()
    service.get_generation.return_value = generation
    return patch(
        "services.secret_manager.registry.SecretManagerConnectionService",
        return_value=service,
    )


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_backend_is_config_error(self) -> None:
        with (
            _patch_generation(_generation()),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg("nope"),
            ),
        ):
            with self.assertRaises(SecretManagerConfigError):
                await SecretManagerClientRegistry().get_or_create(1, MagicMock())

    async def test_failed_ensure_started_is_not_cached(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock(side_effect=SecretManagerAuthError("bad"))
        registry = SecretManagerClientRegistry()
        with (
            _patch_generation(_generation()),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ),
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
            _patch_generation(_generation()),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ),
            patch("services.secret_manager.registry._build_client", return_value=client) as build,
        ):
            first = await registry.get_or_create(1, MagicMock())
            second = await registry.get_or_create(1, MagicMock())
        build.assert_called_once()
        self.assertIs(first, second)
        self.assertIs(first, client)

    async def test_invalidate_shuts_client_down(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock()
        client.shutdown = AsyncMock()
        registry = SecretManagerClientRegistry()
        with (
            _patch_generation(_generation()),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ),
            patch("services.secret_manager.registry._build_client", return_value=client),
        ):
            await registry.get_or_create(1, MagicMock())
        await registry.invalidate(1)
        client.shutdown.assert_awaited_once()
        self.assertEqual(registry._clients, {})

    async def test_missing_row_drops_cached_client(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock()
        client.shutdown = AsyncMock()
        registry = SecretManagerClientRegistry()
        with (
            _patch_generation(_generation()),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ),
            patch("services.secret_manager.registry._build_client", return_value=client),
        ):
            await registry.get_or_create(1, MagicMock())
        with _patch_generation(None):
            with self.assertRaisesRegex(ValueError, "connection 1 not found"):
                await registry.get_or_create(1, MagicMock())
        client.shutdown.assert_awaited_once()
        self.assertEqual(registry._clients, {})

    async def test_inactive_row_drops_cached_client_and_does_not_rebuild(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock()
        client.shutdown = AsyncMock()
        registry = SecretManagerClientRegistry()
        with (
            _patch_generation(_generation()),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ) as load,
            patch("services.secret_manager.registry._build_client", return_value=client),
        ):
            await registry.get_or_create(1, MagicMock())
            load.reset_mock()
            with _patch_generation(_generation(is_active=False)):
                with self.assertRaisesRegex(ValueError, "is not active"):
                    await registry.get_or_create(1, MagicMock())
            load.assert_not_called()
        client.shutdown.assert_awaited_once()
        self.assertEqual(registry._clients, {})

    async def test_updated_at_change_rebuilds_client(self) -> None:
        old_client = MagicMock()
        old_client.ensure_started = AsyncMock()
        old_client.shutdown = AsyncMock()
        new_client = MagicMock()
        new_client.ensure_started = AsyncMock()
        registry = SecretManagerClientRegistry()
        with (
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ),
            patch(
                "services.secret_manager.registry._build_client",
                side_effect=[old_client, new_client],
            ) as build,
        ):
            with _patch_generation(_generation(updated_at=_TS)):
                first = await registry.get_or_create(1, MagicMock())
            with _patch_generation(_generation(updated_at=_TS_LATER)):
                second = await registry.get_or_create(1, MagicMock())
        self.assertIs(first, old_client)
        self.assertIs(second, new_client)
        self.assertEqual(build.call_count, 2)
        old_client.shutdown.assert_awaited_once()
        new_client.shutdown.assert_not_called()

    async def test_unchanged_updated_at_does_not_call_load_connection_config(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock()
        registry = SecretManagerClientRegistry()
        with (
            _patch_generation(_generation()),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ) as load,
            patch("services.secret_manager.registry._build_client", return_value=client),
        ):
            await registry.get_or_create(1, MagicMock())
            load.reset_mock()
            await registry.get_or_create(1, MagicMock())
            load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
```

`test_inactive_row_drops_cached_client_and_does_not_rebuild` is the kill-switch test: no
credential decrypt, no `ensure_started`, cached client shut down. Nested `_patch_generation`
is correct — the inner patch replaces `SecretManagerConnectionService` for the second call
only.

### 6.2 `tests/unit/test_secret_manager_connection_service.py` — add three tests

Reuse the existing `setUp` (in-memory SQLite, transport-policy patches). Do **not** try to
prove identity-map staleness with two SQLite sessions under the default isolation level:
once `get_connection` has run, that session has an open transaction, and SQLite's snapshot
will hide the other session's `COMMIT` from *both* `get_by_id` and `get_by_id_fresh`. That
would make a two-session test either fail or pass for the wrong reason. The load-bearing
proof is: dirty the identity-map instance *without flushing*, then show `get_by_id` still
returns the dirty value while `get_by_id_fresh` overwrites it from the SELECT (DB still
has the committed value). Same mechanism the worker needs against PostgreSQL READ
COMMITTED; no isolation games.

The two-session "API committed, worker session already had the row" analog is still worth
having, but only with `isolation_level="AUTOCOMMIT"` so each statement sees the latest
commit while the ORM identity map still holds the old Python object. Use
`sqlalchemy.pool.StaticPool` + `sqlite://` (`:memory:` is per-connection; two sessions
would otherwise be two empty databases).

Append to the existing file (before `if __name__ == "__main__"`):

```python
    def test_get_generation_returns_none_for_missing(self) -> None:
        self.assertIsNone(self.service.get_generation(999))

    def test_get_generation_tracks_update(self) -> None:
        connection_id = self._create()
        before = self.service.get_generation(connection_id)
        self.assertIsNotNone(before)
        self.assertTrue(before.is_active)
        self.assertEqual(before.name, "network-secrets")

        self.service.update_connection(connection_id, {"is_active": False})
        after = self.service.get_generation(connection_id)
        self.assertIsNotNone(after)
        self.assertFalse(after.is_active)
        self.assertGreater(after.updated_at, before.updated_at)

    def test_get_by_id_fresh_overwrites_dirty_identity_map(self) -> None:
        connection_id = self._create()
        row = self.service._repo.get_by_id(connection_id, db=self.db)
        self.assertTrue(row.is_active)
        row.is_active = False  # dirty, not flushed — DB still True

        self.assertFalse(self.service._repo.get_by_id(connection_id, db=self.db).is_active)
        fresh = self.service._repo.get_by_id_fresh(connection_id, db=self.db)
        self.assertTrue(fresh.is_active)
        self.assertTrue(self.service.get_generation(connection_id).is_active)


class SecretManagerConnectionGenerationFreshnessTests(unittest.TestCase):
    """SM4: get_generation must see commits from another session even when
    this session already has the row in its identity map.

    ``isolation_level="AUTOCOMMIT"`` is required on SQLite so the worker
    session's next SELECT sees the API session's COMMIT; without it, SQLite
    snapshot isolation hides the commit from *both* lookups and the test
    cannot tell populate_existing from a stale snapshot. PostgreSQL workers
    run READ COMMITTED, where each statement already sees the latest commit
    and populate_existing is what overwrites the identity map — AUTOCOMMIT
    SQLite is the unit-test stand-in for that statement visibility.
    """

    def setUp(self) -> None:
        from sqlalchemy.pool import StaticPool

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            isolation_level="AUTOCOMMIT",
        )
        SecretManagerConnection.metadata.create_all(
            engine, tables=[SecretManagerConnection.__table__]
        )
        self.addCleanup(engine.dispose)
        Session = sessionmaker(bind=engine)
        self.db_worker = Session()
        self.db_api = Session()
        self.addCleanup(self.db_worker.close)
        self.addCleanup(self.db_api.close)
        self.worker_svc = SecretManagerConnectionService(self.db_worker)
        self.api_svc = SecretManagerConnectionService(self.db_api)

        validate_patcher = patch(
            "services.secret_manager.transport_policy.validate_outbound_http_url",
            side_effect=lambda url, *, resolve_dns=True: url.rstrip("/"),
        )
        validate_patcher.start()
        self.addCleanup(validate_patcher.stop)
        env_patcher = patch(
            "services.secret_manager.transport_policy.settings.environment", "development"
        )
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

    def test_get_generation_sees_deactivation_committed_on_other_session(self) -> None:
        connection_id = self.api_svc.create_connection(dict(_OPENBAO_BASE))

        loaded = self.worker_svc.get_connection(connection_id)
        self.assertTrue(loaded["is_active"])

        self.api_svc.update_connection(connection_id, {"is_active": False})

        # Identity map still holds the pre-update row — this is the SM4 hazard.
        self.assertTrue(self.worker_svc.get_connection(connection_id)["is_active"])

        generation = self.worker_svc.get_generation(connection_id)
        self.assertIsNotNone(generation)
        self.assertFalse(generation.is_active)
        # populate_existing overwrote the map, so a later get_connection agrees.
        self.assertFalse(self.worker_svc.get_connection(connection_id)["is_active"])

    def test_get_generation_sees_delete_committed_on_other_session(self) -> None:
        connection_id = self.api_svc.create_connection(
            {**_OPENBAO_BASE, "name": "to-delete"}
        )
        self.assertIsNotNone(self.worker_svc.get_connection(connection_id))

        self.api_svc.delete_connection(connection_id)

        self.assertIsNone(self.worker_svc.get_generation(connection_id))
```

If `test_get_generation_sees_deactivation_committed_on_other_session` fails because
`get_connection` after the API update already returns `is_active=False`, the worker
session expired the instance (do not switch away from AUTOCOMMIT to "fix" that — you
would lose statement visibility). If it fails because `get_generation` is still
`is_active=True`, `populate_existing` is not actually on the query.

`test_get_generation_tracks_update` uses `assertGreater` on `updated_at`. On SQLite both
values come from the same connection; `update_connection` writes `datetime.now(UTC)`
explicitly (line 154), so the second value is strictly later. Do not compare ISO strings
from `_to_dict`.

### 6.3 Router tests — no change

`test_update_invalidates_registry` stays. SM4 does not remove API-side `invalidate`.

---

## 7. Verification checklist

From `backend/` with the venv active:

```bash
ruff check services/secret_manager/registry.py \
           services/secret_manager/connection_service.py \
           repositories/secret_manager/secret_manager_connection_repository.py \
           tests/unit/test_secret_manager_registry.py \
           tests/unit/test_secret_manager_connection_service.py
python scripts/check_asyncio_run.py
python scripts/check_http_500_leaks.py
python scripts/check_router_repositories.py
python scripts/check_text_sql.py
python -m pytest tests/unit/test_secret_manager_registry.py \
                 tests/unit/test_secret_manager_connection_service.py \
                 tests/unit/test_secret_manager_router.py -q
python -m pytest tests/unit -q --cov-fail-under=81
```

Done when:

- All eight registry tests in §6.1 pass (four preserved SM1 behaviours + four SM4).
- `get_generation` missing/update tests pass; `get_by_id_fresh` overwrites a dirty
  identity-map instance; the two-session AUTOCOMMIT tests pass — in particular
  `get_connection` is stale after the other session's deactivate *and* `get_generation`
  is not.
- `ruff check` on the five files is clean. The four guard scripts are OK. Coverage ratchet
  still holds.
- No new `text()` SQL, no router talking to a repository, no change to executor files.

Not in scope to verify: a live Hatchet worker. The two-session test *is* the worker/API
split (same engine, two sessions, one commit). A manual check, if desired: start API +
worker, run a workflow that `secret-get`s once (caches the client), deactivate the
connection in Settings, run the workflow again — the second run must fail with
`Secret manager connection '<name>' is not active` without restarting the worker.
