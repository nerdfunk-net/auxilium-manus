# Plan: Fix SM4 — Hatchet workers never see connection changes

Source: `doc/analysis/FABLE_BACKEND_20260916.md` §2.2 SM4, §6 item 6.
Status: **Ready to implement.** Analysis is against the current tree (post
SM1/SM2/SM3). A plan review folded three corrections into D2, D5, §4, §5.1,
and §6.2 (see §0.1); implement this file, not the pre-review draft. Smaller
nits that did not change the implementation are parked in **§0.2 for later
review** (N1–N4).

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

**D2 — The freshness read must *apply* the SELECT (`populate_existing`), not skip SQL.**
Worker tasks hold one `SessionLocal()` for the whole `StepRunner.execute_all` /
`execute_subgraph` call (`hatchet/workflows/workflow_run/phase1.py` lines 220–245,
`hatchet/workflows/device_group_execution.py` lines 53–79). Secret steps take that session
via `object_session(run)`. `BaseRepository.get_by_id` is
`s.query(Model).filter(id==).first()`. That **does emit SQL** every time; it is not
`Session.get()`. If the instance is already in the identity map and not expired,
SQLAlchemy **discards** the loaded columns and returns the cached Python object. The
hazard is stale attributes, not a skipped round trip.

SQLAlchemy 2's identity map is a `WeakInstanceDict`. `get_connection` returns a dict and
drops the ORM instance, so the next lookup often *does* see the other session's commit
(the instance was GC'd). `populate_existing` is still required: a live instance (held
across the device loop, or still reachable on the rebuild path in the same
`get_or_create`) will hide an API `UPDATE`/`DELETE` without it. `SessionLocal` is
`autoflush=False`. Between steps `RunRepository.update_step_result` commits
(`expire_on_commit=True`), so the gap is mainly **within** one step.

The new lookup uses `.execution_options(populate_existing=True)` so that SELECT
overwrites the live instance. `load_connection_config` → `get_connection` → `get_by_id`
still SELECTs (do not claim "no second round trip"); if the instance survived, it now
carries the committed `credential_name` / `backend_config`.

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

**D5b — Re-read generation on the rebuild path; never evict a newer cache.** A Hatchet
worker runs concurrent tasks. Two `get_or_create` calls on the same connection, with the
row updated between their PK reads, is enough to leak a client:

