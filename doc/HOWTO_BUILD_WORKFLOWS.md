# How to Build Workflows: Designing for Throughput

This guide answers a question that comes up for any workflow that targets a large
device count: **when I run a step against hundreds of devices, how are they
actually processed, and what do I configure to make it fast without overloading
the devices or the worker?**

It uses one running example — a nightly configuration backup — to walk through
every option. For the full step contract and fan-out mechanics, see
[`doc/WORKFLOW-STEPS.md`](./WORKFLOW-STEPS.md) → **Fan-out execution**; this
document is the practical, example-driven companion to that reference.

---

## The example: backing up 300 devices overnight

A workflow with three nodes:

```
Get from Nautobot  →  Get Device Configs  →  Store Artifact (git)
   (300 devices)         (running-config)         (commit + push)
```

`Get from Nautobot` (`get-nautobot-devices`) resolves a filter to 300 devices.
`Get Device Configs` (`get-device-configs`) opens an SSH session to each device
and pulls its running config. `Store Artifact` commits all 300 files to a git
repository and pushes once.

The question is entirely about the middle node: **how many of those 300 SSH
sessions does `Get Device Configs` open at once, and in what order?**

---

## Option 1 — Fan-out disabled (the default)

Every inventory step (`get-nautobot-devices`, `get-git-devices`,
`get-ise-devices`, `get-from-list`) ships with fan-out **off** by default:

```python
"fan_out": {
    "enabled": False,
    "mode": "per_device",
    "chunk_size": 1,
    "max_concurrency": 0,
}
```

If you drop `Get from Nautobot` → `Get Device Configs` on the canvas and never
open the fan-out block, this is what you get. There is no batching at all: the
whole workflow runs once, as a single Hatchet task, with all 300 devices
sharing one `WorkflowContext`.

Inside that one execution, `get-device-configs`' executor does this
(`backend/workflow_steps/get_device_configs/executor.py:277-294`):

```python
results = await asyncio.gather(
    *[_fetch_device_logged(...) for device in context.devices]
)
```

**All 300 devices are dispatched concurrently, with no internal throttle.**
There is no "10 at a time" behavior anywhere in this path — that was never a
fan-out default; it was `HATCHET_WORKER_SLOTS` (see the callout below) being
misread as one.

```
┌─────────────────────────── one Hatchet task ───────────────────────────┐
│  Get Device Configs                                                    │
│                                                                        │
│   device 1   ─┐                                                        │
│   device 2   ─┤                                                        │
│   device 3   ─┤                                                        │
│      ...      ├─►  asyncio.gather()  ─►  all 300 SSH sessions at once  │
│   device 299 ─┤                                                        │
│   device 300 ─┘                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

**When this is fine:** small-to-medium device counts, or devices/jump hosts
that comfortably tolerate a burst of concurrent SSH sessions.

**When this bites you:** at 300 devices, you're asking for 300 simultaneous
SSH login attempts against your credential source, your TACACS+/RADIUS server,
and every device's SSH daemon (which itself usually caps concurrent sessions,
often well under 300) — all at the same instant. Expect timeouts, throttling,
and possibly locked-out accounts, not a fast backup.

> **A second, unrelated concurrency cap still applies.** The single Hatchet
> task above still has to be picked up and run by a worker process, and that
> worker will only run so many tasks at once — governed by `HATCHET_WORKER_SLOTS`
> (Settings → Hatchet → *Worker Slots*, default `10`). But that cap is
> **per worker process, shared by every workflow and workflow type currently
> running** — it does not carve your 300 devices into groups of 10. With
> fan-out disabled, this workflow is *one* task, so it either gets a slot and
> runs (dispatching all 300 devices at once, as above) or waits for a slot like
> any other task on that worker.

---

## Option 2 — Fan-out enabled

Turning fan-out on (in `Get from Nautobot`'s config panel, under **Fan Out**)
splits the 300 devices across independent Hatchet **child workflows**
(`DeviceGroupExecution`) instead of one shared execution. This is what actually
gives you controlled batching.

```
Get from Nautobot (fan_out.enabled = true)
        │
        ▼
   StepRunner.execute_all() sees fan-out → STOPS after the inventory step,
   returns a FanOutSignal
        │
        ▼
   _dispatch_children() splits 300 devices into groups, per `mode`/`chunk_size`,
   and runs the groups bounded by `max_concurrency`
        │
        ├──► child 1: Get Device Configs → (per its own group of devices)
        ├──► child 2: Get Device Configs → ...
        └──► child N: Get Device Configs → ...
        │
        ▼
   results merged back together, then Store Artifact runs ONCE on the union
   (only if a Fan In node sits before it — see the warning at the end)
