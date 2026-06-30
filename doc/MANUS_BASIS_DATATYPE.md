# Manus Basis Data Type

## Overview

All workflow steps in Auxilium Manus operate on a single shared data structure called
the **WorkflowContext**. Every step receives a WorkflowContext, does its work (adds
devices, populates config references, appends commands, enriches attributes), and returns
one or more **StepOutcome** values — each carrying an updated WorkflowContext routed
down a named edge.

This document defines the canonical shape of WorkflowContext, how it accumulates data as
it travels through a workflow, how **capability sets** on each node enforce that only
compatible steps can be connected at design time, and the rules step authors must follow.

---

## Design Goals

| # | Goal | Why it matters |
|---|------|----------------|
| G1 | **Single shared envelope** | Steps never need to know their neighbour's concrete shape. |
| G2 | **Design-time validation** | The canvas rejects invalid connections before anything runs. |
| G3 | **Content/metadata separation** | Large content (configs, command output) must not bloat the envelope or the DB. |
| G4 | **Explicit capabilities** | What a step requires/produces is declared data, not inferred. |
| G5 | **First-class failure** | Partial and total failures are representable and routable, never silent. |
| G6 | **Immutability** | Safe to fan out across parallel branches without hidden side effects. |
| G7 | **Deterministic merge** | Converging branches combine predictably with no data loss. |
| G8 | **Cheap persistence** | Each step result is small and serialisable; heavy bytes live in artifact storage. |

---

## Capability Model

A step does not require "a context of rank ≥ 3". It requires that **specific capabilities**
are present on the devices it operates on. Capabilities are an **unordered set**; the
compatibility check is `required ⊆ provided` — never a rank comparison.

```
PENDING_COMMANDS  does not imply  PARSED
RUNNING_CONFIG    does not imply  ATTRIBUTES
```

A rank system both allows connections that fail at runtime (false positives) and blocks
valid ones (false negatives). The subset check has neither problem.

### Compatibility rule

A connection from a source step to a target step is allowed **iff** every capability the
target requires is produced (or passed through) by the source:

```
required_capabilities ⊆ provided_capabilities
```

### Capabilities are tracked per device

Each `DeviceContext` tracks the capabilities it actually has. The context-level
"provided" set is the **intersection** across all devices — a downstream step can only
rely on a capability if *every* device has it. This makes partial enrichment explicit.

The asymmetry is intentional and must be covered by tests:
- **Per-device**: union — a device has a capability if *any* branch gave it.
- **Context-level guarantee**: intersection — what's safe for all downstream steps.

### Typed parser outputs

`PARSED` alone is too coarse — a step that needs BGP data must know BGP was parsed, not
just "something" was. Parser steps declare a **parser key**, and capability checks may be
parameterised:

```
requires_parsed: [bgp]   →  device.parsed must contain key "bgp"
```

The registry expresses this as `requires_parsed` / `produces_parsed` lists (see Registry
section).

---

## Content vs Metadata Separation

The envelope carries **small, structured metadata and references only**. Heavy or
free-form **content** lives in artifact storage and is referenced by an `ArtifactRef`.

| Lives in the envelope (metadata) | Lives in artifact storage (content) |
|----------------------------------|-------------------------------------|
| Device identity, attributes      | Running / startup config text       |
| Parsed structured data (bounded) | Raw command output                  |
| Capability flags, device status  | Generated config bundles, backups   |
| ArtifactRef pointers             | Reports, diffs                      |

A step that retrieves a running config:
1. Writes the config bytes to artifact storage via `ArtifactService`.
2. Stores an `ArtifactRef` on the device (`device.running_config_ref`).

Downstream steps that need the bytes resolve the ref through `ArtifactService`. The
envelope — and therefore every persisted step result — stays small.

> **Rule:** never inline content larger than a small bounded structure into the envelope.
> If it can grow with device config size, it is content and must be an `ArtifactRef`.

---

## The Canonical Python Types

All types live in `backend/models/workflow_context.py`. The full import block is shown
once here; individual snippets below omit it.

