# Durable SSH Sessions Across Workflow Steps — Implementation Plan

Status: **IMPLEMENTED** (v1, backend only). §9 (replay idempotency) remains a
separate, unimplemented follow-up.
Scope: backend only (no frontend/UI changes required for v1)
Related docs: `WORKFLOW-STEPS.md`, `WAIT-AND-RUN.md`

---

## 1. Goal

A workflow run must be able to open an SSH session to a device once and reuse that
same live session across multiple steps, e.g.:

```
get-nautobot-devices → get-device-configs → (REST call to other system) → run-command → deploy-rendered-template
                            │ SSH opened          │ session stays open        │ same session      │ same session
```

Today every network step opens and tears down a fresh Netmiko session **per device,
per step**. The goal is transparent session reuse for the lifetime of one execution
segment, without changing the user-facing workflow model.

---

## 2. Current-State Analysis

### 2.1 Execution architecture (what makes this possible)

The whole run executes as **one Hatchet durable task** in **one Python process /
coroutine**:

- `hatchet/workflows/workflow_run.py` — workflow `WorkflowExecution`:
  - task `prepare` (30 s)
  - durable task `execute_steps` (24 h) — walks the canvas graph in topological
    order via `StepRunner`, entirely in-process.
- `hatchet/workflows/device_group_execution.py` — child workflow
  `DeviceGroupExecution`, one task `execute_device_group` (1 h) per device group
  during fan-out. Also a single in-process invocation.
- `hatchet/worker.py` — one worker process, `slots=10` (up to 10 concurrent task
  invocations share the process).

Because each execution segment is a single coroutine in a single process, a live
SSH socket **can** be held in memory across steps. Nothing in Hatchet prevents
this — the limitation is purely in our executor implementation.

### 2.2 Where connections are created and destroyed today

Call chain for every network step:

```
StepRunner._execute_step (services/execution/step_runner.py:520)
  → executor(config=…, context=…, run=…, artifact_service=…, node_id=…)
      → NetmikoService()                       # new instance PER STEP EXECUTION
          → loop.run_in_executor(_sync_*)      # thread pool
              → with _session(host, …):        # connect
                    session.send_commands(…)   # work
                                               # disconnect (context manager exit)
```

Concrete sites:

| File | What it does |
|---|---|
| `services/network/netmiko/connection.py` | `NetmikoDeviceSession` — already has separated `connect()` / `disconnect()` / `connection` property. Good foundation. |
| `services/network/netmiko/service.py` | `NetmikoService` — every public method builds a session inside a `with` block (`_sync_send_commands` etc.) → **connect/disconnect per call**. |
| `workflow_steps/run_command/executor.py:98` | `netmiko = NetmikoService()` per step execution |
| `workflow_steps/get_device_configs/executor.py:63` | same |
| `workflow_steps/deploy_rendered_template/executor.py:82` | same |
| `routers/netmiko.py:93,156` | same pattern for ad-hoc API calls (out of scope, but see §10) |

### 2.3 Existing defect discovered during analysis

`NetmikoService.__init__` creates a `ThreadPoolExecutor(max_workers=10)` that is
never explicitly shut down, and a new `NetmikoService` is instantiated on every
network step execution (and every `routers/netmiko.py` request).

**Measured severity (verified 2026-07-26 with a simulation of the exact pattern
on Python 3.14):** this is *not* an unbounded leak. CPython collects the dropped
instance promptly and the executor's idle threads exit when their owner is
garbage-collected (50 sequential step-simulations plateaued at 11 threads and
settled back to baseline). The actual costs are:

- up to 10 threads created and torn down per network step (churn, negligible
  next to SSH latency),
- transient peaks bounded by concurrently-alive instances (~`slots × 10`),
- cleanup timing depends on GC — a traceback or reference cycle holding a
  service instance keeps its threads alive until a generational GC pass.

Conclusion: no standalone hotfix needed; the refactor below removes the pattern
structurally (one executor per pool, deterministic `shutdown()` in `close()`).

### 2.4 Hard boundaries — where a session can NEVER survive

These are architectural facts, not fixable by this plan; the design must respect
them:

1. **Fan-out boundary** (`_dispatch_children` → `DeviceGroupExecution`): parent and
   children are separate Hatchet task invocations (JSON in/out, potentially
   different workers). Sessions cannot cross. Not a practical problem: children
   run the whole per-device subgraph, so pooling *inside* the child covers the
   per-device step chain (the case that matters most).