```

Two independent knobs decide how those groups are built and released:

### `mode` — how devices are grouped into one child

| `mode` | Devices per child | What happens inside that child |
|---|---|---|
| `per_device` | 1 | `get-device-configs` sees a context with 1 device — nothing to `gather()` over. |
| `chunked` | `chunk_size` | `get-device-configs` sees a context with `chunk_size` devices — and still runs `asyncio.gather()` over **all of them at once**, same as Option 1, just on a smaller group. |

This is the detail that's easy to get backwards: **`chunk_size` is not a
concurrency limit.** It only decides how many devices are bundled into one
child's context. Whatever ends up in that context is still hit fully
concurrently, unthrottled, by the executor. A `chunk_size: 10` chunk is a
10-wide burst, not a paced trickle.

### `max_concurrency` — how many children run at once

This is the actual throttle. `_run_groups` (`backend/hatchet/workflows/workflow_run.py:566-587`)
implements it as a semaphore over the child-workflow calls:

```python
if max_concurrency <= 0:
    tasks = [child_workflow.aio_run(inp) for inp in child_inputs]
    return await asyncio.gather(*tasks, return_exceptions=True)   # unlimited

semaphore = asyncio.Semaphore(max_concurrency)
async def _run_one(inp):
    async with semaphore:
        return await child_workflow.aio_run(inp)
```

With a semaphore in play, this is a **rolling pool**, not a lockstep batch:
every child that finishes immediately frees a slot for the next one to start.
It is *not* "run 10, wait for all 10 to finish, then run the next 10" — devices
stream through continuously.

```
mode: per_device, max_concurrency: 10   (recommended shape for this example)

 time ──────────────────────────────────────────────────────────────►

 slot 1  [dev 1]───►[dev 11]──────►[dev 23]───►...
 slot 2  [dev 2]────────►[dev 12]─►[dev 24]───►...
 slot 3  [dev 3]──►[dev 13]───────►[dev 25]───►...
   ...
 slot 10 [dev 10]──────►[dev 20]──►[dev 30]───►...

 → never more than 10 SSH sessions open at once, but a slot never sits idle
   waiting for the other 9 to finish — the moment one device is done, the
   next queued device starts immediately.
```

### `max_concurrency: 0` isn't "safe unlimited" — it's a gap, not a limit

It's tempting to enable fan-out, set `mode: "per_device"`, and leave
`max_concurrency` at its default `0` ("unlimited") expecting the per-device
split alone to have tamed the problem. It hasn't — `0` skips the semaphore
branch entirely, so **all N devices are submitted as separate Hatchet child
tasks essentially simultaneously**, with no cap coming from this step at all:

```python
if max_concurrency <= 0:
    tasks = [child_workflow.aio_run(inp) for inp in child_inputs]
    return await asyncio.gather(*tasks, return_exceptions=True)   # no semaphore