```python
# backend/models/workflow_context.py

from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, ConfigDict


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Capability(str, Enum):
    """A discrete, independently-acquired property of a DeviceContext."""
    IDENTITY          = "identity"          # id, name, hostname, driver  (source steps)
    ATTRIBUTES        = "attributes"        # nautobot attribute map
    RUNNING_CONFIG    = "running_config"    # running config retrieved (as ArtifactRef)
    STARTUP_CONFIG    = "startup_config"    # startup config retrieved
    PARSED            = "parsed"            # at least one parser ran
    PENDING_COMMANDS  = "pending_commands"  # build step queued commands


class ArtifactRef(BaseModel):
    """A pointer to content stored outside the envelope."""
    artifact_id: str           # storage key / DB id
    kind: str                  # "running_config" | "command_output" | "backup" | ...
    media_type: str = "text/plain"
    size_bytes: int | None = None
    sha256: str | None = None  # integrity / change detection
    created_at: str = Field(default_factory=_now_iso)


class CommandResult(BaseModel):
    """Metadata for one CLI command. Raw output is an ArtifactRef, not inlined."""
    node_id: str                               # graph node that issued this command
    command: str
    success: bool
    executed_at: str = Field(default_factory=_now_iso)
    output_ref: ArtifactRef | None = None      # bytes live in artifact storage
    summary: str | None = None                 # optional short, bounded excerpt


class DeviceStatus(str, Enum):
    PENDING  = "pending"
    OK       = "ok"
    FAILED   = "failed"
    SKIPPED  = "skipped"


class DeviceError(BaseModel):
    node_id: str    # graph node where the error occurred
    step_id: str    # step type e.g. "get-running-config"
    code: str       # "timeout" | "auth_failed" | "unreachable" | "parse_error" | ...
    message: str    # human-readable, safe to surface in the UI
    occurred_at: str = Field(default_factory=_now_iso)


class DeviceContext(BaseModel):
    """Everything the workflow knows about one device. Enriched in place by steps."""

    model_config = ConfigDict(extra="forbid")

    # --- Identity (populated by source steps: get-nautobot-devices, get-git-devices) ---
    id: str
    name: str
    hostname: str                      # bare SSH target — no CIDR mask (invariant)
    platform: str | None = None        # e.g. "Cisco IOS"
    network_driver: str | None = None  # netmiko driver key, e.g. "cisco_ios"
    primary_ip4: str | None = None     # may include /mask; hostname must not
    source: str = ""                   # "nautobot" | "git"
    source_id: str = ""                # ID of the configured source

    # --- Enrichment --------------------------------------------------------------
    attributes: dict[str, Any] = Field(default_factory=dict)
    # Nautobot attribute map: role, device_type, location, custom_fields,
    # interfaces, tags, config_context, etc.

    running_config_ref: ArtifactRef | None = None
    startup_config_ref: ArtifactRef | None = None

    parsed: dict[str, Any] = Field(default_factory=dict)
    # Keyed by parser key. Document each key in the producing step, e.g.:
    #   parsed["bgp"]   = {"neighbors": [{"peer": "10.0.0.1", "asn": 65001}]}
    #   parsed["vlans"] = [10, 20, 30]

    command_results: dict[str, list[CommandResult]] = Field(default_factory=dict)
    # Keyed by node_id → the list of CommandResults that node produced for this
    # device (one entry per command run). Merge replaces the whole list per node_id,
    # so it stays idempotent across diamond graphs while still supporting a step
    # that runs several commands per device.

    # --- Capability & status -----------------------------------------------------
    capabilities: set[Capability] = Field(default_factory=set)
    status: DeviceStatus = DeviceStatus.PENDING
    errors: list[DeviceError] = Field(default_factory=list)
    # errors is append-only. Dedupe on merge by (node_id, step_id) pair.


class WorkflowContext(BaseModel):
    """The single envelope that flows along every edge of the workflow graph."""

    model_config = ConfigDict(extra="forbid")

    # --- Invariant execution metadata (set once by the engine) -------------------
    run_id: str
    workflow_id: str
    schema_version: int = 1

    # --- Core device map (keyed by device id) ------------------------------------
    devices: dict[str, DeviceContext] = Field(default_factory=dict)
    # Each source step populates this map. Subsequent steps enrich individual
    # DeviceContext entries. Steps never replace the entire devices dict.

    # --- Pending commands (keyed by device id, then by node id) ------------------
    pending_commands: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    # Structure: { device_id: { node_id: ["cmd1", "cmd2", ...] } }
    # Keying by node_id makes merge idempotent — the same node's commands can
    # never be counted twice even in a diamond-shaped graph.
    # send-config flattens per device in TOPOLOGICAL order of the producing nodes
    # before sending (NOT lexical node_id order): config push order is significant
    # (e.g. an ACL must be defined before it is referenced), so commands must be
    # applied in the order their build nodes ran. The engine supplies the
    # topological node ordering; see "Pending command ordering" below.

    # --- Namespaced scratch space ------------------------------------------------
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Keys must be namespaced by node_id to avoid collisions:
    #   metadata["<node-id>.summary"]    = {"total_peers": 42}
    #   metadata["<node-id>.violations"] = [...]

    def provided_capabilities(self) -> set[Capability]:
        """Capabilities present on *every* device — the safe downstream guarantee.

        Returns the full Capability set if devices is empty (vacuously true).
        Empty inventory is treated as a no-op, not a capability failure.
        """
        if not self.devices:
            return set(Capability)
        sets = [d.capabilities for d in self.devices.values()]
        return set.intersection(*sets)

    def provided_parsed_keys(self) -> set[str]:
        """Parser keys present on *every* device — the safe downstream guarantee.

        Mirrors provided_capabilities(): intersection across devices. The empty
        inventory case is never reached by the pre-step guard (it skips empty maps
        as a no-op), so an empty set is returned here.
        """
        if not self.devices:
            return set()
        sets = [set(d.parsed.keys()) for d in self.devices.values()]
        return set.intersection(*sets)


class StepOutcome(BaseModel):
    """A named exit path from a step, carrying the enriched context."""
    name: str                 # "success" | "failure" | "ios" | "nxos" | ...
    context: WorkflowContext
```