2. **Durable waits** (`ctx.aio_wait_for_event` — debug stepping, Wait & Run
   approval gates): the coroutine may park for hours; devices drop idle SSH
   (`exec-timeout`) long before that. Sessions must be released before a durable
   wait and lazily re-established after.
3. **Worker crash / durable-task replay**: on re-execution nothing in memory
   survives. Sessions are rebuilt lazily; see §9 for the related (pre-existing)
   idempotency risk.

### 2.5 Executor contract (what has to change)

All 32 executors implement (documented in `WORKFLOW-STEPS.md` §executor contract,
enforced implicitly by the single call site `StepRunner._execute_step`):

```python
async def execute(*, config, context, run, artifact_service, node_id) -> list[StepOutcome]
```

Executors use keyword-only parameters **without** `**kwargs`, so adding an argument
at the call site requires touching every executor signature (mechanical, grep-able).

---

## 3. Design

### 3.1 Core idea

Introduce a **`DeviceSessionPool`** whose lifetime equals one *execution segment*
(one `StepRunner` usage span):

- created when a segment starts (phase-1 walk, phase-4 post-join resume, or a
  fan-out child),
- injected into executors alongside `artifact_service`,
- sessions are opened lazily on first use, keyed by connection identity,
- reused by any later step in the same segment with the same identity,
- health-checked (`is_alive()`) and transparently reconnected on acquire,
- **suspended** (all sessions closed, pool kept) before every durable wait,
- closed unconditionally in a `finally` when the segment ends.

Pooling is **transparent**: no workflow/canvas/UI change. A step that uses the same
device + credential as a previous step silently reuses the socket.

### 3.2 Session identity (pool key)

```python
SessionKey = tuple[
    str,  # host           (bare hostname/IP as passed to ConnectHandler)
    str,  # device_type    (resolved netmiko driver, incl. per-step override)
    str,  # credential_reference  (vault name — NOT the password)
]
```

Rationale:
- Two steps using different credentials against the same device get different
  sessions (correct privilege semantics).
- `credential_reference` instead of `username`/`password` keeps secrets out of the
  key and out of accidental logging. The resolved `(username, password)` is stored
  on the session object only.
- `device_type` in the key covers `network_driver_override` differences between
  steps.

Edge case: if a credential's password is rotated mid-run, an existing live session
keeps working (SSH is already authenticated); a reconnect after suspend will use
the newly resolved password. Acceptable; document it.

### 3.3 Concurrency model

Constraints:
- Netmiko/paramiko sessions are **not thread-safe** — one session must never be
  used by two threads at once.
- Executors run per-device work concurrently via `asyncio.gather` (per step), but
  a given device appears once per step, and steps run **sequentially** within a
  segment. So contention on one session is only possible across the connect path
  (two coroutines requesting the same key simultaneously) — still guard it.

Design:
- One `ThreadPoolExecutor` **per pool** (per segment), `max_workers` from settings
  (default 10, same as today). Shut down in `close()`. This also fixes §2.3.
- One `asyncio.Lock` **per SessionKey**: all operations on a session (connect,
  send, disconnect) run while its lock is held; the blocking Netmiko call itself
  runs in the pool's thread executor via `run_in_executor`.
- Pool-level `asyncio.Lock` only for dict mutation (get-or-create of entries).

Worst-case thread math: worker `slots=10` × `max_workers=10` = 100 threads per
worker process. Same order as today (today it is per-step-instance and leaked);
make `max_workers` a setting (`settings.netmiko_pool_workers`) so it can be tuned.

### 3.4 Keeping sessions alive between network steps

While non-SSH steps run (the "REST call in another system" case), sessions sit
idle. Two mechanisms:

1. **TCP keepalive**: pass `keepalive=30` to `ConnectHandler` in
   `NetmikoDeviceSession.connect()` (paramiko transport keepalive). Prevents
   NAT/firewall silent drops during minutes-long gaps.
2. **Reconnect-on-acquire**: on every `pool.acquire(key)`, check
   `connection.is_alive()`; if dead, disconnect + reconnect before returning.
   This makes device-side `exec-timeout` kills self-healing.

