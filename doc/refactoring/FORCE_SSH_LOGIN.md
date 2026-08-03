# Force Fresh SSH Login — Implementation Plan

Status: **IMPLEMENTED**
Scope: backend only (no frontend/UI changes)
Related docs: `doc/DURABLE_SSH_SESSION.md`, `doc/WORKFLOW-STEPS.md`
Implements: the deferred "Per-step requires fresh session" item from
`DURABLE_SSH_SESSION.md` §11, scoped to the login probe path.

---

## 1. Goal

`login-successful` must always perform a **real new SSH authentication** against
the device, using a **disposable side connection** that:

1. Never touches, locks for reuse, or disconnects any existing pooled session.
2. Is closed immediately after the probe (success or failure).
3. Is never stored in the pool and is never used by a later step.

This is required for the rollback-after-bad-change pattern:

```
get-device-configs → deploy-rendered-template → login-successful
        │ SSH opened              │ same pooled session stays open │ NEW probe login
                                                                   │ (closed after)
                              on failure ──────────────────────────┘
                              use the ORIGINAL pooled session to
                              roll back / undo the bad config
```

If the probe tore down the original session, a failed login would leave no live
session to cancel the change. Keeping the pooled session open is therefore
**non-negotiable**.

---

## 2. Current Behaviour (defect)

| Layer | What happens today |
|---|---|
| `login_successful/executor.py` | Calls `NetmikoService.test_login(...)` |
| `NetmikoService.test_login` | `pool.run_on_device(op=lambda s: s.is_alive())` |
| `DeviceSessionPool.run_on_device` | Reuses the live session for `(host, device_type, credential_reference)` when `is_alive()` is true — **no new `ConnectHandler` login** |

Consequence: if any prior SSH step in the same segment left a live session for
that key, `login-successful` is a keepalive check on the already-authenticated
socket, not a login test. A post-deploy AAA/SSH break can falsely report success
**and** the design below must not fix that by destroying the recovery session.

Concurrent runs are unaffected (each segment has its own pool — see
`DURABLE_SSH_SESSION.md` §3.6). The bug is **within one segment**, after an
earlier SSH step.

---

## 3. Design

### 3.1 Core idea — parallel probe, never mutate the pool

Add a dedicated pool API for login probes that opens an independent
`NetmikoDeviceSession`, runs the liveness check, and disconnects it in
`finally`. The pool's `_sessions` dict is **not read or written**.

```
┌─ DeviceSessionPool (unchanged entries) ─┐
│  key K → PooledSession (LIVE, untouched) │
└──────────────────────────────────────────┘
                    ║
                    ║  test_login / probe_login does NOT go through run_on_device
                    ║
                    ▼
         NetmikoDeviceSession (ephemeral)
              connect() → is_alive() → disconnect()
              never inserted into _sessions
```

Hard invariant:

> A login probe must not call `disconnect()` / `connect()` on any
> `PooledSession.session`, must not take a per-key session lock for the purpose
> of replacing that session, and must not insert the probe session into the
> pool.

### 3.2 Why not `force_fresh` reconnect-into-pool?

An earlier draft proposed disconnecting the pooled session and reconnecting
under the same key. That is **rejected**:

| Approach | Fresh login? | Pooled session for rollback? |
|---|---|---|
| Reconnect-into-pool (`force_fresh` tear-down) | Yes | **No** — recovery path destroyed |
| Disposable side probe (this plan) | Yes | **Yes** — original session stays open |
| Reuse pooled `is_alive()` (today) | No | Yes — but false positive |

The probe connection is throwaway by product requirement: on success it is
closed immediately; on failure it is also closed (connect may have partially
succeeded). It is never handed to a later step.

### 3.3 API surface

Prefer a **new** pool method over overloading `run_on_device`, so the "do not
touch pooled sessions" rule is structurally obvious:

```python
class DeviceSessionPool:
    async def probe_login(
        self,
        *,
        host: str,
        device_type: str,
        username: str,
        password: str,
    ) -> bool:
        """Open a disposable SSH session, confirm it is alive, disconnect.

        Does not read, lock, mutate, or replace any pooled session. The probe
        session is never stored in the pool.
        """
```

```python
# NetmikoService.test_login — switch from run_on_device to probe_login
async def test_login(
    self,
    *,
    host: str,
    network_driver: str | None,
    platform: str | None,
    username: str,
    password: str,
    credential_reference: str,  # kept for call-site compatibility / logging; unused by pool key
    device_type: str | None = None,
) -> bool:
    resolved = device_type or resolve_netmiko_device_type(...)
    return await self._pool.probe_login(
        host=host,
        device_type=resolved,
        username=username,
        password=password,
    )
```

`credential_reference` stays on `test_login` so executors and tests need no
signature churn; the probe is not keyed (it never enters the pool).

