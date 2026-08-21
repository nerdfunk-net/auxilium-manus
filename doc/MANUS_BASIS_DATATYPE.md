# Manus Basis Data Type

## Overview

All workflow steps in Auxilium Manus operate on a single shared data structure called
the **WorkflowContext**. Every step receives a WorkflowContext, does its work (adds
devices, populates config references, appends commands, enriches attributes), and returns
one or more **StepOutcome** values — each carrying an updated WorkflowContext routed
down a named edge. A step is invoked **once per node per run**, with the whole current
device set in that one `WorkflowContext` — never once per device (see
`doc/ARCHITECTURAL_OVERVIEW.md` → "Step execution granularity" for the execution-model
side of this; this document covers the data shape itself).

This document defines the canonical shape of WorkflowContext, how it accumulates data as
it travels through a workflow, how **capability sets** on each node enforce that only
compatible steps can be connected at design time, and the rules step authors must follow.

**Note on the worked examples below:** they use real, currently-registered steps
(`get-nautobot-devices`, `get-device-configs`, `parse-cisco-config`, `run-command`, ...),
simplified to show the pattern — not verbatim dumps of the real executors, which have
more error handling and step-specific detail. Follow the file paths given to see the
full implementation.

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

### Typed parser outputs: schema exists, no shipped step uses it yet

The intent, still expressed in the schema: `PARSED` alone is too coarse — a step that
needs BGP data should be able to declare that it needs *BGP specifically*, not just
"something" parsed. `PluginDefinition` (`backend/models/plugins.py`) has
`requires_parsed` / `produces_parsed` fields for exactly this, and the runtime machinery
is real: `WorkflowContext.provided_parsed_keys()` (intersection of `device.parsed.keys()`
across devices), `StepCapabilitySpec.requires_parsed` and the parsed-key check in
`pre_step_guard` (`backend/services/workflow_context/guards.py`), and a matching
`parsedKeys`/`isCompatible` check on the frontend (`frontend/src/lib/capability-types.ts`).

**In practice, no currently-registered step sets `requires_parsed` or `produces_parsed`**
(grep `backend/workflow_steps/registry.yaml` for either — zero hits). Every real
parser-producing step (`parse-cisco-config`, `get-pyats-config`, `get-pyats-snapshot`,
`render-jinja-template`, ...) instead exposes a **user-configured `output_key`** string
(e.g. `cisco_config`, `pyats_config`) and writes to `device.parsed[output_key]`.
Downstream steps read that key via a dotted-path expression
(`{output_key.field}` in Jinja, or `parsed.<output_key>.<field>` in Update Attribute's
`source_path`) resolved at **runtime**, not validated by the canvas at connect time — the
canvas only ever checks the coarse `PARSED` capability for these steps today. A workflow
author who mistypes an `output_key` reference gets a missing-value error at run time, not
a blocked connection at design time. See "Open Decisions" below.

---

## Content vs Metadata Separation

The envelope carries **small, structured metadata and references only**. Heavy or
free-form **content** lives in artifact storage and is referenced by an `ArtifactRef`.

| Lives in the envelope (metadata) | Lives in artifact storage (content) |
|----------------------------------|-------------------------------------|
| Device identity, attribute bags  | Running / startup config text       |
| Parsed structured data (bounded) | Raw command output                  |
| Capability flags, device status  | Generated config bundles, backups   |
| ArtifactRef pointers             | Reports, diffs, pyATS Genie snapshots |

A step that retrieves a running config:
1. Writes the config bytes to artifact storage via `ArtifactService`.
2. Stores an `ArtifactRef` on the device (`device.running_config_ref`).

Downstream steps that need the bytes resolve the ref through `ArtifactService`. The
envelope — and therefore every persisted step result — stays small.

> **Rule:** never inline content larger than a small bounded structure into the envelope.
> If it can grow with device config size, it is content and must be an `ArtifactRef`.

`ArtifactService` currently has one real backend, `FilesystemArtifactService`
(`backend/services/artifacts/filesystem_artifact_service.py`), plus an in-memory
implementation for tests; the abstract interface (`store`/`resolve`) stays backend-agnostic
if an object-store backend is added later.

---

## The Canonical Python Types

All types live in `backend/models/workflow_context.py`. This is the actual current file,
shown in full; individual snippets below omit the shared import block.