1. A snapshots generation T1; B snapshots T2 (newer).
2. B rebuilds and inserts a T2 client.
3. A's second lock sees `cached.updated_at (T2) != generation.updated_at (T1)`, pops B's
   client, shuts it down, and inserts a T1 client (A's session may still hold T1 config).

The first lock is therefore compare-only (return on match; **do not pop** on mismatch).
On miss/mismatch, re-read generation outside the lock, then pop only against that fresh
snapshot. If the cache already matches the re-read, return it. If a different generation
appears while we held no lock, loop instead of overwriting. Compare with `==` only
(same rule as D3 — mixed aware/naive `<` raises `TypeError`). `secret-get` is sequential
per device; this race is concurrent Hatchet tasks, not the device loop.

**D6 — Residual, accepted.** Rotating the *credential row's* password while leaving the
connection row untouched does not bump `secret_manager_connections.updated_at`. Workers keep
the SecretID captured at client construction until the next rebuild. OpenBao then fails
closed on re-login (the audit already called this "safe but confusing"). Workaround: any
save of the connection row (including toggling `is_active`). Watching the credentials table
is out of scope.

Out of scope (deliberately): SM5–SM12, B-items, Redis pub/sub, a TTL, moving
`ensure_started` off the lock (SM8), resolving the client once per step instead of once per
device (`SecretManagerService.get_field` → `get_or_create` per device is pre-existing).

### 0.1 Plan-review corrections (folded in)

Three defects found against the pre-review draft; they are already applied above and in
§4 / §5.1 / §6. Do not re-introduce the old text.

1. **Two-session tests must hold the ORM instance.** SQLAlchemy 2.0.51's identity map is
   a `WeakInstanceDict`. `get_connection` returns a dict and drops the instance, so the
   next `get_by_id` is a fresh SELECT and already sees the other session's commit. The
   draft's `assertTrue(worker_svc.get_connection(...)["is_active"])` after an API
   deactivate **fails** on the prescribed `StaticPool` + `AUTOCOMMIT` engine (verified).
   The diagnostic ("session expired the instance") was wrong — it was GC, not
   `expire_on_commit`. Load via `get_by_id` and keep the instance in a local. Use a
   file-backed SQLite DB with two real connections; drop AUTOCOMMIT + StaticPool.
2. **Rebuild must re-read generation (D5b).** The draft's second lock compared against
   the *outer* snapshot, so a stale T1 could pop a T2 cache and leak the T2 OpenBao
   renew task / httpx client. Compare-only first lock, re-read, pop only against the
   fresh snapshot, loop if a different generation appears during shutdown.
3. **D2 and the in-flight-HTTP sentence were misleading.** `filter().first()` always
   SELECTs; `populate_existing` applies columns, it does not "skip SQL" or save a round
   trip on rebuild. `OpenBaoService.shutdown()` / Infisical `httpx.Client.close()` **do**
   abort in-flight calls that still hold the old client. The kill-switch is the *next*
   `get_or_create`; document that, not "in-flight HTTP is not aborted."

### 0.2 Nits for later review — not blockers

> **REVIEW LATER.** These did not block the plan. They are listed so they can be
> accepted, skipped, or folded in on a later pass. Implementers may ignore them;
> none of §2–§7 depends on a decision here.

| ID | Status | Nit | Notes |
|---|---|---|---|
| N1 | **Open — review later** | Pre-review draft cited `hatchet/worker_services.py` `start_all`, line 75 as where the worker registry lives | Line 75 is `await service_factory.stop_secret_manager_services()` in `start_all`'s `finally`, not construction. The registry is lazy in `service_factory.get_secret_manager_registry()` (lines 303–315). §1 already uses the corrected wording; this row is the original citation error so it is not silently lost. |
| N2 | **Open — review later** | `test_get_generation_tracks_update` / `assertGreater` on `updated_at` | Safe **only** because `updated_at` is copied into the frozen dataclass *before* the update (datetime is immutable). Comparing the ORM object to itself after `update_connection` is always `False` (`>`). §6.2 already warns the implementer; worth a glance when reading the test so nobody "simplifies" it to `row.updated_at`. |
| N3 | **Open — review later** | No registry test for missing/inactive with an **empty** cache | §6.1 only covers drop-cached-client. `_require_generation` raises before any cache lookup, so empty-cache missing/inactive is the same `ValueError` path, but there is no test that `load_connection_config` / `_build_client` are not called and `_clients` stays `{}`. Easy add if you want it. |
| N4 | **Open — review later** | `get_generation` assigns `updated_at=connection.updated_at` unwrapped | `name=str(...)` and `is_active=bool(...)` already paper over classic `Column` vs Python types. Bare `updated_at` will add another `Column[datetime]` vs `datetime` pyright error in `connection_service.py` (same class as the four existing ones the SM1–SM3 audit called cosmetic). Wrap it (`updated_at=connection.updated_at` → a `datetime` cast) if you care; do not block SM4 on pyright. |

---

## 1. Why the current code is wrong (grounded in the tree)

Three processes each hold a `SecretManagerClientRegistry` singleton via
`service_factory.get_secret_manager_registry()` (`service_factory.py` lines 303–315):

- FastAPI (`main.py` lifespan calls `stop_secret_manager_services` on shutdown)
- live Hatchet worker (`hatchet/worker_services.py` `start_all`; the registry is
  constructed lazily on first `get_or_create`, torn down in `start_all`'s `finally`
  via `stop_secret_manager_services`)
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
has run in the same session, a *live* identity-map instance carries the committed
columns, so the rebuild path's `load_connection_config` decrypts the current
`credential_name` / `backend_config` even though `get_by_id` still emits a SELECT
(D2 — it is not `Session.get()`). If the instance was already GC'd, that SELECT is a
plain load and is also current.

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
from services.secret_manager.connection_service import (
    SecretManagerConnectionGeneration,
    SecretManagerConnectionService,
)
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

    async def _require_generation(
        self, connection_id: int, db: Session
    ) -> SecretManagerConnectionGeneration:
        generation = SecretManagerConnectionService(db).get_generation(connection_id)
        if generation is None:
            await self.invalidate(connection_id)
            raise ValueError(f"Secret manager connection {connection_id} not found")
        if not generation.is_active:
            await self.invalidate(connection_id)
            raise ValueError(
                f"Secret manager connection '{generation.name}' is not active"
            )
        return generation

    async def get_or_create(self, connection_id: int, db: Session) -> SecretManagerClient:
        while True:
            generation = await self._require_generation(connection_id, db)

            async with self._lock:
                cached = self._clients.get(connection_id)
                if cached is not None and cached.updated_at == generation.updated_at:
                    return cached.client

            # Miss or mismatch. Re-read so a stale snapshot cannot evict a
            # newer cache another coroutine inserted (D5b). Then pop only
            # against this fresh generation.
            generation = await self._require_generation(connection_id, db)

            stale = None
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
                if cached is not None:
                    # Different generation appeared while we shut down — do
                    # not overwrite it; loop and re-read.
                    continue
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
- `ensure_started` still runs *before* the insert and *inside* the lock, so a failed
  login is still not cached (SM1 invariant, `test_failed_ensure_started_is_not_cached`)
  and two coroutines cannot both construct (D5).
- Compare `updated_at` with `==`, never `<` / timestamps. Both values come from the same
  column in the same dialect. Mixed aware/naive equality is `False` (rebuild every call) —
  that cannot happen on PostgreSQL (`DateTime(timezone=True)` + `datetime.now(UTC)` on
  update). Do not call `.replace(tzinfo=…)` or `.timestamp()`.
- Cache-hit path: one PK read, one lock, return. The extra `get_generation` is only on
  miss/mismatch (D5b).
- First lock is compare-only. Pop happens only after a re-read, against that fresh
  generation. The `while True` + `continue` covers a different generation appearing
  during `stale.client.shutdown()`. Do not "simplify" this into the pre-review
  double-checked insert that compared against the outer snapshot — that pops a newer
  cache and leaks its renew task.
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
A live client already inside `get_field`/`set_field` may error: `invalidate`
and a generation mismatch both call `shutdown()`, which closes the httpx
client (OpenBao also cancels its renew task). In-flight calls are not
cancelled by a cooperative abort; they fail because the transport is gone.
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
from services.secret_manager.registry import SecretManagerClientRegistry, _CachedClient

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

    async def test_stale_snapshot_does_not_evict_newer_cache(self) -> None:
        """D5b: a get_or_create whose first PK read is behind the cache must
        re-read and return the newer client, not shut it down."""
        newer = MagicMock()
        newer.shutdown = AsyncMock()
        registry = SecretManagerClientRegistry()
        registry._clients[1] = _CachedClient(client=newer, updated_at=_TS_LATER)
        service = MagicMock()
        service.get_generation.side_effect = [
            _generation(updated_at=_TS),
            _generation(updated_at=_TS_LATER),
        ]
        with (
            patch(
                "services.secret_manager.registry.SecretManagerConnectionService",
                return_value=service,
            ),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ) as load,
            patch("services.secret_manager.registry._build_client") as build,
        ):
            got = await registry.get_or_create(1, MagicMock())
        self.assertIs(got, newer)
        newer.shutdown.assert_not_called()
        build.assert_not_called()
        load.assert_not_called()
        self.assertEqual(service.get_generation.call_count, 2)