Do **not** add a canvas/config toggle. Login testing always uses a disposable
probe. Do **not** add a general registry `requires_fresh_session` flag in this
change.

### 3.4 `probe_login` implementation

```python
async def probe_login(
    self,
    *,
    host: str,
    device_type: str,
    username: str,
    password: str,
) -> bool:
    loop = asyncio.get_running_loop()
    session = NetmikoDeviceSession(
        host=host,
        device_type=device_type,
        username=username,
        password=password,
        keepalive=settings.netmiko_keepalive_seconds,
    )

    def _probe() -> bool:
        try:
            session.connect()
            return session.is_alive()
        finally:
            session.disconnect()

    return await loop.run_in_executor(self._executor, _probe)
```

Notes:

- Uses the pool's existing `ThreadPoolExecutor` (same as `run_on_device`) so
  thread limits stay consistent; does **not** use `run_on_device`.
- `finally: disconnect()` runs on both success and failure (including auth
  errors raised from `connect()` — `disconnect()` must be safe when never
  connected; today's `NetmikoDeviceSession.disconnect()` already no-ops when
  `_connection is None`).
- Auth / timeout errors propagate unchanged; the executor maps them to the
  `failure` outcome as today.
- When `enabled=False`, behaviour is identical for probes (always disposable).
  No special branch required; optionally short-circuit to the same code path
  unconditionally so pooling kill-switch cannot change probe semantics.

### 3.5 Interaction with an existing pooled session

| Moment | Pooled session for key K | Probe session |
|---|---|---|
| Before `login-successful` | Live (from deploy / get-configs) | — |
| During probe | Still live, unused by probe | Connecting |
| Probe success | Still live | Disconnected in `finally` |
| Probe failure | Still live → available for rollback steps | Disconnected in `finally` |
| Later `run-command` same key | Reused via `run_on_device` as today | Gone |

Device-side view during the probe: **two** SSH sessions for a short window
(pooled + probe). That is intentional and required.

### 3.6 Concurrency

- Probe does not take the per-key `asyncio.Lock`. A concurrent `run_on_device`
  on the same key in the same pool can proceed on the pooled session while the
  probe runs on a different socket. That is correct for rollback workflows
  (and for gather across devices).
- Netmiko thread-safety: probe and pooled session are **different**
  `NetmikoDeviceSession` instances → no shared Netmiko object.
- Cross-run: unchanged (independent pools).

### 3.7 Device session limits

Some platforms limit concurrent VTY/SSH sessions. The probe briefly consumes
one extra session. Acceptable for v1; document it. If a device is at its
session limit, the probe fails (login not successful) while the pooled
session remains — still the correct safety outcome.

---

## 4. File-by-File Change List

### 4.1 `backend/services/network/netmiko/session_pool.py`

1. Add `async def probe_login(...)` as in §3.4.
2. Module docstring: document that login probes are disposable side sessions
   and **must not** mutate pooled entries; cite the rollback invariant.
3. Do **not** add a tear-down `force_fresh` flag to `run_on_device`.

### 4.2 `backend/services/network/netmiko/service.py`

1. Change `test_login` to call `self._pool.probe_login(...)` instead of
   `run_on_device`.
2. Update the method docstring:

   > Always opens a disposable SSH session to verify authentication. Existing
   > pooled sessions for the same host are left untouched so a failed probe
   > can still use them to roll back config. The probe session is disconnected
   > before this method returns and is never reused.

### 4.3 `backend/workflow_steps/login_successful/executor.py`

No call-site change required (`test_login` signature stays). Add a short
comment at the `test_login` call:

```python
# Disposable probe login — does not touch any pooled session, so a prior
# deploy session remains available for rollback on failure.
```

### 4.4 Docs

1. `doc/DURABLE_SSH_SESSION.md`:
   - §11: mark fresh-login-for-probe as implemented via disposable
     `probe_login`; link here. Explicitly reject reconnect-into-pool for this
     use case (destroys rollback).
   - §6 lifecycle matrix: add rows from §6 below.
2. `doc/WORKFLOW-STEPS.md` "Device sessions":
   - `login-successful` opens a disposable side connection; pooled sessions
     stay open for rollback.
3. `backend/workflow_steps/registry.yaml` for `login-successful`:
   - Description: performs a **new** SSH login attempt without closing any
     existing workflow device session; used to verify that config changes did
     not break authentication (existing session remains available to undo
     changes).

### 4.5 Out of scope

- Frontend / ConfigPanel changes.
- Registry-level `requires_fresh_session` metadata.
- Changing other SSH executors.
- Replacing the pooled session after a successful probe.
- Keeping the probe session open for later reuse.
- Cross-run session coordination.

---

## 5. Test Plan (write / extend first — TDD)

### 5.1 Pool unit tests — `backend/tests/unit/test_device_session_pool.py`