```python
# backend/models/workflow_context.py

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Capability(StrEnum):
    """A discrete, independently-acquired property of a DeviceContext."""
    IDENTITY          = "identity"          # id, name, hostname, driver  (source steps)
    ATTRIBUTES        = "attributes"        # at least one attribute_bags entry populated
    RUNNING_CONFIG    = "running_config"    # running config retrieved (as ArtifactRef)
    STARTUP_CONFIG    = "startup_config"    # startup config retrieved
    PARSED            = "parsed"            # at least one parser ran
    PENDING_COMMANDS  = "pending_commands"  # queued commands awaiting a drain step (unused today — see "Open Decisions")
    PYATS_TESTBED     = "pyats_testbed"     # pyATS shim device/credential bundle (add-pyats-testbed)


class ArtifactRef(BaseModel):
    """A pointer to content stored outside the envelope."""
    model_config = ConfigDict(extra="forbid")

    artifact_id: str           # storage key / DB id
    kind: str                  # "running_config" | "command_output" | "backup" | ...
    media_type: str = "text/plain"
    size_bytes: int | None = None
    sha256: str | None = None  # integrity / change detection
    created_at: str = Field(default_factory=now_iso)


class CommandResult(BaseModel):
    """Metadata for one CLI command. Raw output is an ArtifactRef, not inlined."""
    model_config = ConfigDict(extra="forbid")

    node_id: str                               # graph node that issued this command
    command: str
    success: bool
    executed_at: str = Field(default_factory=now_iso)
    output_ref: ArtifactRef | None = None      # bytes live in artifact storage
    summary: str | None = None                 # optional short, bounded excerpt


class DeviceStatus(StrEnum):
    PENDING  = "pending"
    OK       = "ok"
    FAILED   = "failed"
    SKIPPED  = "skipped"


class DeviceError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str    # graph node where the error occurred
    step_id: str    # step type e.g. "get-device-configs"
    code: str       # "timeout" | "auth_failed" | "unreachable" | "parse_error" | ...
    message: str    # human-readable, safe to surface in the UI
    occurred_at: str = Field(default_factory=now_iso)


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
    attribute_bags: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Namespaced attribute maps, keyed by source/producer, e.g.:
    #   attribute_bags["nautobot"]      = {role, device_type, location, custom_fields,
    #                                       interfaces, tags, config_context, ...}
    #   attribute_bags["tacacs"]        = {shared_secret: <sealed>, ...}
    #   attribute_bags["pyats_testbed"] = {pyats_source_id, host, os, username,
    #                                       password: <sealed>}  (add-pyats-testbed)
    #   attribute_bags["run_input"]     = {<static_attributes the operator supplied>}
    # "run_input" is a reserved bag name seeded by the engine (see
    # doc/WORKFLOW-STEPS.md → "Static attributes"). update-attribute and other
    # generic writers may create/extend any other bag; reads use dotted-path
    # expressions like {bag_name.field} (services/workflow_context/attribute_path.py).
    # Sensitive leaves (e.g. attribute_bags["tacacs"]["shared_secret"]) are stored
    # as sealed envelopes, never cleartext — see doc/WORKFLOW-STEPS.md →
    # "Secret-valued attributes".

    running_config_ref: ArtifactRef | None = None
    startup_config_ref: ArtifactRef | None = None

    parsed: dict[str, Any] = Field(default_factory=dict)
    # Keyed by a per-step, user-configured output_key (not a fixed parser name —
    # see "Typed parser outputs" above). Document the shape in the producing step:
    #   parsed["cisco_config"]   = {"hostname": ..., "vlans": [...], ...}  ← parse-cisco-config
    #   parsed["pyats_config"]   = {"running": {...}}                     ← get-pyats-config

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

    # set[Capability] is not natively JSON — sorted list on the wire, coerced back
    # into a set on load. This is the round-trip pinned by the Serialisation rule below.
    @field_serializer("capabilities")
    def serialize_capabilities(self, capabilities: set[Capability]) -> list[str]:
        return sorted(cap.value for cap in capabilities)

    @field_validator("capabilities", mode="before")
    @classmethod
    def parse_capabilities(cls, value: Any) -> set[Capability]:
        if value is None:
            return set()
        if isinstance(value, set):
            return {Capability(item) if not isinstance(item, Capability) else item for item in value}
        if isinstance(value, (list, tuple)):
            return {Capability(item) for item in value}
        raise TypeError(f"capabilities must be a set or list, got {type(value)!r}")


class WorkflowContext(BaseModel):
    """The single envelope that flows along every edge of the workflow graph."""

    model_config = ConfigDict(extra="forbid")

    # --- Invariant execution metadata (set once by the engine) -------------------
    run_id: str
    workflow_id: str
    schema_version: int = 2

    # --- Core device map (keyed by device id) ------------------------------------
    devices: dict[str, DeviceContext] = Field(default_factory=dict)
    # Each source step populates this map. Subsequent steps enrich individual
    # DeviceContext entries. Steps never replace the entire devices dict.

    # --- Pending commands (keyed by device id, then by node id) ------------------
    pending_commands: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    # Structure: { device_id: { node_id: ["cmd1", "cmd2", ...] } }
    # Real merge machinery exists for this field (see "Immutability and Merge"
    # below), but no shipped step currently populates or drains it — see "Open
    # Decisions". The one real command-execution step, run-command, builds and
    # sends commands in a single step instead of queuing them here.

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
    model_config = ConfigDict(extra="forbid")

    name: str                 # "success" | "failure" | "ios" | "nxos" | ...
    context: WorkflowContext
    summary: str | None = None  # short, bounded status text; surfaced in run/step UI and logs


def bare_hostname(primary_ip4: str | None, fallback: str) -> str:
    """Derive a bare SSH hostname from primary_ip4 (strip CIDR) or fallback.

    The one shared implementation of the hostname invariant (no CIDR mask) —
    every source step must call this instead of re-deriving it locally.
    """
    if primary_ip4:
        return primary_ip4.split("/")[0]
    return fallback
```

---

## Executor Contract

```python
# backend/workflow_steps/{step_id}/executor.py

from typing import Any
from models.workflow_context import WorkflowContext, StepOutcome
from core.models.runs import WorkflowRun
from services.artifacts import ArtifactService
from services.network.netmiko.session_pool import DeviceSessionPool

async def execute(
    *,
    config: dict[str, Any],          # step's pluginConfig (incl. credential references)
    context: WorkflowContext,         # assembled & merged from all parents by the engine
    run: WorkflowRun,                 # ORM instance — use object_session(run) for DB
    artifact_service: ArtifactService,  # injected by the engine
    node_id: str,                     # this step's graph node id — use for keying
    device_sessions: DeviceSessionPool,  # run-segment-scoped pooled SSH sessions
) -> list[StepOutcome]:
    ...
```