---

## Executor Contract

```python
# backend/workflow_steps/{step_id}/executor.py

from typing import Any
from models.workflow_context import WorkflowContext, StepOutcome
from core.models.runs import WorkflowRun
from services.artifacts import ArtifactService

async def execute(
    *,
    config: dict[str, Any],          # step's pluginConfig (incl. credential references)
    context: WorkflowContext,         # assembled & merged from all parents by the engine
    run: WorkflowRun,                 # ORM instance — use object_session(run) for DB
    artifact_service: ArtifactService,  # injected by the engine
    node_id: str,                     # this step's graph node id — use for keying
) -> list[StepOutcome]:
    ...
```

`artifact_service` and `node_id` are provided by the engine; step authors do not
instantiate them. `node_id` is the graph node's unique id (not the step type); use it
when writing to `pending_commands`, `command_results`, `errors`, and `metadata`.

- The engine assembles the input context by `merge()`-ing all parent step results, then
  calls `execute()`. Steps never call other steps directly.
- A simple linear step returns `[StepOutcome(name="success", context=...)]`.
- A branching step returns multiple outcomes; the engine routes each along the edge bound
  to that outcome handle.
- **Credentials** are passed as references in `config` (e.g. `config["credential_ref"]`),
  resolved through the credential service inside the step. Credentials never live in the
  envelope (which is persisted).

### Empty inventory

If `context.devices` is empty (upstream produced no devices, or all were routed to a
`failure` edge), the pre-step guard is skipped. The step must check for an empty device
map and return a `success` outcome immediately with the context unchanged. This is a
no-op, not a failure.

```python
if not context.devices:
    return [StepOutcome(name="success", context=context)]
```

### Authoring rules (mandatory)

1. **Never mutate** the received context — return new instances via `model_copy(update={...})`.
2. **Populate only your fields** — never clear another step's data.
3. **Add capabilities** to each device you *successfully* enriched.
4. **On per-device runtime failure** — set `status=FAILED`, append a `DeviceError` (with
   your `node_id` and `step_id`), continue to the next device. Do not raise.
5. **Success outcome carries only successfully enriched devices.** Failed devices go only
   on the `failure` outcome. The `success` context must satisfy
   `step.produces ⊆ provided_capabilities()` of that context.
6. **Raise `ValueError`** for config errors or missing required capabilities (design bug).
   Raise `RuntimeError` for unexpected internal failures.
7. **Store content as `ArtifactRef`** — never inline config text or command output.
8. **Namespace `metadata` and `pending_commands` keys** with your `node_id`.

Rule 5 is the most critical: mixing enriched and failed devices in the `success` outcome
causes `provided_capabilities()` to return the intersection (which excludes the
new capability), so every downstream step will fail its pre-step guard.

### Error contract

| Situation | Action |
|-----------|--------|
| Step is misconfigured | `raise ValueError(...)` → engine marks step failed |
| Unexpected internal error | `raise RuntimeError(...)` → engine marks step failed |
| Individual device unreachable / auth failed | `status=FAILED`, `errors.append(DeviceError(...))`, continue |
| Individual device parse error | `status=FAILED`, `errors.append(DeviceError(...))`, continue |

Raising is reserved for whole-step failures. Per-device failures are data, not exceptions.

### Post-step guard (`touched_by_step` defined)

After a step returns, the engine checks:

```python
# "touched" = devices present in the success outcome that the step attempted to enrich
# (i.e. devices from context.devices that are now in success_outcome.context.devices)
# See "Runtime Validation Guards" for the canonical guard, which also enforces
# `consumes` (a consumed capability must NOT remain on the success path).
touched = set(success_outcome.context.devices.keys()) & set(context.devices.keys())
for device_id in touched:
    device = success_outcome.context.devices[device_id]
    assert step.produces.issubset(device.capabilities), (
        f"Step {step_id} declared produces={step.produces} "
        f"but device {device_id} only has {device.capabilities}"
    )
```

This catches steps that return a device on the success path without having added the
declared capability — a bug in the step implementation, not in the workflow graph.

---

## Executor Examples

The examples below show the full pattern. `artifact_service` and `node_id` are received
as parameters (see Executor Contract above).

### get-nautobot-devices (source step)