Extend `FakeSession` if needed so probes are distinguishable (e.g. track all
constructed instances via a class-level list on the fake).

1. **`test_probe_login_does_not_touch_existing_pooled_session`**
   - `run_on_device` once → pooled session connected (`connect_calls == 1`).
   - `probe_login` same host/creds → a **second** FakeSession instance is
     constructed; probe has `connect_calls == 1` and `disconnect_calls == 1`.
   - Pooled session still `connected is True`, still `connect_calls == 1`,
     `disconnect_calls == 0`.
   - `len(pool._sessions) == 1` (probe not inserted).
2. **`test_probe_login_disconnects_on_success`**
   - Probe returns `True`; probe session not connected afterwards.
3. **`test_probe_login_disconnects_on_connect_failure`**
   - Fake `connect()` raises; assert `disconnect` still ran; exception
     propagates; pool `_sessions` unchanged / empty.
4. **`test_run_on_device_after_probe_reuses_original_session`**
   - `run_on_device` → `probe_login` → `run_on_device` again: pooled
     `connect_calls` still 1 (reuse), probe was a separate instance.

### 5.2 Service integration — `backend/tests/unit/test_netmiko_service_pool_integration.py`

5. **`test_test_login_leaves_pooled_session_open`**
   - `send_commands` once, then `test_login` same key: pooled entry still
     alive; two FakeSession constructions; send_commands session still
     connected.
6. Existing reuse tests remain green.

### 5.3 Executor — `backend/tests/unit/test_login_successful_executor.py`

7. Existing `test_login` mocks stay valid (no new required kwargs).

### 5.4 Manual lab (PR test plan)

1. Workflow: `get-device-configs → login-successful` with pooling on.
2. During/after the login step, confirm **two** logins occurred (or a brief
   second session) and that the first session was **not** dropped before the
   probe finished.
3. Negative case (if safe): break new SSH auth via deploy while keeping the
   existing session; confirm `login-successful` fails **and** a following
   rollback step can still use the original pooled session (e.g.
   `deploy-rendered-template` / `run-command` with restore commands) without
   an extra reconnect forced by a torn-down pool entry.

---

## 6. Lifecycle Matrix

| Scenario | Expected behaviour |
|---|---|
| First network op is `login-successful` | Disposable probe connect+disconnect; pool may stay empty |
| `get-device-configs` then `login-successful` (same key) | Pooled session stays open; probe opens second SSH, then closes; pool still holds original |
| Probe fails after deploy | Pooled session still alive for rollback steps |
| Probe succeeds then `run-command` (same key) | Probe closed; `run-command` reuses original pooled session (not the probe) |
| Two `login-successful` nodes in sequence | Two independent disposable probes; pooled sessions untouched |
| `netmiko_session_pooling=False` | Probe still disposable; other steps use per-call sessions as today |
| Concurrent runs, same device | Independent pools; each probe is its own disposable session |

---

## 7. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Accidentally reconnecting via `run_on_device` and killing rollback | Dedicated `probe_login`; tests assert pooled session `disconnect_calls == 0` |
| Probe session leaked into `_sessions` | Never call `_get_or_create_entry` from probe path; test asserts `len(_sessions)` unchanged |
| Probe not disconnected on exception | `finally: session.disconnect()`; test connect-failure path |
| Device max-session limit rejects probe | Probe fails → login-successful failure; pooled session still available to undo |
| Brief dual sessions confuse operators | Document in registry description and WORKFLOW-STEPS |
| Thread pool saturation | Probe uses same executor; same `netmiko_pool_workers` bound as other ops |

---

## 8. Implementation Order

| # | Step | Touches | Gate |
|---|---|---|---|
| 1 | RED: pool tests in §5.1 | `test_device_session_pool.py` | tests fail |
| 2 | GREEN: implement `probe_login` | `session_pool.py` | pool tests pass |
| 3 | RED/GREEN: `test_login` → `probe_login` + service test §5.2 | `service.py`, integration test | tests pass |
| 4 | Docs + registry + executor comment | docs, `registry.yaml`, executor | review |
| 5 | Manual lab §5.4 | — | pooled session survives failed probe |

---

## 9. Acceptance Criteria

- [x] `login-successful` always performs a new Netmiko authentication (not
      `is_alive()` on an existing pooled socket).
- [x] Any pre-existing pooled session for the same host/credential key remains
      connected for the entire probe and afterwards (success or failure).
- [x] The probe session is disconnected before `test_login` returns and is
      never inserted into the pool or reused by a later step.
- [x] Default reuse path for other SSH steps is unchanged.
- [x] Unit/integration tests in §5 pass, including an explicit
      "pooled session untouched" assertion.
- [x] Docs state the rollback invariant: probe must not tear down pooled
      sessions.
- [ ] Manual lab (§5.4) — requires real lab devices, not run as part of this
      change.