Note the semantic caveat: a transparent reconnect gives you a *new* session
(enable mode is re-entered by `connect(privileged=True)`, but e.g. an interactive
pending state would be lost). For the current step set (send_command /
send_config_set / save_config) this is safe because no step leaves a session in a
non-base state between steps. Record this as an invariant: **executors must return
sessions to privileged-exec base state before returning.**

### 3.5 Fan-out / fan-in interaction (analysis)

Fan-out is not a problem for the pool — it is where pooling pays off most. The
hard rule from §2.4 (sessions cannot cross the parent→child task boundary)
costs almost nothing in practice because of *where* SSH happens in a fanned-out
workflow:

```
get-nautobot-devices (parent, API only — no SSH)
        │ fan-out
        ├── child[device A]: get-configs → parse → render → deploy   ← all SSH; ONE session for A
        ├── child[device B]: get-configs → parse → render → deploy   ← one session for B
        │ fan-in
        └── parent: git-push / store-artifact (runs once — no SSH)
```

- Pre-fan-out steps are inventory/API steps; post-join steps are run-once sinks
  (git, artifacts). All device SSH lives inside the child branch, and each child
  is one in-process coroutine with its own pool → the entire per-device chain
  runs over a single SSH login.
- The only lossy case: a workflow that SSHes to devices **before** fan-out and
  again inside the branch. The parent's sessions close at dispatch
  (§5.5 item 1) and each child logs in once more — exactly one extra login per
  device, in a workflow shape that is rare by construction. Accepted; no
  mitigation needed.
- Fan-out also fixes a convoy effect the pool alone cannot: without fan-out,
  steps process all devices in lockstep (`asyncio.gather` per step), so the
  slowest device in step N delays every device's step N+1. Fanned-out children
  progress independently.

### 3.6 What is explicitly out of scope for v1

- Cross-segment persistence (parent → fan-out children).
- Session sharing between concurrent runs (pool is run-segment-scoped by design;
  sharing across runs would create credential/tenancy hazards).
- A user-visible "hold connection" toggle per step. Pooling is always-on with a
  single global kill switch (`settings.netmiko_session_pooling: bool = True`) for
  emergency rollback.
- scrapli/async drivers (see §11 Future work).

---

## 4. New Component: `DeviceSessionPool`

**New file:** `backend/services/network/netmiko/session_pool.py` (~200 lines)

```python
"""Run-segment-scoped pool of live Netmiko sessions.

One pool per execution segment (StepRunner span). Not shared across Hatchet
task invocations. All public methods are asyncio-safe; blocking Netmiko I/O
runs on the pool's private thread executor.
"""

SessionKey = tuple[str, str, str]  # (host, device_type, credential_reference)

class PooledSession:
    key: SessionKey
    session: NetmikoDeviceSession          # existing class, reused as-is
    lock: asyncio.Lock                     # serializes all use of this session
    last_used: float                       # monotonic, for diagnostics/idle reaping

class DeviceSessionPool:
    def __init__(self, *, max_workers: int, enabled: bool = True) -> None: ...

    async def run_on_device(
        self,
        *,
        host: str,
        device_type: str,
        credential_reference: str,
        username: str,
        password: str,
        op: Callable[[NetmikoDeviceSession], T],   # sync callable, runs in executor thread
    ) -> T:
        """Acquire (or lazily create/reconnect) the session for the key, hold its
        per-session lock, execute `op(session)` on the thread executor, release.

        When `enabled` is False, behaves exactly like today: fresh session per
        call, disconnected afterwards (rollback path).
        """

    async def suspend(self) -> None:
        """Disconnect every live session but keep the pool usable afterwards.
        Called before durable waits. Never raises (log + continue per session)."""

    async def close(self) -> None:
        """Disconnect everything and shut down the thread executor. Idempotent.
        Never raises."""

    # diagnostics
    def stats(self) -> dict:  # {"open": n, "created_total": n, "reconnects": n}
```

Design notes:

- `run_on_device(op=…)` (a higher-order sync callable executed under the lock, on
  the executor thread) is deliberately the **only** way to touch a session. This
  makes the not-thread-safe invariant structurally enforceable — no executor can
  keep a raw session past the lock.
- Connect happens inside `op`'s guarded scope: get-or-create entry under the pool
  lock, then under the session lock: `if not alive → connect()` in the executor
  thread, then run `op`.
- `suspend()`/`close()` take each session lock before disconnecting so they cannot
  race an in-flight command.