```python
async def execute(*, config, context, run, artifact_service, node_id) -> list[StepOutcome]:
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    devices_raw = await fetch_devices_from_nautobot(config)

    def bare_host(ip: str | None) -> str:
        """Strip CIDR mask for the SSH target hostname."""
        return ip.split("/")[0] if ip else ""

    new_devices = {
        d.id: DeviceContext(
            id=d.id,
            name=d.name,
            hostname=bare_host(d.primary_ip4) or d.name,
            platform=d.platform,
            network_driver=d.network_driver,
            primary_ip4=d.primary_ip4,
            source="nautobot",
            source_id=config["nautobot_source_id"],
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        for d in devices_raw
    }

    new_context = context.model_copy(
        update={"devices": {**context.devices, **new_devices}}
    )
    return [StepOutcome(name="success", context=new_context)]
```

### get-running-config

```python
async def execute(*, config, context, run, artifact_service, node_id) -> list[StepOutcome]:
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    for device_id, device in context.devices.items():
        try:
            config_text = await fetch_running_config(device, config)
            ref = await artifact_service.store(
                content=config_text,
                kind="running_config",
                device_id=device_id,
                run_id=context.run_id,
            )
            success_devices[device_id] = device.model_copy(update={
                "running_config_ref": ref,
                "capabilities": device.capabilities | {Capability.RUNNING_CONFIG},
                "status": DeviceStatus.OK,
            })
        except (TimeoutError, AuthError) as exc:
            err = DeviceError(
                node_id=node_id,
                step_id="get-running-config",
                code=type(exc).__name__.lower(),
                message=str(exc),
            )
            failed_devices[device_id] = device.model_copy(update={
                "status": DeviceStatus.FAILED,
                "errors": [*device.errors, err],
            })

    # SUCCESS carries only enriched devices — never mix with failed ones (see rule 5).
    success_ctx = context.model_copy(update={"devices": success_devices})
    failure_ctx = context.model_copy(update={"devices": failed_devices})

    outcomes = [StepOutcome(name="success", context=success_ctx)]
    if failed_devices:
        outcomes.append(StepOutcome(name="failure", context=failure_ctx))
    return outcomes
```

### parse-bgp (parser step)

```python
async def execute(*, config, context, run, artifact_service, node_id) -> list[StepOutcome]:
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    updated: dict[str, DeviceContext] = {}
    for device_id, device in context.devices.items():
        if device.running_config_ref is None:
            updated[device_id] = device
            continue
        config_text = await artifact_service.resolve(device.running_config_ref)
        bgp_data = parse_bgp(config_text)
        updated[device_id] = device.model_copy(update={
            "parsed": {**device.parsed, "bgp": bgp_data},
            "capabilities": device.capabilities | {Capability.PARSED},
        })
    new_ctx = context.model_copy(update={"devices": updated})
    return [StepOutcome(name="success", context=new_ctx)]
```

### build-config (command-building step)

```python
async def execute(*, config, context, run, artifact_service, node_id) -> list[StepOutcome]:
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    new_pending = {k: dict(v) for k, v in context.pending_commands.items()}
    updated: dict[str, DeviceContext] = {}

    for device_id, device in context.devices.items():
        commands = generate_commands(device, config)
        # Key by node_id — idempotent across diamond merges
        device_cmds = new_pending.setdefault(device_id, {})
        device_cmds[node_id] = commands
        updated[device_id] = device.model_copy(update={
            "capabilities": device.capabilities | {Capability.PENDING_COMMANDS},
        })

    new_ctx = context.model_copy(update={
        "devices": updated,
        "pending_commands": new_pending,
    })
    return [StepOutcome(name="success", context=new_ctx)]
```

---

## How Data Flows Through a Workflow

Each step receives the fully accumulated context from all its upstream predecessors. The
StepRunner merges contexts from multiple parents using `merge()` before calling the next
step.

### Linear flow

```
[get-nautobot-devices] ──→ [get-running-config] ──→ [parse-bgp] ──→ [build-config] ──→ [send-config]
   produces: IDENTITY          +RUNNING_CONFIG         +PARSED         +PENDING_CMDS     drains cmds
   status: OK                  failed → failure edge                                    results stored
```

At each step the StepRunner:
1. Assembles a `WorkflowContext` by `merge()`-ing the outputs of all parent nodes.
2. Runs the pre-step capability guard.
3. Calls the executor with the merged context.
4. Runs the post-step capability guard on the success outcome.
5. Persists each returned `StepOutcome` and routes each context to the edges bound to
   that outcome handle.

### Branching and failure routing

```
[get-running-config]
  ├── success ──→ [parse-bgp] ──→ [build-config] ──→ [send-config]
  └── failure ──→ [notify-team]
```

Each outcome carries the same envelope type — only the routing and the device subset differ.

---

## Immutability and Merge

### Immutability

Steps **must not mutate** the context they receive. Use `model_copy(update={...})` to
build the modified copy. Because content is referenced via `ArtifactRef` rather than
inlined, copies are small even for large device fleets.