```

This is not identical to fan-out being off — with fan-out off, all 300 SSH
sessions open inside *one* Python coroutine, guaranteed. With fan-out on and
`max_concurrency: 0`, 300 *separate Hatchet tasks* get queued instead, and
Hatchet itself won't run more of them at once than the worker process has
capacity for (`HATCHET_WORKER_SLOTS`, default `10` — Settings → Hatchet).

That can make `max_concurrency: 0` *look* safe in a typical single-worker dev
setup, where it quietly ends up around ~10 concurrent devices anyway — but
that's an accident of `HATCHET_WORKER_SLOTS`, which is a **global** cap shared
by every other workflow running on that worker, not something this step
controls or that's scoped to this run. Add a second worker process, or raise
`HATCHET_WORKER_SLOTS`, and the real concurrency ceiling rises with it — with
nothing in the step's own configuration reflecting that. Relying on it means
your device count's actual concurrency ceiling lives in worker deployment
config you may not be looking at, not in the workflow you're designing.

The config panel now flags this directly: with fan-out enabled and
`max_concurrency` left at `0`, a `!` warning appears reminding you that
concurrency is effectively determined by Worker Slots, not by this step (a
sibling `!` warning covers Option 1 too, appearing whenever fan-out is off
entirely). Set an explicit number — `10`–`20` for the 300-device example —
whenever you want the limit to actually live in the workflow, not in shared
worker capacity.

Compare that to `mode: chunked, chunk_size: 10, max_concurrency: 1`, which
*is* a strict wait-for-the-batch model, because each "slot" here is itself a
10-device burst that must fully complete before the next chunk starts:

```
mode: chunked, chunk_size: 10, max_concurrency: 1

 chunk 1 (devices 1-10)    [██████████ 10 concurrent SSH ██████████]
                                                                     │ waits
 chunk 2 (devices 11-20)                                            └►[██████████]
                                                                                  │ waits
 chunk 3 (devices 21-30)                                                         └►[██████████]
```

This shape is occasionally what you want (e.g. you need a `Fan In` per batch,
or you're deliberately throttling for a change window), but it is **not** a
smooth "10 at a time" pipeline — it's 10 devices bursting, then a full stop,
repeated.

### `approval.enabled` — a third, unrelated gate

If `fan_out.approval.enabled: true` (the **Wait & Run** feature), dispatch
groups are batched into sets of `approval.batch_size` and the run **pauses**
after each set until an operator clicks *Run next batch* in the UI — regardless
of `max_concurrency`. This is for canary/staged rollouts of risky changes
(e.g. a TACACS+ key), not for throughput tuning. Leave it `false` for a backup
job; you want continuous streaming, not an operator gate every N devices.

---

## What to actually set for a fast, safe 300-device backup

1. Enable fan-out on `Get from Nautobot`.
2. `mode: "per_device"` — one device per child, so nothing inside a single
   child can burst past what `max_concurrency` allows.
3. `max_concurrency: 10–20` — pick a number your devices' SSH daemons, your
   credential/TACACS+ source, and your network can sustain concurrently. Start
   at 10 and raise it if backups finish comfortably with no timeouts; lower it
   if you see auth throttling or connection failures.
4. `approval.enabled: false` — no operator gate; this is a routine backup, not
   a staged rollout.
5. Put a **Fan In** node between `Get Device Configs` and `Store Artifact`.
   `store-artifact (git)` opens one shared working tree per git source — if it
   ran once per child instead of once after the join, 300 children would race
   on `index.lock` and produce 300 single-file commits instead of one clean
   commit. See `doc/WORKFLOW-STEPS.md` → **Writing fan-out-safe steps**.

Final shape:

```
Get from Nautobot          Get Device Configs           Fan In        Store Artifact (git)
 (fan_out: per_device,  →   (runs once per device,   →  (rejoin)  →    (runs ONCE, all
  max_concurrency: 10)       10 in flight at a time)                    300 configs, one commit)
```

This gives you a continuous pipeline of ~10 devices in flight at any moment,
300 devices flowing through without ever waiting on a full batch to drain, and
exactly one git commit/push at the end.

---

## Quick decision table

| Your goal | Fan-out? | `mode` | `chunk_size` | `max_concurrency` |
|---|---|---|---|---|
| A handful of devices, simplicity over control | Off (default) | — | — | — |
| Hundreds of devices, fastest safe throughput | On | `per_device` | — | `10`–`20` |
| Devices must be processed in fixed-size batches with a hard pause between them for review | On | `per_device` or `chunked` | as needed | any, plus `approval.enabled: true` |
| A step genuinely needs several devices in one context together | On | `chunked` | small (e.g. 5) | set deliberately — remember `chunk_size × max_concurrency` is your real concurrent SSH ceiling |

And regardless of any of the above: `HATCHET_WORKER_SLOTS` (Settings →
Hatchet) is a **separate, global** cap on how many Hatchet tasks the worker
process runs at once, shared with every other workflow running on it at the
time. It is not a per-workflow setting and does not substitute for configuring
`max_concurrency` on a specific fan-out step.