`artifact_service`, `node_id`, and `device_sessions` are provided by the engine; step
authors do not instantiate them. `node_id` is the graph node's unique id (not the step
type); use it when writing to `pending_commands`, `command_results`, `errors`, and
`metadata`. `device_sessions` is only used by SSH-issuing steps; non-SSH steps accept
and ignore it (import `DeviceSessionPool` under `TYPE_CHECKING` there — see
`doc/WORKFLOW-STEPS.md` → "Device sessions" for the full pooling contract).

- `StepRunner` (`backend/services/execution/step_runner.py`) calls `execute()` **exactly
  once per node per run**, after assembling the input context by `merge()`-ing all parent
  step results. Steps never call other steps directly. See
  `doc/ARCHITECTURAL_OVERVIEW.md` → "Step execution granularity" for what this implies
  about how a step should process `context.devices`.
- A simple linear step returns `[StepOutcome(name="success", context=...)]`.
- A branching step returns multiple outcomes; the engine routes each along the edge bound
  to that outcome handle.
- **Credentials** are passed as references in `config` (e.g. `config["credential_reference"]`),
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

### Post-step guard (`touched` devices)

After a step returns, the engine checks (canonical implementation:
`backend/services/workflow_context/guards.py::post_step_guard`; see "Runtime Validation
Guards" below for the real code):

```python
# "touched" = devices present in the success outcome that the step attempted to enrich
# (i.e. devices from context.devices that are now in success_outcome.context.devices)
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

Simplified illustrations of the pattern using real, currently-registered steps —
`artifact_service` and `node_id` are received as parameters (see Executor Contract
above). Follow the file path in each heading for the real implementation.

### get-nautobot-devices (source step)

`backend/workflow_steps/get_nautobot_devices/executor.py` — `requires: []`, `produces: [identity]`.

```python
async def execute(*, config, context, run, artifact_service, node_id, device_sessions) -> list[StepOutcome]:
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    devices_raw = await fetch_devices_from_nautobot(config)  # real: resolves via GraphQL

    # bare_hostname() is the shared helper (models/workflow_context.py) — strips the
    # CIDR mask from primary_ip4, falling back to the device name. Every source step
    # must use it, not a local re-implementation, so the hostname invariant holds
    # identically everywhere.
    new_devices = {
        d.id: DeviceContext(
            id=d.id,
            name=d.name,
            hostname=bare_hostname(d.primary_ip4, fallback=d.name),
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

### get-device-configs

`backend/workflow_steps/get_device_configs/executor.py` — `requires: [identity]`,
`produces: [running_config, startup_config]` narrowed by `config_format`
(`"running" | "startup" | "both"`) via `effective_produces()` (see "Runtime Validation
Guards" below) — a step's static `produces` isn't always what it guarantees on a given
run.

```python
async def execute(*, config, context, run, artifact_service, node_id, device_sessions) -> list[StepOutcome]:
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    config_format = config.get("config_format", "both")
    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    for device_id, device in context.devices.items():
        try:
            update: dict[str, Any] = {"status": DeviceStatus.OK}
            capabilities = set(device.capabilities)
            if config_format in ("running", "both"):
                text = await fetch_running_config(device, config, device_sessions)
                update["running_config_ref"] = await artifact_service.store(
                    content=text, kind="running_config", device_id=device_id, run_id=context.run_id,
                )
                capabilities.add(Capability.RUNNING_CONFIG)
            if config_format in ("startup", "both"):
                text = await fetch_startup_config(device, config, device_sessions)
                update["startup_config_ref"] = await artifact_service.store(
                    content=text, kind="startup_config", device_id=device_id, run_id=context.run_id,
                )
                capabilities.add(Capability.STARTUP_CONFIG)
            update["capabilities"] = capabilities
            success_devices[device_id] = device.model_copy(update=update)
        except (TimeoutError, AuthError) as exc:
            err = DeviceError(
                node_id=node_id, step_id="get-device-configs",
                code=type(exc).__name__.lower(), message=str(exc),
            )
            failed_devices[device_id] = device.model_copy(update={
                "status": DeviceStatus.FAILED, "errors": [*device.errors, err],
            })

    # SUCCESS carries only enriched devices — never mix with failed ones (see rule 5).
    outcomes = [StepOutcome(
        name="success", context=context.model_copy(update={"devices": success_devices}),
    )]
    if failed_devices:
        outcomes.append(StepOutcome(
            name="failure", context=context.model_copy(update={"devices": failed_devices}),
        ))
    return outcomes
```

### parse-cisco-config (parser step)

`backend/workflow_steps/parse_cisco_config/executor.py` — `requires: [identity]`,
`produces: [parsed]`. Writes to a **user-configured** `output_key`, not a fixed parser
name — see "Typed parser outputs" above for why this means the specific key isn't
canvas-validated.

```python
async def execute(*, config, context, run, artifact_service, node_id, device_sessions) -> list[StepOutcome]:
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    output_key = config["output_key"]  # e.g. "cisco_config" — arbitrary, author-chosen
    updated: dict[str, DeviceContext] = {}
    for device_id, device in context.devices.items():
        if device.running_config_ref is None:
            updated[device_id] = device
            continue
        config_text = await artifact_service.resolve(device.running_config_ref)
        parsed_data = cisco_config_parser.parse(config_text)  # real: cisco-config-parser lib
        updated[device_id] = device.model_copy(update={
            "parsed": {**device.parsed, output_key: parsed_data},
            "capabilities": device.capabilities | {Capability.PARSED},
        })
    new_ctx = context.model_copy(update={"devices": updated})
    return [StepOutcome(name="success", context=new_ctx)]
```

### run-command (self-contained command execution)

`backend/workflow_steps/run_command/executor.py` — `requires: [identity]`,
`produces: []`. There is no separate "build commands" step feeding a "send commands"
step: `run-command` takes its own `commands` list in config and executes directly against
each device in one pass, storing raw output as an `ArtifactRef` per command via
`command_results`. This is the real shape of command execution today — `pending_commands`
(a build-then-drain queue) exists in the model but isn't used by this or any other
shipped step; see "Open Decisions".

```python
async def execute(*, config, context, run, artifact_service, node_id, device_sessions) -> list[StepOutcome]:
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    commands = config["commands"]
    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    for device_id, device in context.devices.items():
        try:
            results: list[CommandResult] = []
            for command in commands:
                raw = await execute_on_device(device, command, config, device_sessions)
                ref = await artifact_service.store(
                    content=raw, kind="command_output", device_id=device_id, run_id=context.run_id,
                )
                results.append(CommandResult(
                    node_id=node_id, command=command, success=True, output_ref=ref,
                ))
            success_devices[device_id] = device.model_copy(update={
                "command_results": {**device.command_results, node_id: results},
                "status": DeviceStatus.OK,
            })
        except (TimeoutError, AuthError) as exc:
            err = DeviceError(
                node_id=node_id, step_id="run-command",
                code=type(exc).__name__.lower(), message=str(exc),
            )
            failed_devices[device_id] = device.model_copy(update={
                "status": DeviceStatus.FAILED, "errors": [*device.errors, err],
            })

    outcomes = [StepOutcome(
        name="success", context=context.model_copy(update={"devices": success_devices}),
    )]
    if failed_devices:
        outcomes.append(StepOutcome(
            name="failure", context=context.model_copy(update={"devices": failed_devices}),
        ))
    return outcomes
```

---

## How Data Flows Through a Workflow

Each step receives the fully accumulated context from all its upstream predecessors. The
StepRunner merges contexts from multiple parents using `merge()` before calling the next
step.

### Linear flow

```
[get-nautobot-devices] ──→ [get-device-configs] ──→ [parse-cisco-config] ──→ [run-command]
   produces: IDENTITY          +RUNNING_CONFIG,          +PARSED                results stored
   status: OK                  +STARTUP_CONFIG                                  in command_results
                                failed → failure edge
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
[get-device-configs]
  ├── success ──→ [parse-cisco-config] ──→ [run-command]
  └── failure ──→ [notify-on-error]
```

Each outcome carries the same envelope type — only the routing and the device subset differ.

---

## Immutability and Merge

### Immutability

Steps **must not mutate** the context they receive. Use `model_copy(update={...})` to
build the modified copy. Because content is referenced via `ArtifactRef` rather than
inlined, copies are small even for large device fleets.

### Deterministic merge

When branches converge, the engine merges parent contexts. This is the real
implementation, not a paraphrase — `backend/services/workflow_context/merge.py`:

```python
def merge_workflow_contexts(contexts: list[WorkflowContext]) -> WorkflowContext: ...
```

| Field | Rule |
|-------|------|
| `run_id`, `workflow_id`, `schema_version` | Must be identical; mismatch → `ValueError`. |
| `devices` | Union by device id. For the same id, merge `DeviceContext` field-by-field (below). |
| `pending_commands` | Dict-union per device, then dict-union per node_id within each device. Idempotent: the same node's commands are never duplicated even in a diamond graph. Real machinery, but currently unused by any shipped step — see "Open Decisions". |
| `metadata` | Shallow merge by key; conflict → raise unless values are equal. |

**DeviceContext merge per id** (`merge_device_contexts` / `_merge_two_devices`):

| Field | Rule |
|-------|------|
| Scalar identity fields (`id`, `name`, `hostname`, `platform`, `network_driver`, `primary_ip4`, `source`, `source_id`) | Equal or one side `None` → keep the non-`None` value silently. Both non-`None` and different → keep the left value, append a `DeviceError` (`step_id="merge"`, `code="identity_conflict"`). |
| `attribute_bags` | Dict-union by bag name, then shallow key-union **within** each bag; conflicting keys raise unless equal. |
| `parsed` | Shallow key-union; conflicting keys raise unless equal. |
| `*_config_ref` | Take the non-None value; conflict (both non-None and different) → raise. |
| `command_results` | Dict-union by `node_id`; each value is the node's full `list[CommandResult]`. The same `node_id` always carries the same list, so union is idempotent; conflict (same node_id, different list) → raise. |
| `capabilities` | Union — a device has a capability if any branch gave it. |
| `status` | Worst-case wins: `FAILED` > `SKIPPED` > `PENDING` > `OK` (`worst_device_status`). |
| `errors` | Concatenate; dedupe by `(node_id, step_id)` pair. |

#### Why pending_commands uses node_id keys

In a diamond graph, two branches B and C both inherit ancestor A's `pending_commands`.
A naïve list concatenation at the merge point D would double-count A's commands. Keying
by `node_id` makes the dict-union idempotent: `{A: [...]}` merged with `{A: [...]}` is
still `{A: [...]}`. This is why both `pending_commands` (context level) and
`command_results` (device level) are dicts keyed by node_id rather than plain lists —
`command_results` is real and load-bearing (`run-command` uses it today);
`pending_commands` has the same idempotent-merge design but is currently dormant (built,
tested, unused — see "Open Decisions").

#### Pending command ordering

Keying by `node_id` solves double-counting but discards ordering — and for any future
step that *does* build a command queue, push order would be significant (e.g. an ACL must
be defined before it is referenced). `merge.py::flatten_pending_commands(pending_by_node,
node_order)` already exists and is unit-tested for this
(`backend/tests/unit/test_workflow_context_merge.py`) — it flattens a device's
`{node_id: [cmds]}` map in **topological order of the producing nodes**, never in lexical
`node_id` order. No step calls it today (see "Open Decisions"); a future queue-building
step would pass it the engine's topological node ordering before concatenating.

---

## Step Registry — Capability Declarations

Each step in `registry.yaml` declares the capabilities it **requires** and **produces**,
plus its named **outcomes**. The frontend loads this at boot and uses it for canvas
validation and palette rendering. Schema: `backend/models/plugins.py::PluginDefinition`.
These are real entries from `backend/workflow_steps/registry.yaml` (`configuration_input`
lists trimmed for brevity — see the real file for every field):

```yaml
# backend/workflow_steps/registry.yaml

schema_version: 1

plugins:
  - id: get-nautobot-devices
    name: Get from Nautobot
    overview: Select devices from the Nautobot inventory.
    description: Select one or more target devices from the inventory.
    artifact_type: inventory_selector
    palette_category: nautobot
    directory: get_nautobot_devices
    enabled: true
    requires: []                # source node — takes no upstream context
    produces: [identity]
    outcomes:
      - name: success
      - name: failure
    metadata:
      configuration_input:
        - name: nautobot_source_id
          description: ID of a Nautobot source configured under Settings → Sources.
          data_type: string
          required: true
          example: prod-lab

  - id: get-device-configs
    name: Get Configs
    overview: Get device configuration in the chosen format.
    description: Get device configuration in the specified format.
    artifact_type: configuration_retrieval
    directory: get_device_configs
    enabled: true
    requires: [identity]
    produces: [running_config, startup_config]
    primary_output: running_config
    outcomes:
      - name: success
      - name: failure

  - id: parse-cisco-config
    name: Parse Cisco Config
    overview: Parse a Cisco running/startup config into structured data.
    artifact_type: configuration_retrieval
    palette_category: cisco
    directory: parse_cisco_config
    enabled: true
    requires: [identity]
    produces: [parsed]
    consumes: []
    primary_output: cisco_config
    outcomes:
      - name: success
      - name: failure

  - id: run-command
    name: Run Command
    overview: Execute CLI commands on connected devices.
    artifact_type: command_execution
    directory: run_command
    enabled: true
    requires: [identity]
    produces: []                 # adds command_results (content), no new capability
    primary_output: command_output
    outcomes:
      - name: success
      - name: failure
```

`requires: []` marks a **source node** — it has no input handle on the canvas.
Each entry in `outcomes` maps to one output handle. `palette_category` groups the step in
the frontend palette (e.g. `"nautobot"`, `"pyats"`, `"cisco"`) and is optional — steps
without one fall into a default grouping.

**`requires` vs `consumes` vs `produces`:**
- `requires` — capabilities that must be present on the input edge (read-only gate).
- `produces` — capabilities the step *adds* to the devices on its success outcome.
- `consumes` — capabilities the step *removes* after it runs, because it drains the
  underlying data. A step's success outcome guarantees
  `(provided_on_input ∪ produces) \ consumes`. **No shipped step currently declares a
  non-empty `consumes`** — every entry that sets it explicitly sets `consumes: []`. The
  field, and the post-step "leaked consumes" guard below, exist for a future step that
  needs to drain something (e.g. a `pending_commands`-consuming step, if one is ever
  built — see "Open Decisions").

`consumes` defaults to `[]` when omitted.

At runtime a step that *did* declare `consumes` would be responsible for making its
returned context match it — removing the corresponding capability from each device it
processed. The engine asserts this in the post-step guard — a device on the success path
must not retain a consumed capability:

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
**As implemented, this is maintained by hand** (no codegen, no cross-language parity
test yet — see Open Decision 5 below); a `registry.yaml`-vs-enum test exists on the
backend side only (`backend/tests/unit/test_plugin_registry_capabilities.py`). Treat any
change to the Python `Capability` enum as requiring a matching manual edit here.

```typescript
// frontend/src/lib/capability-types.ts
/** Capability tokens — keep in sync with backend Capability enum. */

export type Capability =
  | "identity"
  | "attributes"
  | "running_config"
  | "startup_config"
  | "parsed"
  | "pending_commands"
  | "pyats_testbed";

export const ALL_CAPABILITIES: Capability[] = [
  "identity", "attributes", "running_config", "startup_config",
  "parsed", "pending_commands", "pyats_testbed",
];

export interface Provided {
  capabilities: Capability[]
  parsedKeys: string[]        // parser keys guaranteed on this edge (currently always [] — see "Typed parser outputs")
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

### Computing what an outcome handle guarantees

Unlike an earlier design where each node statically stored its own transitive
capabilities, the canvas now computes them on demand by walking the graph:
`computeOutcomeProvides()` (`frontend/src/components/features/workflows/utils/capability-graph.ts`)
starts from an empty `{capabilities: [], parsedKeys: []}` state at each source node and,
for every node along a chain, applies `provided_out = (provided_in ∪ produces) \ consumes`
and `parsed_out = parsed_in ∪ producesParsed` — the same rule the doc has always
described, just implemented as a graph walk rather than stored per-node fields.

### React Flow connection validation

```typescript
// frontend/src/components/features/workflows/components/workflow-canvas.tsx

const isValidConnection = useCallback(
  (connection: Connection): boolean => {
    const sourceNode = nodes.find(n => n.id === connection.source)
    const targetNode = nodes.find(n => n.id === connection.target)
    if (!sourceNode || !targetNode) return false

    // Canvas decorations (label/background) never accept or emit edges; funnels
    // have their own connection rules (unlimited in, exactly one out, no chaining,
    // and skip capability checking — see doc/WORKFLOW-STEPS.md "Fan-out execution").
    // ... decoration/funnel handling omitted here, see the real file ...

    const provided = getOutcomeProvides(outcomeProvides, connection.source ?? "", connection.sourceHandle)
    const required = {
      capabilities: targetNode.data.requires ?? [],
      parsedKeys: targetNode.data.requiresParsed ?? [],
    }

    return isCompatible(provided, required)
  },
  [nodes, edges, outcomeProvides],
)
```

`outcomeProvides` is precomputed per node/handle by `computeOutcomeProvides()` above and
passed in from the parent component; `getOutcomeProvides` looks up one node+handle's
entry in it.

### Node data shape

```typescript
// frontend/src/components/features/workflows/types/workflow-canvas.ts

import type { Capability } from "@/lib/capability-types"

export interface WorkflowNodeData extends Record<string, unknown> {
  kind: string                      // step id, matches registry, e.g. "get-nautobot-devices"
  title: string
  description: string
  requires?: Capability[]           // capabilities needed on the input edge
  requiresParsed?: string[]         // parser keys needed on the input edge
  produces?: Capability[]           // capabilities this step adds
  producesParsed?: string[]         // parser keys this step adds
  consumes?: Capability[]           // capabilities this step removes
  outcomes?: { name: string }[]     // one per output handle — no per-outcome capability fields
  pluginConfig?: Record<string, unknown>
  // ...canvas-only fields (handle sides, group-view annotations) omitted here
}
```

`outcomes` here is just the handle names — it does **not** carry per-handle
`transitiveProvides`/`transitiveParsedKeys` the way an earlier design had it; those are
computed separately by `computeOutcomeProvides()` (above), not stored as static node
data.

---

## Runtime Validation Guards

Design-time canvas checks are not enough. The engine validates at runtime too. This is
the real, current file: `backend/services/workflow_context/guards.py`.

```python
@dataclass(frozen=True)
class StepCapabilitySpec:
    """Declared capability contract for a workflow step (from registry)."""
    step_id: str
    requires: frozenset[Capability] = field(default_factory=frozenset)
    produces: frozenset[Capability] = field(default_factory=frozenset)
    consumes: frozenset[Capability] = field(default_factory=frozenset)
    requires_parsed: frozenset[str] = field(default_factory=frozenset)


def pre_step_guard(*, spec: StepCapabilitySpec, context: WorkflowContext) -> None:
    """Validate required capabilities and parser keys before a step runs."""
    if not context.devices:
        return  # skip guard for empty inventory — no-op pass-through

    missing_capabilities = set(spec.requires) - context.provided_capabilities()
    if missing_capabilities:
        raise ValueError(f"Step {spec.step_id}: missing required capabilities {missing_capabilities}")

    missing_parsed_keys = set(spec.requires_parsed) - context.provided_parsed_keys()
    if missing_parsed_keys:
        raise ValueError(f"Step {spec.step_id}: missing required parsed keys {missing_parsed_keys}")
```

**Config-dependent `produces`** — the post-step guard normally checks the static
`produces` list from `registry.yaml`, but a handful of steps only guarantee a subset of
their declared capabilities depending on `pluginConfig`, and the registry format has no
way to express a conditional. `effective_produces()` computes the actual expected set for
these before the guard runs — this is the real function, in full:

```python
def effective_produces(*, spec: StepCapabilitySpec, step_type: str, config: dict) -> frozenset[Capability]:
    """Return capabilities a step must add on the success path for this config."""
    if step_type == "get-device-configs":
        config_format = str(config.get("config_format") or "both").strip().lower()
        if config_format == "running":
            return frozenset({Capability.RUNNING_CONFIG})
        if config_format == "startup":
            return frozenset({Capability.STARTUP_CONFIG})
        return frozenset({Capability.RUNNING_CONFIG, Capability.STARTUP_CONFIG})
    if step_type == "render-jinja-template":
        return frozenset({Capability.PARSED})
    if step_type == "update-attribute":
        if _update_attribute_has_guaranteed_write(config):
            return frozenset({Capability.ATTRIBUTES})
        return frozenset()
    return spec.produces
```

| Step | Config that narrows `produces` |
|------|---------------------------------|
| `get-device-configs` | `config_format: "running" \| "startup" \| "both"` — only the requested `*_CONFIG` capability is required, not both. |
| `render-jinja-template` | Always narrows to `{PARSED}` regardless of the registry entry. |
| `update-attribute` | `ATTRIBUTES` is only guaranteed when at least one configured entry is `mode: "fixed"` (an unconditional write); a purely `regex`-mode config may legitimately skip a device, so `produces` narrows to `{}`. |

Every other step uses its registry `produces` unchanged. A new step should only need
`effective_produces()` if its declared capability is genuinely conditional on config —
prefer a `produces` list that's always true instead, when possible.

**Post-step guard** — after a step returns, check the success outcome only:

```python
def post_step_guard(
    *, spec: StepCapabilitySpec, input_context: WorkflowContext,
    outcomes: list[StepOutcome], expected_produces: frozenset[Capability] | None = None,
) -> None:
    produces = expected_produces if expected_produces is not None else spec.produces
    success_outcome = next((o for o in outcomes if o.name == "success"), None)
    if success_outcome is None:
        return

    touched = set(success_outcome.context.devices) & set(input_context.devices)
    for device_id in touched:
        device = success_outcome.context.devices[device_id]

        missing_produces = set(produces) - device.capabilities
        if missing_produces:
            raise RuntimeError(f"Step {spec.step_id} expected produces={set(produces)} but device "
                                f"{device_id} is missing {missing_produces} on the success path")

        leaked_consumes = set(spec.consumes) & device.capabilities
        if leaked_consumes:
            raise RuntimeError(f"Step {spec.step_id} declared consumes={set(spec.consumes)} but device "
                                f"{device_id} still has {leaked_consumes} on the success path")
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

Quick reference for step authors, using real steps.

| Step                       | Requires            | Reads from context                            | Writes to context                                    |
|----------------------------|---------------------|-----------------------------------------------|--------------------------------------------------------|
| `get-nautobot-devices`     | *(source)*          | nothing                                       | `devices[*]` identity fields + `IDENTITY`            |
| `get-git-devices`          | *(source)*          | nothing                                       | `devices[*]` identity fields + `IDENTITY`            |
| `get-nautobot-attributes`  | `IDENTITY`          | `devices[*].id`                               | `devices[*].attribute_bags["nautobot"]` + `ATTRIBUTES` |
| `get-device-configs`       | `IDENTITY`          | `devices[*].hostname`, `network_driver`       | `devices[*].running_config_ref` and/or `startup_config_ref` + `RUNNING_CONFIG`/`STARTUP_CONFIG` (per `config_format`) |
| `parse-cisco-config`       | `IDENTITY`          | `devices[*].running_config_ref` and/or `startup_config_ref` | `devices[*].parsed[output_key]` + `PARSED`   |
| `add-pyats-testbed`        | `IDENTITY`          | `devices[*].id`, credential/source config     | `devices[*].attribute_bags["pyats_testbed"]` + `PYATS_TESTBED` |
| `get-pyats-config`         | `IDENTITY`, `PYATS_TESTBED` | `devices[*].attribute_bags["pyats_testbed"]` | `devices[*].parsed[output_key]` + `PARSED` |
| `run-command`              | `IDENTITY`          | `devices[*]` (hostname, credential config)    | `devices[*].command_results[node_id]` (list, `ArtifactRef`-backed) |
| `filter-output`            | `IDENTITY`          | `devices[*].command_results` or `devices[*].parsed["{src}.merged_content"]` | `devices[*].parsed["{node_id}.filtered_output"]` + `PARSED` |
| `update-attribute`         | `IDENTITY`          | `devices[*]` (any dotted-path source, incl. `parsed.*`) | `devices[*].attribute_bags[bag]` + `ATTRIBUTES` (conditionally — see `effective_produces()`) |

Full step-by-step catalogue: `doc/WORKFLOW-STEPS.md`; pyATS-specific steps:
`doc/PYATS_INTEGRATION.md`.

---

## Persistence and Schema Version

- Persist with `model_dump(mode="json")`; rehydrate with `model_validate`.
- `schema_version` is persisted with every step result. On load, if older than the
  current code, run a registered migration function before use.
- One step result is stored per node per run (`workflow_step_results` table). Because
  content is referenced via `ArtifactRef`, a step result is the small enriched context —
  not a copy of every device's configuration.

---

## Open Decisions

1. ~~**Artifact storage backend**~~ — **Resolved:** filesystem
   (`services/artifacts/filesystem_artifact_service.py`), with an in-memory
   implementation for dev/tests. The abstract `ArtifactService` (`store`/`resolve`)
   stays backend-agnostic if an object-store backend is added later.
2. **Per-device capability gating** — should a step run only on the subset of devices
   that satisfy its capability, instead of requiring all devices? A per-device gate is
   more flexible but more complex; recommended as a follow-up once the all-devices model
   is stable. Still open.
3. **Parsed-data size bound** — `parsed` is "structured but bounded". Define a soft cap
   and spill to an `ArtifactRef` above it if parsers produce large trees. Still open.
4. ~~**Outcome fan-out semantics**~~ — **Resolved:** implemented as full inventory-level
   fan-out (per-device/chunked child workflows + optional Wait & Run approval batching),
   well beyond a single step's multiple outcomes. See `doc/WORKFLOW-STEPS.md` →
   "Fan-out execution" for the design; this document's merge rules above cover only
   branch-convergence `merge()`, not fan-out's separate `merge_fan_out_contexts()`
   (`services/workflow_context/merge.py`) — see that section for its list-concatenate /
   first-child-wins semantics.
5. **Capability enum sync** — kept in sync by hand today. Partially mitigated: a backend
   test (`backend/tests/unit/test_plugin_registry_capabilities.py`) asserts every
   `registry.yaml` capability string is a valid `Capability` enum value, but there is no
   test asserting the Python enum and `frontend/src/lib/capability-types.ts`'s
   `Capability` union stay identical to each other. Still open — add that parity check
   (or codegen) before relying on the frontend union being trustworthy.
6. **Typed parser outputs (`requires_parsed`/`produces_parsed`) are unused.** The schema
   and runtime guard machinery are real (see "Typed parser outputs" above), but every
   shipped parser-producing step uses a dynamic, user-configured `output_key` instead of
   a statically-declared parser key, so the canvas cannot catch a mistyped/missing
   `output_key` reference at design time — only at run time, as a missing value. Either
   (a) migrate real steps to declare `produces_parsed: [output_key-ish-name]` so the
   canvas can validate it (non-trivial: `output_key` is user-chosen per step instance,
   not a fixed step-level constant, so the registry's static declaration model would need
   to change), or (b) remove the unused fields/guard checks and rely on run-time errors,
   accepting the design-time gap. Still open.
7. **`pending_commands` (queue-and-drain command building) is unused.** The field, its
   merge logic, and `flatten_pending_commands()`'s topological-ordering helper are real
   and tested, but no shipped step produces, requires, or consumes it —
   `run-command` proved a single self-contained step (build + execute in one pass) is
   sufficient for today's use cases. Either keep the machinery for a future step that
   genuinely needs to build a queue across multiple upstream nodes before one downstream
   step drains it (e.g. composing config from several independent template/attribute
   steps before a single push), or remove it if no such step is planned. Still open.

---

## Robustness Checklist

- [ ] Capabilities are a **set**; compatibility is **subset** (`required ⊆ provided`), never rank `>=`.
- [ ] Capabilities tracked per device; context guarantee = intersection across devices (vacuously full for empty inventory).
- [ ] Parser outputs keyed by a per-step `output_key`; `requires_parsed`/`produces_parsed` exist in the schema but are not populated by any shipped step today (see Open Decision 6).
- [ ] `command_results` is `{ node_id: list[CommandResult] }` — supports multiple commands per node, idempotent on merge.
- [ ] `consumes` honoured when a step declares it: capability removed after the step; `transitiveProvides = (in ∪ produces) \ consumes`. No shipped step declares a non-empty `consumes` today (see Open Decision 7).
- [ ] `pending_commands`, if ever populated by a future step, must be flattened in TOPOLOGICAL node order (not lexical node_id) via `flatten_pending_commands()` before sending.
- [ ] All bulky content is an `ArtifactRef`; envelope/step-results stay small.
- [ ] Per-device `status` + append-only `errors`; runtime failures never raise.
- [ ] **Success outcome carries only successfully enriched devices** — failed devices on `failure` only.
- [ ] Branching/failure expressed via multiple `StepOutcome`s; same envelope type, different device subset.
- [ ] `pending_commands` and `command_results` keyed by `node_id` — merge is idempotent, no diamond double-counting.
- [ ] Credentials passed as references in `config`, resolved in-step, never in the envelope.
- [ ] `merge()` is total and deterministic; per-device capability union, cross-device intersection.
- [ ] `model_config = extra="forbid"` on every envelope type; `set[Capability]` serialisation pinned by round-trip test.
- [ ] `schema_version` persisted with a migration hook.
- [ ] Pre-step guard skips empty inventory (no-op); checks `requires ⊆ provided_capabilities()` otherwise.
- [ ] Post-step guard checks `produces ⊆ device.capabilities` for `touched` devices on success path (using `effective_produces()` where a step's config narrows it).
- [ ] `hostname` invariant (no CIDR mask) enforced at the source step.
- [ ] Capability enum sync strategy decided and documented (still open — see Open Decision 5).

---

## Summary

```
WorkflowContext                                           schema_version: int
├── run_id, workflow_id                                   (invariant — set once by engine)
├── devices: { device_id: DeviceContext }
│   ├── id, name, hostname, platform,
│   │   network_driver, primary_ip4, source               ← source steps
│   ├── attribute_bags: { bag_name: { ... } }              ← "nautobot" (get-nautobot-attributes),
│   │                                                         "tacacs"/"ise" (ISE/TACACS+ steps),
│   │                                                         "pyats_testbed" (add-pyats-testbed),
│   │                                                         "run_input" (reserved, seeded by engine)
│   ├── running_config_ref, startup_config_ref            ← get-device-configs  (ArtifactRef)
│   ├── parsed: { output_key: structured_data }           ← parse-cisco-config, get-pyats-config, ...
│   │   ├── "{node_id}.merged_content": { artifact_ref, step_node_id, output_key, kind, size_bytes }
│   │   │                                                 ← merge-content
│   │   └── "{node_id}.filtered_output": { artifact_ref, step_node_id, output_key, kind, size_bytes }
│   │                                                     ← filter-output (cleaned JSON or text blob)
│   ├── command_results: { node_id: [ CommandResult ] }   ← run-command  (output as ArtifactRef)
│   ├── capabilities: set[Capability]                     ← added by each enriching step
│   ├── status: DeviceStatus                              ← set per operation
│   └── errors: [ DeviceError ]                           ← append-only, deduped by (node_id, step_id)
├── pending_commands: { device_id: { node_id: [cmds] } }  ← modelled + merge-tested, unused by any shipped step
└── metadata: { "<node-id>.key": value }                  ← namespaced scratch space

Compatibility check:  required_capabilities ⊆ provided_capabilities()
                      provided_capabilities() = ∩ device.capabilities  (full set if devices empty)
```