### Deterministic merge

When branches converge, the engine merges parent contexts:

```python
def merge(contexts: list[WorkflowContext]) -> WorkflowContext: ...
```

| Field | Rule |
|-------|------|
| `run_id`, `workflow_id`, `schema_version` | Must be identical; mismatch → `ValueError`. |
| `devices` | Union by device id. For the same id, merge `DeviceContext` field-by-field (below). |
| `pending_commands` | Dict-union per device, then dict-union per node_id within each device. Idempotent: the same node's commands are never duplicated even in a diamond graph. |
| `metadata` | Shallow merge by key; conflict → raise unless values are equal. |

**DeviceContext merge per id:**

| Field | Rule |
|-------|------|
| Scalar identity fields | Must be equal or one side `None`; conflict → record `DeviceError`, keep first parent's value. |
| `attributes`, `parsed` | Shallow key-union; conflicting keys raise unless equal. |
| `*_config_ref` | Take the non-None value; conflict (both non-None and different) → raise. |
| `command_results` | Dict-union by `node_id`; each value is the node's full `list[CommandResult]`. The same `node_id` always carries the same list, so union is idempotent; conflict (same node_id, different list) → raise. |
| `capabilities` | Union — a device has a capability if any branch gave it. |
| `status` | Worst-case wins: `FAILED` > `SKIPPED` > `PENDING` > `OK`. |
| `errors` | Concatenate; dedupe by `(node_id, step_id)` pair. |

#### Why pending_commands uses node_id keys

In a diamond graph, two branches B and C both inherit ancestor A's `pending_commands`.
A naïve list concatenation at the merge point D would double-count A's commands. Keying
by `node_id` makes the dict-union idempotent: `{A: [...]}` merged with `{A: [...]}` is
still `{A: [...]}`. This is why both `pending_commands` (context level) and
`command_results` (device level) are dicts keyed by node_id rather than plain lists.

#### Pending command ordering

Keying by `node_id` solves double-counting but discards ordering — and config push
order is significant. `send-config` must therefore flatten each device's
`{node_id: [cmds]}` map in **topological order of the producing nodes**, never in
lexical `node_id` order (node ids are opaque and unrelated to graph order).

The engine already computes a topological ordering of the graph to drive execution; it
passes that node ordering to `send-config` (e.g. via `config` or a context helper) so the
step can sort the contributing `node_id`s by their position in that ordering before
concatenating. Two build nodes that must run in a fixed sequence must therefore have an
explicit edge between them (or a shared chain) so the topological order is well-defined;
commands from unordered parallel build nodes have no guaranteed relative order and must
not depend on one.

---

## Step Registry — Capability Declarations

Each step in `registry.yaml` declares the capabilities it **requires** and **produces**,
plus its named **outcomes**. The frontend loads this at boot and uses it for canvas
validation and palette rendering.

```yaml
# backend/workflow_steps/registry.yaml

schema_version: 1

plugins:
  - id: get-nautobot-devices
    name: Get Devices from Nautobot
    description: Fetches a filtered device list from a Nautobot source.
    artifact_type: inventory_selector
    directory: get_nautobot_devices
    enabled: true
    requires: []               # source node — takes no upstream context
    produces: [identity]
    outcomes:
      - name: success
      - name: failure

  - id: get-git-devices
    name: Get Devices from Git
    description: Reads device definitions from a Git repository.
    artifact_type: inventory_selector
    directory: get_git_devices
    enabled: true
    requires: []
    produces: [identity]
    outcomes:
      - name: success
      - name: failure

  - id: get-nautobot-attributes
    name: Get Nautobot Attributes
    description: Enriches devices with full attribute data from Nautobot.
    artifact_type: configuration_retrieval
    directory: nautobot_attributes
    enabled: true
    requires: [identity]
    produces: [attributes]
    outcomes:
      - name: success
      - name: failure

  - id: get-running-config
    name: Get Running Config
    description: Connects to each device via SSH and retrieves the running configuration.
    artifact_type: configuration_retrieval
    directory: get_running_config
    enabled: true
    requires: [identity]
    produces: [running_config]
    outcomes:
      - name: success
      - name: failure

  - id: get-startup-config
    name: Get Startup Config
    description: Retrieves the startup configuration from each device.
    artifact_type: configuration_retrieval
    directory: get_startup_config
    enabled: true
    requires: [identity]
    produces: [startup_config]
    outcomes:
      - name: success
      - name: failure

  - id: parse-bgp
    name: Parse BGP
    description: Extracts BGP neighbour data from the running configuration.
    artifact_type: configuration_retrieval
    directory: parse_bgp
    enabled: true
    requires: [running_config]
    produces: [parsed]
    produces_parsed: [bgp]
    outcomes:
      - name: success

  - id: build-config
    name: Build Config Commands
    description: Generates configuration commands from device data or templates.
    artifact_type: command_execution
    directory: build_config
    enabled: true
    requires: [identity]
    produces: [pending_commands]
    outcomes:
      - name: success

  - id: send-config
    name: Send Config to Devices
    description: Pushes pending_commands to each device via SSH.
    artifact_type: command_execution
    directory: send_config
    enabled: true
    requires: [pending_commands]
    consumes: [pending_commands]   # drains the queue; capability is removed after
    produces: []                   # adds command_results (content), no new capability
    outcomes:
      - name: success
      - name: failure
```