- Errors from `op` propagate unchanged (executors already map exceptions to
  per-device `DeviceError`); errors during reconnect surface as
  `NetmikoConnectionError`, same type executors already handle.

---

## 5. File-by-File Change List

### 5.1 `services/network/netmiko/connection.py` — minor additions

1. Add `keepalive: int = 30` constructor param; pass `keepalive` into
   `device_params` in `connect()`.
2. Add `def is_alive(self) -> bool` → `self._connection is not None and
   self._connection.is_alive()` (guard exceptions → `False`).
3. No other behavior change. `NetmikoDeviceSession` remains the single low-level
   session class, now used both by the pool and (unchanged) by `routers/netmiko.py`.

### 5.2 `services/network/netmiko/service.py` — refactor to pool-backed

`NetmikoService` keeps its public async API (**signatures unchanged** except one
new required keyword) so executor diffs stay small:

1. `NetmikoService.__init__(self, *, pool: DeviceSessionPool)` — no longer owns a
   `ThreadPoolExecutor`; delegates to the pool.
2. Each public method gains `credential_reference: str` and calls
   `pool.run_on_device(..., op=…)` where `op` is the existing `_sync_*` body
   **minus** the `with _session(...)` wrapper (session is provided by the pool,
   not created/destroyed):
   - `_sync_send_commands` → `def _op(session): return session.send_commands(commands, use_textfsm=…)`
   - `_sync_deploy_config` → `def _op(session): result = session.deploy_config(…); … save_running_config()`
   - `_sync_get_configs` / running / startup analogously.
3. **Invariant** (add to module docstring): every `op` leaves the session in
   privileged-exec base state (config mode always exited — `send_config_set`
   already does; no pending interactive prompts).
4. Keep a thin compatibility path for `routers/netmiko.py` (see §10): either a
   module-level helper that builds a throwaway single-use pool, or (preferred)
   `DeviceSessionPool(enabled=False)` per request + `close()` in `finally`.

### 5.3 Executor contract — add one keyword argument

New contract (update `WORKFLOW-STEPS.md` §"executor contract" and the docstring in
`services/execution/step_registry.py`):

```python
async def execute(
    *, config, context, run, artifact_service, node_id,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]
```

- **All 32 executors** under `backend/workflow_steps/*/executor.py` get the new
  keyword-only parameter. For the 29 non-SSH executors it is unused — name it
  `device_sessions` everywhere anyway (consistent grep target), no `**kwargs`
  loophole.
- `StepRunner._execute_step` passes `device_sessions=self.device_sessions`.

Alternative considered and rejected: a `StepServices` dataclass bundling
`artifact_service` + pool + future services. Cleaner long-term, but a much larger
mechanical diff (every executor body references `artifact_service`); do it later
if a third service ever appears.

### 5.4 `services/execution/step_runner.py`

1. `StepRunner.__init__(self, db)`: create the pool —
   ```python
   self.device_sessions = DeviceSessionPool(
       max_workers=settings.netmiko_pool_workers,
       enabled=settings.netmiko_session_pooling,
   )
   ```
2. Add lifecycle methods (thin delegates):
   ```python
   async def suspend_device_sessions(self) -> None: await self.device_sessions.suspend()
   async def close_device_sessions(self) -> None:  await self.device_sessions.close()
   ```
3. `_execute_step`: add `device_sessions=self.device_sessions` to the executor
   call.
4. **Ownership rule (document in class docstring):** whoever instantiates
   `StepRunner` must `finally: await runner.close_device_sessions()`. The three
   instantiation sites are listed in 5.5/5.6.

### 5.5 `hatchet/workflows/workflow_run.py`

Three concerns: cleanup, durable waits, phase boundaries.

1. **Phase 1** (`execute_steps`, first `SessionLocal` block): wrap the
   `_run_steps_until_fan_out_or_done` call:
   ```python
   runner = StepRunner(db)
   try:
       final_status, fan_out, run = await _run_steps_until_fan_out_or_done(…)
   finally:
       await runner.close_device_sessions()
   ```
   Close (not suspend) even on the fan-out path — children build their own pools,
   and phase 2/3 hold no device connections. Also close before the fan-out debug
   pause (`aio_wait_for_event` on `fan_out_label`) — already covered because that
   wait happens after the `finally` if structured as above; verify ordering when
   implementing (the debug fan-out pause currently sits *inside* the first
   `SessionLocal` block — restructure so `close_device_sessions()` runs before
   that wait).