if __name__ == "__main__":
    unittest.main()
```

`test_inactive_row_drops_cached_client_and_does_not_rebuild` is the kill-switch test: no
credential decrypt, no `ensure_started`, cached client shut down. Nested `_patch_generation`
is correct — the inner patch replaces `SecretManagerConnectionService` for the second call
only.

`test_stale_snapshot_does_not_evict_newer_cache` is the D5b test. It seeds the cache at
`_TS_LATER` and makes the first `get_generation` return `_TS`. The re-read must return
`_TS_LATER` so the newer client is kept. If the implementer pops on the first lock against
the outer snapshot, this test fails (`newer.shutdown` awaited, `build` called).

Kill-switch / missing-row paths call `_require_generation` once then `invalidate` — they
do not enter the rebuild loop. Empty-cache missing/inactive is covered by the same raise
as the drop-cached-client cases (first `_require_generation` fires before any cache
lookup).

### 6.2 `tests/unit/test_secret_manager_connection_service.py` — add tests

Reuse the existing `setUp` (in-memory SQLite, transport-policy patches) for the three
same-session tests. The load-bearing identity-map proof is: dirty the instance *without
flushing*, then show `get_by_id` still returns the dirty value while `get_by_id_fresh`
overwrites it from the SELECT (DB still has the committed value). Same mechanism the
worker needs against PostgreSQL READ COMMITTED.

The two-session "API committed, worker session already had the row" analog is still
worth having, but **only if the worker holds a strong reference to the ORM instance**.
SQLAlchemy 2's identity map is a `WeakInstanceDict`. `get_connection` returns a dict and
drops the instance; the next `get_by_id` is a fresh SELECT and already sees the other
session's commit — so asserting `get_connection` is still stale after the API update
**fails**. Do **not** use `isolation_level="AUTOCOMMIT"` + `StaticPool`: sessions then
share one DBAPI connection, and AUTOCOMMIT was a wrong diagnosis for that failure
(it was GC, not expiration). Use a file-backed SQLite DB with two real connections and
`autoflush=False` (same as `SessionLocal`). Load via `get_by_id` and keep `held` alive.

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
    this session already holds the ORM instance.

    SQLAlchemy 2's identity map is WeakInstanceDict — a dict from
    get_connection is not a strong ref, so the next lookup would see the
    commit even without populate_existing and the test would pass for the
    wrong reason. Hold the instance. File-backed SQLite + two connections
    (not StaticPool, not AUTOCOMMIT) is the unit-test stand-in for
    PostgreSQL READ COMMITTED: each statement sees the latest commit;
    populate_existing is what overwrites the live instance.
    """

    def setUp(self) -> None:
        import os
        import tempfile

        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self._db_path = handle.name
        engine = create_engine(f"sqlite:///{self._db_path}")
        SecretManagerConnection.metadata.create_all(
            engine, tables=[SecretManagerConnection.__table__]
        )
        self.addCleanup(engine.dispose)
        self.addCleanup(os.unlink, self._db_path)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
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

        held = self.worker_svc._repo.get_by_id(connection_id, db=self.db_worker)
        self.assertIsNotNone(held)
        self.assertTrue(held.is_active)

        self.api_svc.update_connection(connection_id, {"is_active": False})

        # Strong ref keeps the identity-map instance; get_by_id returns it
        # without applying the other session's COMMIT — this is the SM4 hazard.
        self.assertTrue(held.is_active)
        self.assertIs(
            self.worker_svc._repo.get_by_id(connection_id, db=self.db_worker), held
        )
        self.assertTrue(held.is_active)

        generation = self.worker_svc.get_generation(connection_id)
        self.assertIsNotNone(generation)
        self.assertFalse(generation.is_active)
        # populate_existing overwrote the live instance.
        self.assertFalse(held.is_active)

    def test_get_generation_sees_delete_committed_on_other_session(self) -> None:
        connection_id = self.api_svc.create_connection(
            {**_OPENBAO_BASE, "name": "to-delete"}
        )
        held = self.worker_svc._repo.get_by_id(connection_id, db=self.db_worker)
        self.assertIsNotNone(held)

        self.api_svc.delete_connection(connection_id)

        self.assertIsNone(self.worker_svc.get_generation(connection_id))
```