`requires: []` marks a **source node** — it has no input handle on the canvas.
Each entry in `outcomes` maps to one output handle.

**`requires` vs `consumes` vs `produces`:**
- `requires` — capabilities that must be present on the input edge (read-only gate).
- `produces` — capabilities the step *adds* to the devices on its success outcome.
- `consumes` — capabilities the step *removes* after it runs, because it drains the
  underlying data. `send-config` consumes `pending_commands`: it requires the queue to be
  present, drains it, and clears the capability so a downstream step cannot assume commands
  are still queued. Most steps have an empty `consumes`. A step's success outcome therefore
  guarantees `(provided_on_input ∪ produces) \ consumes`.

`consumes` defaults to `[]` when omitted.

At runtime the step is responsible for making its returned context match its declared
`consumes`: when `send-config` drains `pending_commands` it must also remove
`Capability.PENDING_COMMANDS` from each device it processed (and empty that device's
`pending_commands` entry). The engine asserts this in the post-step guard — a device on the
success path must not retain a consumed capability:

```python
for device_id in touched:
    device = success_outcome.context.devices[device_id]
    leaked = set(step.consumes) & device.capabilities
    assert not leaked, f"Step {step_id} declared consumes={step.consumes} but {leaked} remain"
```

---

## Canvas — Connection Validation

### TypeScript capability type

The TypeScript `Capability` union must stay in sync with the Python `Capability` enum.
**Do not maintain these by hand.** Either generate the TypeScript union from `registry.yaml`
(or from the Python enum) at build time, or add a contract test that asserts the two sets
are identical. The chosen approach must be documented before the first step ships.

```typescript
// frontend/src/lib/capability-types.ts
// AUTO-GENERATED from backend/models/workflow_context.py — do not edit by hand

export type Capability =
  | "identity"
  | "attributes"
  | "running_config"
  | "startup_config"
  | "parsed"
  | "pending_commands"

export interface Provided {
  capabilities: Capability[]
  parsedKeys: string[]        // parser keys guaranteed on this edge (e.g. ["bgp"])
}

export interface Required {
  capabilities: Capability[]
  parsedKeys: string[]        // parser keys this step needs (requires_parsed)
}

export function isCompatible(provided: Provided, required: Required): boolean {
  const haveCaps = new Set(provided.capabilities)
  const haveKeys = new Set(provided.parsedKeys)
  const capsOk = required.capabilities.every((cap) => haveCaps.has(cap))
  const keysOk = required.parsedKeys.every((key) => haveKeys.has(key))
  return capsOk && keysOk   // required ⊆ provided, for BOTH capabilities and parser keys
}
```

Parser keys are validated alongside coarse capabilities. A step with
`requires_parsed: [bgp]` only connects to an upstream chain whose `transitiveProvides`
includes the `bgp` parser key — `PARSED` alone is not sufficient.

### React Flow connection validation

```typescript
// frontend/src/components/features/workflow-canvas/workflow-canvas.tsx

const isValidConnection = useCallback(
  (connection: Connection): boolean => {
    const sourceNode = nodes.find(n => n.id === connection.source)
    const targetNode = nodes.find(n => n.id === connection.target)
    if (!sourceNode || !targetNode) return false

    // Each outcome handle carries the transitive capabilities + parser keys it provides
    const outcome = sourceNode.data.outcomes.find(
      o => o.handle === connection.sourceHandle,
    )
    const provided: Provided = {
      capabilities: outcome?.transitiveProvides ?? [],
      parsedKeys: outcome?.transitiveParsedKeys ?? [],
    }
    const required: Required = {
      capabilities: targetNode.data.requires ?? [],
      parsedKeys: targetNode.data.requiresParsed ?? [],
    }

    return isCompatible(provided, required)
  },
  [nodes],
)
```

`transitiveProvides` (and `transitiveParsedKeys`) is what the upstream chain guarantees on
that specific outcome handle. The canvas computes both per node at render time by walking
the chain: for each node, `provided_out = (provided_in ∪ produces) \ consumes`, and
`parsed_out = parsed_in ∪ produces_parsed`. `consumes` removes a capability (e.g.
`send-config` consuming `pending_commands`) so downstream nodes cannot rely on it.

### Node data shape