2. **Debug-mode stepping** (`_run_steps_until_fan_out_or_done`): immediately
   before each `await ctx.aio_wait_for_event(…)`:
   ```python
   await runner.suspend_device_sessions()
   ```
   Sessions transparently reconnect on the next network step after resume.
3. **Phase 4** (`resume_after_join`): the fresh `StepRunner(db)` there gets the
   same `try/finally: close_device_sessions()` treatment.
4. **Approval gates** (`_dispatch_children`): no change needed — the orchestrator
   holds no device sessions during dispatch (children own their pools). Add an
   assertion-style comment so this stays true.

### 5.6 `hatchet/workflows/device_group_execution.py`

Wrap the `execute_subgraph` call:

```python
runner = StepRunner(db)
try:
    step_outcomes = await runner.execute_subgraph(…)
finally:
    await runner.close_device_sessions()
```

This is where reuse pays off most: a per-device child runs
`get-device-configs → parse → render → deploy` on **one** SSH session.

### 5.7 The three SSH executors

`workflow_steps/run_command/executor.py`,
`workflow_steps/get_device_configs/executor.py`,
`workflow_steps/deploy_rendered_template/executor.py`:

1. Replace `netmiko = NetmikoService()` with
   `netmiko = NetmikoService(pool=device_sessions)`.
2. Pass `credential_reference=credential_reference` into each
   `send_commands` / `get_configs` / `deploy_config` call (the pool needs it for
   the key; username/password still resolved once per step via
   `resolve_ssh_credential` exactly as today).
3. No other logic changes — per-device `asyncio.gather`, artifact storage, outcome
   splitting all stay identical.

### 5.8 The non-SSH executors

Mechanical: add `device_sessions: DeviceSessionPool` (type via
`TYPE_CHECKING` import to avoid pulling netmiko into pure steps) to the signature.
List below is 29 as of this plan's authoring; by implementation time two more
non-SSH steps (`get-from-config`, `show-summary`) had been added, bringing the
real total to 31 non-SSH + 3 SSH = 34 executors — same mechanical treatment.
List (from `STEP_REGISTRY`): add_to_ise, add_to_nautobot, compare_data,
config_to_attributes, fan_in, filter_output, get_from_list, get_git_devices,
get_ise_devices, get_ise_tacacs_key, get_nautobot_attributes,
get_nautobot_devices, git_clone, git_pull, git_push, list_contains,
log_attributes, log_message, merge_content, parse_cisco_config, reachable,
render_jinja_template, route_on_attribute, route_on_content,
set_default_attributes, store_artifact, update_attribute, update_ise_tacacs_key,
update_nautobot_device.

### 5.9 `core/config.py` — settings

```python
netmiko_session_pooling: bool = True   # kill switch → per-call sessions (old behavior)
netmiko_pool_workers: int = 10         # threads per pool (per execution segment)
netmiko_keepalive_seconds: int = 30    # paramiko transport keepalive
```

### 5.10 Documentation

- `doc/WORKFLOW-STEPS.md`: update the executor contract (new parameter), add a
  "Device sessions" subsection: pooling semantics, the base-state invariant
  (§3.4), fan-out boundary note, and the rule that executors must never store the
  pool or a session beyond the `execute()` call.
- `CLAUDE.md` "Adding a New Workflow Step": update the contract snippet.

---

## 6. Lifecycle Matrix (verify each during implementation)

| Scenario | Expected pool behavior |
|---|---|
| Normal linear run, 2 SSH steps, same credential | 1 connect per device total; both steps share the session; `close()` at run end |
| Two SSH steps, different `credential_reference` | 2 sessions per device (different keys) — both closed at end |
| SSH step → REST/transform steps → SSH step | Session idles with keepalive; second SSH step reuses it (or transparently reconnects if the device killed it) |
| Debug mode | `suspend()` before every step-gate wait; lazy reconnect after resume |
| Fan-out (per_device / chunked) | Parent pool closed before dispatch; each child has its own pool covering its subgraph; parent phase-4 pool covers post-join steps |
| Wait & Run approval gate | No sessions held during the gate (they live in children only) |
| Step raises / run fails | `finally` still closes everything; no leaked threads or sockets |
| Executor exception mid-command | Session lock released; `is_alive()` decides reuse vs reconnect on next acquire |
| `netmiko_session_pooling=False` | Behavior byte-for-byte like today (fresh session per call) |
| Worker process exits | OS closes sockets; nothing to do (verify no atexit hangs from executor threads — use `thread_name_prefix`, daemon semantics of `ThreadPoolExecutor.shutdown(wait=False, cancel_futures=True)` in `close()`) |

