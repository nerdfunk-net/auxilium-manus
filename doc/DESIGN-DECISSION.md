The decision to run the whole workflow inside one Hatchet durable task was right — it's the standard "interpreter/orchestrator" pattern for user-designed graphs. More importantly: your SSH limitation is not caused by that decision — it's caused by it not being exploited. Because the entire run executes as one Python coroutine in one worker process, you are in the best possible position to hold an SSH session open across steps. The per-step reconnect is purely an implementation choice inside the executors (NetmikoService opens and tears down a session on every call — services/network/netmiko/service.py:205, with _session(...)). Splitting the run into one-Hatchet-task-per-canvas-step would make persistent connections impossible, not easier.

What the code does today

- hatchet/workflows/workflow_run.py defines one Hatchet workflow (WorkflowExecution) with a prepare task and a 24-hour execute_steps durable task. The canvas graph is walked in topological order inside that single task by StepRunner; durable waits (ctx.aio_wait_for_event) implement debug stepping and batch-approval gates.
- Fan-out spawns DeviceGroupExecution child workflows — one Hatchet task per device group — and the parent aggregates results.
- Every network step (run_command, get_device_configs, deploy_rendered_template) does connect → command → disconnect per device, per step.

Why the one-durable-task decision was right

Hatchet (like Temporal) registers workflows and their task DAGs in code at worker startup. Your users draw arbitrary graphs at runtime, so a 1:1 mapping of canvas node → Hatchet task would require either registering workflows dynamically per user workflow (re-registration churn, versioning pain when a workflow is edited mid-flight) or a generic "execute one node" task spawned per node with dependencies orchestrated by hand. That alternative buys you per-step visibility in the Hatchet dashboard and per-step retries, but costs you:

1. Serialization at every step boundary. Hatchet passes JSON between tasks. Your WorkflowContext (device dicts, command results, artifacts refs) would be serialized/deserialized per step — you already do this only at the fan-out boundary, which is the right granularity.
2. No shared state whatsoever. Tasks can land on different workers. A live SSH socket, a paramiko channel, a requests session — none of it survives a task boundary. Hatchet does have sticky assignment to pin child tasks to the parent's worker, but you'd be stashing sockets in worker-global state and praying the pin holds — fragile.
3. You'd rebuild step results in Postgres anyway (the Hatchet dashboard is not your product UI), which you already have.

This is exactly how other systems that need cross-step device sessions behave: Nornir runs the whole play in one process and caches connections per host across tasks; Ansible holds persistent connections per host for the duration of a play; Temporal-based workflow builders use the same interpreter-workflow pattern and either keep the whole device conversation inside one activity or use worker sessions to pin stateful work. Engines that do isolate steps into separate processes (Airflow, Prefect, n8n) simply cannot offer persistent device sessions — users there cram the whole SSH conversation into one node. You chose the architecture that permits the better answer.

How to get the persistent SSH session (no re-implementation needed)

The fix is a run-scoped connection pool, injected exactly like artifact_service already is:

1. DeviceConnectionPool keyed by (host, credential_ref, device_type), owned by the execute_steps invocation and passed through StepRunner._execute_step into executors (extend the executor signature the same way artifact_service travels today). NetmikoDeviceSession already separates connect()/disconnect() — executors just stop using the per-call with _session(...) context manager and ask the pool instead.
2. Lifetime = task invocation. Create the pool at the top of execute_steps (and independently inside each DeviceGroupExecution child task), close everything in a finally. Your motivating scenario — SSH in, call a REST API elsewhere, come back to the same session — works immediately, because those steps are just successive awaits in the same coroutine.
3. Close (or health-check) before durable waits. Debug pauses and Wait & Run approval gates can sit for hours; devices will drop idle SSH anyway (exec-timeout). Release connections before aio_wait_for_event and reconnect lazily after — with lazy connect() in the session class, "reconnect on next use if is_alive() is false" gives you this almost for free.
4. Thread affinity. Netmiko/paramiko sessions are not thread-safe. Today each call gets a fresh session in the thread pool, so it doesn't matter; with a pool you need a per-device lock (steps already serialize per device within asyncio.gather, so this is a small guard, not a redesign).
5. Fan-out is unaffected. Connections can't cross the parent→child Hatchet boundary, but children run the whole per-device subgraph (your steps 3–5: get config → render → deploy), which is precisely where reuse pays off. Each child pools its one device's connection across its steps.

If you later want native async instead of the thread-pool bridge, scrapli-asyncio slots into the same pool shape — but that's an optimization, not a prerequisite.

The one real weakness I'd fix first

It's not SSH — it's replay semantics. Durable tasks re-execute their function after a worker crash; only the durable calls (aio_wait_for_event) are memoized and replayed. Your step executions are not memoized, so a crash mid-run would re-execute already-completed steps against real devices — including config deployments. To actually cash in on the durability you're paying for, make the walk resumable: before executing a node, check its persisted WorkflowStepResult and skip/rehydrate completed nodes. One caveat there: persisted outputs go through redact_secrets_in_data, so faithful rehydration of the context needs the un-redacted outcome stored somewhere (or secrets re-resolved on load). Until that exists, I'd verify what retry/reassignment policy applies to execute_steps on worker death and consider pinning retries to zero so a crash fails the run loudly rather than silently re-pushing config.

Bottom line: keep the architecture. Add the run-scoped connection pool (a contained change to StepRunner, the executor signature, and NetmikoService), and address step idempotency on replay — that's the gap with real operational risk.