```typescript
// frontend/src/components/features/workflow-canvas/types/node-data.ts

import { Capability } from "@/lib/capability-types"

export interface OutcomeHandle {
  name: string                      // "success" | "failure" | "ios" | ...
  handle: string                    // React Flow handle id
  transitiveProvides: Capability[]  // capabilities guaranteed on this edge
  transitiveParsedKeys: string[]    // parser keys guaranteed on this edge (e.g. ["bgp"])
}

export interface WorkflowNodeData {
  stepId: string                    // matches registry id, e.g. "get-nautobot-devices"
  label: string
  requires: Capability[]            // capabilities needed on the input edge
  requiresParsed: string[]          // parser keys needed on the input edge
  produces: Capability[]            // capabilities this step adds
  producesParsed: string[]          // parser keys this step adds
  consumes: Capability[]            // capabilities this step removes (e.g. pending_commands)
  outcomes: OutcomeHandle[]         // one per output handle
  pluginConfig: Record<string, unknown>
}
```

---

## Runtime Validation Guards

Design-time canvas checks are not enough. The engine validates at runtime too.

**Pre-step guard** — before calling a step, check for empty inventory (no-op) then assert
both coarse capabilities and parser keys:
```python
if context.devices:  # skip guard for empty inventory — no-op pass-through
    missing = set(step.requires) - context.provided_capabilities()
    if missing:
        raise ValueError(f"Step {step_id}: missing required capabilities {missing}")

    # Parser-key check — PARSED alone is not enough; the specific keys must exist
    # on every device (intersection), mirroring provided_capabilities().
    missing_keys = set(step.requires_parsed) - context.provided_parsed_keys()
    if missing_keys:
        raise ValueError(f"Step {step_id}: missing required parsed keys {missing_keys}")
```

`provided_parsed_keys()` is the intersection of `device.parsed.keys()` across all devices
(full/vacuous for an empty map), exactly like `provided_capabilities()`.

**Post-step guard** — after a step returns, check the success outcome only:
```python
# touched = devices the step attempted to enrich (present in both input and success output)
touched = set(success_outcome.context.devices) & set(context.devices)
for device_id in touched:
    device = success_outcome.context.devices[device_id]
    missing = set(step.produces) - device.capabilities
    if missing:
        raise RuntimeError(
            f"Step {step_id} declared produces={step.produces} but device "
            f"{device_id} is missing {missing} on the success path"
        )
    leaked = set(step.consumes) & device.capabilities
    if leaked:
        raise RuntimeError(
            f"Step {step_id} declared consumes={step.consumes} but device "
            f"{device_id} still has {leaked} on the success path"
        )
```

**Schema validation** — every persisted/loaded context is `model_validate`-d with
`extra="forbid"`. Unknown fields are rejected.

**Serialisation** — `set[Capability]` is not natively JSON. Serialise as a sorted list
and coerce back on load. Pin this with a round-trip test.

**Invariants (assert in tests, optionally at runtime in debug mode):**
- `hostname` contains no `/` (CIDR mask must be stripped in source steps).
- Every key in `pending_commands` exists in `devices`.
- `provided_capabilities()` equals the intersection of `device.capabilities` across all
  non-empty device maps.

---

## What Each Step Reads and Writes

Quick reference for step authors.

| Step                       | Requires            | Reads from context                            | Writes to context                                    |
|----------------------------|---------------------|-----------------------------------------------|------------------------------------------------------|
| `get-nautobot-devices`     | *(source)*          | nothing                                       | `devices[*]` identity fields + `IDENTITY`            |
| `get-git-devices`          | *(source)*          | nothing                                       | `devices[*]` identity fields + `IDENTITY`            |
| `get-nautobot-attributes`  | `IDENTITY`          | `devices[*].id`                               | `devices[*].attributes` + `ATTRIBUTES`               |
| `get-running-config`       | `IDENTITY`          | `devices[*].hostname`, `network_driver`       | `devices[*].running_config_ref` + `RUNNING_CONFIG`   |
| `get-startup-config`       | `IDENTITY`          | `devices[*].hostname`, `network_driver`       | `devices[*].startup_config_ref` + `STARTUP_CONFIG`   |
| `parse-bgp`                | `RUNNING_CONFIG`    | `devices[*].running_config_ref`               | `devices[*].parsed["bgp"]` + `PARSED`               |
| `filter-output`            | `IDENTITY`          | `devices[*].command_results` or `devices[*].parsed["{src}.merged_content"]` | `devices[*].parsed["{node_id}.filtered_output"]` + `PARSED` |
| `build-config`             | `IDENTITY`          | `devices[*]` (any fields needed by template)  | `pending_commands[*][node_id]` + `PENDING_COMMANDS`  |
| `send-config`              | `PENDING_COMMANDS`  | `pending_commands`, `devices[*].hostname`     | `devices[*].command_results[node_id]` (list); **consumes** `PENDING_COMMANDS` (drains & clears the queue) |

---

## Persistence and Schema Version