---

## 7. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Netmiko session used from two threads | Only access path is `run_on_device` under per-key `asyncio.Lock`; no raw session handed out |
| Device `exec-timeout` kills idle session | keepalive=30 + `is_alive()` reconnect-on-acquire |
| Half-open TCP after network blip | same (`is_alive()` sends a NOP; on failure → reconnect) |
| Session left in config mode by a buggy op | Invariant in §3.4 + debug-only guard (decided, §13.2): after each op run `check_config_mode()` when debug is active; normal runs skip the extra round-trip |
| Thread growth (slots × pool workers) | per-pool executor sized by setting; `stats()` logged at pool close for observability |
| Credential rotated mid-run | Live session unaffected; reconnect uses freshly resolved password (resolved per step). Document. |
| Secrets in memory longer | Password lives on the session object exactly as long as the segment — same exposure class as today's per-call flow; never in the pool key, never logged |
| Regression risk in ad-hoc API (`routers/netmiko.py`) | Untouched behaviorally in v1 (single-use pool or `enabled=False`), plus its per-request thread churn (§2.3) removed by deterministic executor shutdown |
| Emergency rollback | `netmiko_session_pooling=False` restores today's semantics without redeploying code changes beyond the setting |

---

## 8. Test Plan (write first — TDD)

New test file `backend/tests/test_device_session_pool.py` (unit, fake
`NetmikoDeviceSession` via monkeypatched factory — no real SSH):

1. `test_reuses_session_for_same_key` — two `run_on_device` calls, one connect.
2. `test_distinct_sessions_per_credential_reference` — different keys → two connects.
3. `test_reconnects_when_not_alive` — fake `is_alive() → False` → disconnect+connect once.
4. `test_suspend_disconnects_but_pool_survives` — suspend, then next call reconnects.
5. `test_close_is_idempotent_and_shuts_executor`.
6. `test_concurrent_acquire_same_key_serializes` — two coroutines, assert no interleaved ops (fake records call order) and exactly one connect.
7. `test_disabled_pool_matches_legacy_behavior` — `enabled=False` → connect+disconnect per call.
8. `test_suspend_never_raises` — session whose `disconnect()` raises.
9. `test_config_mode_guard_debug_only` — post-op `check_config_mode()` runs when
   debug is active and is skipped otherwise (§13.2).

Extend existing suites:

10. `test_step_runner_*`: executor call receives `device_sessions`; `close_device_sessions()` closes the pool.
11. `tests/test_debug_mode_stepping.py`: assert `suspend()` called before each debug wait (spy on the pool).
12. Executor tests for run_command / get_device_configs / deploy_rendered_template: same step twice in one runner → single connect per device (fake pool/service).
13. Orchestrator tests (`test_wait_and_run_dispatch.py` pattern): phase-1 pool closed before child dispatch.

Integration (manual, dev lab — record in PR test plan): one Cisco device,
workflow `get-device-configs → run-command → deploy-rendered-template`; verify via
device `show users` / logs that exactly **one** SSH login occurs; repeat in debug
mode (expect re-logins after each pause); repeat with fan-out on 2 devices.

Regression guards: `ruff check` on touched files; `python scripts/check_asyncio_run.py`.

---

## 9. Companion Work (separate PR, strongly recommended): replay idempotency

Not part of this change, but adjacent and higher-risk: `execute_steps` is a
**durable** task — after a worker crash Hatchet re-executes the function and only
replays memoized durable calls (`aio_wait_for_event`). The step walk itself is not
memoized, so completed steps (including config deployments!) would re-run against
real devices.

Outline for a follow-up plan:
1. On entry to the walk, load existing `WorkflowStepResult` rows for the run;
   treat nodes with terminal status as done and rehydrate `step_outcomes` from the
   persisted `output`.
2. Blocker to solve there: persisted outputs pass through
   `redact_secrets_in_data`, so contexts cannot be rehydrated faithfully today —
   either store an un-redacted copy server-side or re-resolve secrets on load.