If `test_get_generation_sees_deactivation_committed_on_other_session` fails because
`held.is_active` is already `False` after the API update (before `get_generation`),
the instance was expired or you dropped the strong ref (do not "fix" that by switching
to AUTOCOMMIT). If it fails because `get_generation` is still `is_active=True`,
`populate_existing` is not actually on the query.

`test_get_generation_tracks_update` uses `assertGreater` on `updated_at` copied into the
frozen dataclass *before* the update (datetime is immutable; do not compare the ORM
object to itself). On SQLite `update_connection` writes `datetime.now(UTC)` explicitly
(line 154), so the second value is strictly later. Do not compare ISO strings from
`_to_dict`.

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

- All nine registry tests in §6.1 pass (four preserved SM1 behaviours + four SM4 + D5b
  stale-snapshot-does-not-evict-newer-cache).
- `get_generation` missing/update tests pass; `get_by_id_fresh` overwrites a dirty
  identity-map instance; the two-session file-backed tests pass — in particular the
  **held** ORM instance stays stale after the other session's deactivate *and*
  `get_generation` is not.
- `ruff check` on the five files is clean. The four guard scripts are OK. Coverage ratchet
  still holds.
- No new `text()` SQL, no router talking to a repository, no change to executor files.

Not in scope to verify: a live Hatchet worker. The two-session test *is* the worker/API
split (file-backed SQLite, two sessions, one commit, held instance). A manual check, if
desired: start API + worker, run a workflow that `secret-get`s once (caches the client),
deactivate the connection in Settings, run the workflow again — the second run must fail
with `Secret manager connection '<name>' is not active` without restarting the worker.