- Persist with `model_dump(mode="json")`; rehydrate with `model_validate`.
- `schema_version` is persisted with every step result. On load, if older than the
  current code, run a registered migration function before use.
- One step result is stored per node per run. Because content is referenced via
  `ArtifactRef`, a step result is the small enriched context — not a copy of every
  device's configuration.

---

## Open Decisions

1. **Artifact storage backend** — DB large-object, filesystem, or object store (S3/MinIO)?
   The `ArtifactRef` abstraction is backend-agnostic; pick one and implement an
   `ArtifactService` behind it.
2. **Per-device capability gating** — should a step run only on the subset of devices
   that satisfy its capability, instead of requiring all devices? A per-device gate is
   more flexible but more complex; recommended as a follow-up once the all-devices model
   is stable.
3. **Parsed-data size bound** — `parsed` is "structured but bounded". Define a soft cap
   and spill to an `ArtifactRef` above it if parsers produce large trees.
4. **Outcome fan-out semantics** — when a step emits both `success` and `failure`, the
   engine sends each outcome's context only down edges bound to that outcome handle.
   Confirm this is enforced before the first branching step is implemented.
5. **Capability enum sync** — choose between build-time codegen (Python enum → TS union)
   or a contract test. Must be decided before the second step type ships.

---

## Robustness Checklist

- [ ] Capabilities are a **set**; compatibility is **subset** (`required ⊆ provided`), never rank `>=`.
- [ ] Capabilities tracked per device; context guarantee = intersection across devices (vacuously full for empty inventory).
- [ ] Parser outputs keyed by parser key; `requires_parsed` / `produces_parsed` in registry.
- [ ] Parser keys validated at BOTH canvas (`isCompatible`) and runtime (pre-step guard via `provided_parsed_keys()`), not just coarse `PARSED`.
- [ ] `command_results` is `{ node_id: list[CommandResult] }` — supports multiple commands per node, idempotent on merge.
- [ ] `consumes` honoured: capability removed after the step (e.g. `send-config` drains `pending_commands`); `transitiveProvides = (in ∪ produces) \ consumes`.
- [ ] `pending_commands` flattened in TOPOLOGICAL node order (not lexical node_id) before sending.
- [ ] All bulky content is an `ArtifactRef`; envelope/step-results stay small.
- [ ] Per-device `status` + append-only `errors`; runtime failures never raise.
- [ ] **Success outcome carries only successfully enriched devices** — failed devices on `failure` only.
- [ ] Branching/failure expressed via multiple `StepOutcome`s; same envelope type, different device subset.
- [ ] `pending_commands` and `command_results` keyed by `node_id` — merge is idempotent, no diamond double-counting.
- [ ] Credentials passed as references in `config`, resolved in-step, never in the envelope.
- [ ] `merge()` is total and deterministic; per-device capability union, cross-device intersection.
- [ ] `model_config = extra="forbid"`; `set[Capability]` serialisation pinned by round-trip test.
- [ ] `schema_version` persisted with a migration hook.
- [ ] Pre-step guard skips empty inventory (no-op); checks `requires ⊆ provided_capabilities()` otherwise.
- [ ] Post-step guard checks `produces ⊆ device.capabilities` for `touched` devices on success path.
- [ ] `hostname` invariant (no CIDR mask) enforced at the source step.
- [ ] Capability enum sync strategy decided and documented before second step ships.

---

## Summary

```
WorkflowContext                                           schema_version: int
├── run_id, workflow_id                                   (invariant — set once by engine)
├── devices: { device_id: DeviceContext }
│   ├── id, name, hostname, platform,
│   │   network_driver, primary_ip4, source               ← source steps
│   ├── attributes: { ... }                               ← get-nautobot-attributes
│   ├── running_config_ref, startup_config_ref            ← get-*-config  (ArtifactRef)
│   ├── parsed: { parser_key: structured_data }           ← parse-* steps
│   │   ├── "{node_id}.merged_content": { artifact_ref, step_node_id, output_key, kind, size_bytes }
│   │   │                                                 ← merge-content
│   │   └── "{node_id}.filtered_output": { artifact_ref, step_node_id, output_key, kind, size_bytes }
│   │                                                     ← filter-output (cleaned JSON or text blob)
│   ├── command_results: { node_id: [ CommandResult ] }   ← send-* steps  (output as ArtifactRef)
│   ├── capabilities: set[Capability]                     ← added by each enriching step
│   ├── status: DeviceStatus                              ← set per operation
│   └── errors: [ DeviceError ]                           ← append-only, deduped by (node_id, step_id)
├── pending_commands: { device_id: { node_id: [cmds] } }  ← build-config, drained by send-config
└── metadata: { "<node-id>.key": value }                  ← namespaced scratch space

Compatibility check:  required_capabilities ⊆ provided_capabilities()
                      provided_capabilities() = ∩ device.capabilities  (full set if devices empty)
```