3. **Fan-out re-dispatch**: the same caveat applies to child workflows.
   `child_workflow.aio_run(...)` in `_dispatch_children` is a plain awaited call,
   not a memoized durable operation — on replay the parent would re-dispatch
   **all** children, re-running deployments on devices that already received
   them. The follow-up must make dispatch resumable too: before dispatching,
   check which child results were already aggregated/persisted
   (`_aggregate_and_persist` with `final=False` already writes per-batch results
   for Wait & Run — reuse that as the checkpoint) and only dispatch the
   remainder. This is the strongest argument for prioritizing the follow-up:
   the blast radius of a replayed fan-out is every device in the run.
4. Until then: verify the retry/reassignment policy for `execute_steps` and prefer
   a loud failed run over silent re-execution.

The session pool neither worsens nor fixes this; sessions are simply rebuilt on
replay.

---

## 10. Out-of-Scope Cleanups Noticed (do opportunistically)

- `routers/netmiko.py` instantiates `NetmikoService()` per request → after this
  refactor it must construct a single-use pool; make sure the request handler
  closes it (`finally`). This also removes the per-request thread-pool churn (§2.3).
- `NetmikoService` no longer owning a thread pool means the class is nearly a thin
  namespace over the pool; consider folding its methods into `DeviceSessionPool`
  later and deleting the class (keep for now to minimize executor churn).

---

## 11. Future Work (explicitly deferred)

- **scrapli-asyncio** as the driver: native asyncio removes the thread executor
  entirely; the pool interface (`run_on_device`) is designed so the Netmiko-backed
  implementation can be swapped without touching executors.
- Per-step "requires fresh session" flag if a future step needs guaranteed clean
  session state.
- `reachable` step: optional SSH reachability probe via the pool (doubles as
  session pre-warming). Deferred from v1 (§13.3).
- Fan-out refinements (independent of sessions, recorded here from the same
  analysis): replace the per-parent `asyncio.Semaphore` in `_dispatch_children`
  with Hatchet concurrency keys on `DeviceGroupExecution` so `max_concurrency`
  is enforced globally across simultaneous runs (two parents fanning out today
  each get their own semaphore — combined device concurrency doubles); use
  Hatchet bulk-run APIs for child dispatch once device counts reach the
  hundreds.
- Worker-level sticky session cache across Hatchet tasks (Hatchet sticky
  assignment) — only if a real use case demands parent/child session sharing;
  significant complexity, weak payoff today.

---

## 12. Implementation Order

| # | Step | Touches | Gate |
|---|---|---|---|
| 1 | Pool unit tests (RED) + `DeviceSessionPool` + `connection.py` additions (GREEN) | new file, connection.py, tests | pool tests pass |
| 2 | Settings | core/config.py | — |
| 3 | `NetmikoService` refactor to pool-backed + `routers/netmiko.py` compatibility | service.py, routers/netmiko.py | existing netmiko router tests pass |
| 4 | Executor contract: signature added to all 32 executors + registry docstring | workflow_steps/*/executor.py, step_registry.py | grep confirms 32/32; test suite passes |
| 5 | `StepRunner` owns pool; call-site injection | step_runner.py | runner tests |
| 6 | Lifecycle wiring: try/finally + suspends in orchestrator & child | workflow_run.py, device_group_execution.py | debug/dispatch tests |
| 7 | SSH executors use the pool | 3 executors | reuse tests (one connect per device) |
| 8 | Docs (`WORKFLOW-STEPS.md`, `CLAUDE.md`) | docs | review |
| 9 | Manual lab verification (§8 integration) | — | `show users` shows single login |

Steps 1–3 are independent of 4–6 and can be reviewed as a first PR; 4–7 as a
second; docs+verification close it out.

---

## 13. Resolved Questions (decided 2026-07-26)

1. **Debug mode** → **suspend** before every node gate (not disabling pooling).
   Behavior stays uniform between normal and debug runs; sessions lazily
   reconnect after each resume. Wired in §5.5 item 2.
2. **Post-op config-mode guard** → **debug-only**: run `check_config_mode()`
   after each op only when debug is active; normal runs skip the extra prompt
   round-trip. See §7 risk table.
3. **`reachable` SSH probe / session pre-warming** → **not in v1**; stays ping
   only. Tracked under §11 Future Work.
4. **Pool `stats()` surfacing** → **logs-only for v1**: emitted once at pool
   close (`{"open", "created_total", "reconnects"}`); no `WorkflowRun` metadata
   or UI exposure.
