# Batfish Integration

Backend integration with [Batfish](https://github.com/batfish/batfish), an
offline network-configuration analysis engine, for answering routing/
reachability/ACL questions against already-collected device configs from a
workflow. Unlike the pyATS integration, Batfish's heavy engine runs in its
own container already (`docker/batfish/`) and the Python client (`pybatfish`)
is thin enough to live directly in the backend's own venv — **no shim
container is needed here.**

Optional, like pyATS: nothing in this integration is required for the app to
function, and the **Batfish** step category is hidden from the canvas
palette entirely until a Batfish source is configured (mirrors pyATS's
`hasPyatsSource` gate in `step-catalog.tsx` — see "Frontend: category
gating" below).

## Contents

- [Why no separate shim container](#why-no-separate-shim-container)
- [Architecture](#architecture)
- [File map](#file-map)
- [Snapshot lifecycle: networks, snapshots, retention](#snapshot-lifecycle-networks-snapshots-retention)
- [Configuring a source](#configuring-a-source)
- [Security notes](#security-notes)
- [Workflow steps](#workflow-steps)
  - [Init Batfish Snapshot](#init-batfish-snapshot-batfish-init-snapshot)
  - [Batfish Routing Table](#batfish-routing-table-batfish-routing-table)
  - [Batfish Path Check](#batfish-path-check-batfish-path-check)
  - [Batfish ACL Check](#batfish-acl-check-batfish-acl-check)
- [Frontend: category gating](#frontend-category-gating)
- [Viewing results: the run detail UI](#viewing-results-the-run-detail-ui)
- [Open items / verify during hardening](#open-items--verify-during-hardening)

## Why no separate shim container

pyATS needed its own container because the *engine itself* (pyATS/Genie/
Unicon) couldn't run in the backend's Python 3.14 venv — its published wheels
only confirm 3.12/3.13, and its dependency tree (a pinned `paramiko`/
`cryptography`, plus `unicon`) risked colliding with the backend's own deps.

Batfish is structurally different: the engine (parsing, modeling, answering
questions) already runs inside the `batfish` container we stood up in
`docker/batfish/` (the coordinator + worker, via the official
`batfish/allinone` image). The backend only needs a **client** that speaks
Batfish's RPC protocol — that's `pybatfish`, and it is a genuinely thin
dependency. Checked directly against PyPI metadata rather than assumed
(current release `2026.8.19.3660`):

```
requires_python: >=3.10          (no upper bound — 3.14 is fine)
requires_dist:  attrs, deepdiff, pandas, python-dateutil, PyYAML,
                requests, requests-toolbelt, setuptools, simplejson, urllib3
```

No `unicon`/`paramiko`-class dependency, and nothing here collides with
`backend/requirements.txt` (which has no `pandas`/`requests`/`urllib3` pin at
all, and an unconstrained `PyYAML` requirement compatible with the pinned
`PyYAML==6.0.3`). So `pybatfish` is added straight to
`backend/requirements.txt` and imported directly from
`backend/services/batfish/client.py` — no `Dockerfile`, no second
`docker-compose.yml` service, no shim HTTP contract to design.

## Architecture

```
Settings -> Sources -> Batfish              backend/services/batfish/client.py
  (Settings UI)              (BatfishService: pybatfish.Session, app-scoped)
        |                              |
        v                              v pybatfish's own RPC protocol (ports 9996/9997)
  sources.batfish.<id>          batfish container (coordinator + worker)
  (settings only --                    |
   no credential row)                  v  vendor-neutral model, in-memory per snapshot
                                 answers routing/reachability/ACL questions
```

Reachability of the `batfish` container follows the same two-case pattern as
`docker/pyats` and `docker/openbao`: `host=batfish` on the shared `backend`
Docker network for a containerized backend, `host=127.0.0.1` for the native
dev workflow (`python start.py` / `python scripts/run_worker_dev.py`) — see
`docker/batfish/README.md`. Because the coordinator has no authentication,
the source config has no credential at all (see "Configuring a source"
below) — just host + one port.

**Only one port is actually used, despite two being published.** Checked
directly against `pybatfish.client.session.Session.__init__`: it accepts
`port_v1` (default 9997) but never assigns it to `self` or uses it anywhere —
every request is built from `self.port_v2` (default **9996**, confusingly
named "v2" despite being numerically the lower/older port). `port_v1`/9997 is
a vestigial constructor parameter in the installed `pybatfish` release. The
source config therefore only needs `host` + one `port` (default `9996`); the
9997 publish in `docker/batfish/docker-compose.yaml` is harmless to keep (matches
upstream's own quick-start convention and costs nothing) but isn't load-bearing
for anything this integration does.

## Session caching and concurrency safety

`pybatfish.client.session.Session` is **synchronous** (`requests`-based, no
`asyncio` support) and **stateful**: `set_network(name)` mutates
`self.network`, and every subsequent call implicitly targets whatever
network was last set — there is no `network=` kwarg on the question-answering
path to override it per call (confirmed from `Session.answer_question`'s
signature: `snapshot`/`reference_snapshot` can be overridden per call,
`network` cannot). Naively caching one `Session` per `(host, port)` and
reusing it across concurrent calls would let two unrelated calls — two
workflow runs querying Batfish at the same time, e.g. on the live and
background-tier Hatchet workers — race on `self.network`, silently querying
the wrong network's data.

`BatfishService` avoids this by caching sessions **per `(host, port,
network)`**, calling `set_network()` exactly once when a cache entry is
created and never again for that entry — so a cached session's `.network`
never changes after creation, and it's safe to share across concurrent
callers. `snapshot` is never relied upon as session state — every question
call passes `answer(snapshot=snapshot_name)` explicitly. `init_snapshot`,
`list_snapshots`, and `delete_snapshot` all still implicitly target
`self.network` (none of them take a `network=` override either, confirmed
from their signatures) — safe under this scheme specifically because that
value is fixed at cache-entry creation and never mutated afterward.

Constructing a `Session` performs a blocking HTTP call itself
(`load_questions=True` by default runs `self.q.load()` in `__init__`), so
both session creation and every actual client call must run via
`asyncio.to_thread(...)` — the same pattern already used for other
blocking-library wrapping in this codebase
(`services/artifacts/filesystem_artifact_service.py`,
`services/artifacts/sinks/git_sink.py`), not a new `ThreadPoolExecutor` like
`DeviceSessionPool`'s (that one bounds true concurrent SSH connections;
Batfish calls are one-shot RPCs with no comparable pooling need). A
plain `asyncio.Lock` around "get-or-create" on the cache dict prevents two
concurrent callers from double-constructing the same `(host, port, network)`
entry.

`check_health` (used by test-connection) does **not** go through this cache
at all — it builds a throwaway `Session(host, port)` and calls
`list_networks()`, which doesn't depend on `self.network` being set to
anything in particular.

## File map

**Implemented.** Everything below exists on `feature/batfish` (as of this
writing, not yet merged to `main` — check `git status`/`git log` for current
branch/commit state rather than trusting this document's staleness).

```
backend/services/batfish/
├── __init__.py
├── client.py                              # BatfishService -- wraps pybatfish.client.session.Session
├── credentials.py                         # BatfishConnection(host, port=9996) -- no secret fields
├── common/exceptions.py                   # BatfishError, BatfishValidationError, BatfishAPIError
└── source_config_service.py               # BatfishSourceConfigService -- settings only, no credential

backend/models/batfish.py                  # Pydantic request/response models (source CRUD, test-connection)
backend/routers/sources/batfish/
├── __init__.py
├── crud.py                                # /sources/batfish -- source configuration CRUD
└── ops.py                                 # /sources/batfish/{source_id}/test-connection

backend/service_factory.py                 # get/set_batfish_app_service, build_batfish_source_config_service
backend/dependencies.py                    # get_batfish_source_config_service (FastAPI dependency)
backend/main.py                            # BatfishService lifespan startup/shutdown (API process), router registration
backend/hatchet/worker_services.py         # BatfishService lifespan startup/shutdown (shared by both Hatchet workers)
backend/services/auth/rbac_seed.py         # sources.batfish read/write/delete permissions
backend/services/settings/source_keys.py   # "batfish" added to SourceType + BATFISH_KEY_PREFIX

backend/workflow_steps/common/batfish_context.py   # resolve_batfish_snapshot/store_batfish_snapshot -- shared metadata lookup
backend/workflow_steps/batfish_init_snapshot/{__init__.py,executor.py,config.py}
backend/workflow_steps/batfish_routing_table/{__init__.py,executor.py,config.py}
backend/workflow_steps/batfish_path_check/{__init__.py,executor.py,config.py}
backend/workflow_steps/batfish_acl_check/{__init__.py,executor.py,config.py}
backend/services/execution/step_registry.py   # 4 imports + dict entries
backend/workflow_steps/registry.yaml          # 4 entries, palette_category: batfish

backend/tests/unit/test_batfish_{client,source_config_service,router_auth,context_helper}.py
backend/tests/unit/test_batfish_{init_snapshot,routing_table,path_check,acl_check}_executor.py

frontend/src/components/features/settings/types/settings-api.ts   # BatfishSource*/BatfishTestConnection* types
frontend/src/lib/query-keys.ts                                     # queryKeys.sourcesBatfish
frontend/src/hooks/queries/use-batfish-sources-query.ts             # mirrors use-pyats-sources-query.ts
frontend/src/hooks/queries/use-batfish-sources-mutations.ts
frontend/src/components/features/settings/dialogs/batfish-source-dialog.tsx   # host+port only, no credential field
frontend/src/components/features/settings/hooks/use-sources-settings.ts       # "batfish" slice
frontend/src/components/features/settings/hooks/use-sources-settings-save.ts  # "batfish" dialog/save/delete branch
frontend/src/components/features/settings/components/sources-settings-canvas.tsx  # Batfish SourceListSection + dialog

frontend/src/components/features/workflow-steps/shared/batfish-source-config.ts        # BATFISH_SOURCE_ID_KEY etc.
frontend/src/components/features/workflow-steps/shared/batfish-source-select-dialog.tsx
frontend/src/components/features/workflow-steps/batfish-init-snapshot/{index.tsx,help-panel.tsx}
frontend/src/components/features/workflow-steps/batfish-routing-table/{index.tsx,help-panel.tsx}
frontend/src/components/features/workflow-steps/batfish-path-check/{index.tsx,help-panel.tsx}
frontend/src/components/features/workflow-steps/batfish-acl-check/{index.tsx,help-panel.tsx}
frontend/src/lib/plugin-ui-registry.ts        # 4 PLUGIN_UI_REGISTRY entries
frontend/src/components/features/workflows/utils/step-visuals.ts   # "batfish" category label/colors/icons
frontend/src/components/features/workflows/components/step-catalog.tsx  # hasBatfishSource gate

frontend/src/components/features/workflows/components/step-result-viewer/batfish-result-panel.tsx  # see "Viewing results" below
frontend/src/components/features/workflows/components/step-result-viewer/{metadata-panel,outcome-context-view,devices-section,device-card,device-detail-dialog}.tsx  # wiring for the above (edits, not new)
```

No new `backend/core/models/{domain}.py` SQLAlchemy table — like pyATS and
ISE, a Batfish source's config lives entirely in the generic `settings` table
under the `sources.batfish.<id>` key namespace (`SettingsRepository`); there
is no per-source credential row since the coordinator has no auth. This
means the usual "Adding New Backend Endpoint" 6-step recipe in `CLAUDE.md`
doesn't apply as-is for the *source config* endpoints (no model, no
repository, no service-layer-over-a-table) — it mirrors
`services/pyats/source_config_service.py` / `services/ise/source_config_service.py`
instead. The **workflow steps**, by contrast, follow "Adding a New Workflow
Step" exactly as documented.

**Three independent processes, two independent lifespans — same trap as
pyATS.** `BatfishService` must be started/stopped in **both**
`main.py`'s `lifespan()` *and* `hatchet/worker_services.py::start_all()`
(shared by `hatchet/worker.py` and `hatchet/dynamic_worker.py`). Workflow
steps run only in a worker process; registering the service in `main.py`
alone leaves `service_factory.get_batfish_app_service()` raising at every
step call while the API's own test-connection endpoint works fine — this bit
the pyATS integration first (see that doc's File map section) and is exactly
the kind of failure that's easy to miss in review because the symptom is
worker-only.

## Snapshot lifecycle: networks, snapshots, retention

Batfish's own model is two-level: a **network** (a long-lived namespace) 
contains many **snapshots** (one point-in-time set of configs each). This
maps naturally onto Manus's own model:

- **Network name = `f"manus-workflow-{workflow_id}"`.** One Batfish network
  per Manus workflow, not one global network — keeps different workflows'
  device sets from colliding on node/filter names, and makes
  `bf.list_snapshots()` a meaningful "history for this workflow" view later.
- **Snapshot name = `f"run-{run_id}"`.** One snapshot per `batfish-init-snapshot`
  execution, named after the `WorkflowRun` that produced it — traceable back
  to a specific run, and naturally unique (no timestamp collision handling
  needed).

**Retention is enforced by the step itself, not left as an unbounded
liability.** After a successful `init_snapshot(...)`, the executor calls
`bf.list_snapshots(verbose=True)` for the network and deletes every snapshot
beyond the most recent `retain_snapshots` (a step config field, default
`5`) via `bf.delete_snapshot(name)`. **Snapshot names are not chronologically
sortable and retention must not assume they are** — `run-{run_id}` uses
`WorkflowRun.id` (an autoincrementing int, not `WorkflowContext.run_id`,
which is `run.uuid` — confirmed from `step_runner/runner.py`'s
`WorkflowContext(run_id=run.uuid, ...)`), but even a numeric suffix sorts
wrong lexically (`"run-10" < "run-9"`). The real fix, confirmed against a
live coordinator: `verbose=True` returns each snapshot's
`metadata.creationTimestamp` (a fixed-width, always-UTC, `Z`-suffixed ISO
8601 string — safe to sort lexically), e.g.:

```json
[{"name": "probe-snapshot", "metadata": {"creationTimestamp": "2026-09-12T16:21:45.810915760Z", ...}}]
```

`BatfishService.list_snapshots_with_metadata()` wraps this
(`list_snapshots(verbose=True)`); the retention sweep sorts entries by that
field, not by name, before deciding what to delete. `bf.delete_snapshot(name)`
and `bf.delete_network(name)` both exist on `pybatfish`'s `Session` for the
actual deletion.

**Building the snapshot directory.** `pybatfish` has no "upload N files as
one multi-device snapshot from in-memory text" call —
`init_snapshot_from_text()` exists but is explicitly single-file/single-node
(confirmed from its docstring: one `text` blob, one optional `filename`). For
our multi-device case, `batfish-init-snapshot`'s executor must:

1. Create a `tempfile.TemporaryDirectory()`.
2. For every device in `context.devices`, resolve its running-config text via
   the existing `running_config` content source
   (`workflow_steps/common/content_resolver.py`, the same path `store-artifact`
   already uses) and `artifact_service.read_content(artifact_ref.artifact_id)`,
   then write it to `<tmpdir>/configs/<device_id>.cfg`. The filename is
   cosmetic — **Batfish derives each node's real name from the config text's
   own hostname line, not the filename** (verified: a file whose content
   declares `hostname R1` shows up in every answer table as node `r1`,
   regardless of what the file itself was named). Devices with no
   `running_config_ref` yet (upstream `get-device-configs` failed/skipped
   them) are skipped with a per-device warning, not a whole-step failure.
3. Call `bf.set_network(network_name)` (creates it if absent) then
   `bf.init_snapshot(tmpdir, name=snapshot_name, overwrite=True)`.
4. Store one consolidated key, `WorkflowContext.metadata["batfish"] =
   {"host": ..., "port": ..., "network": network_name, "snapshot":
   snapshot_name}`, so the three query steps downstream in the same run have
   everything they need — including the connection itself — without each
   needing their own `batfish_source_id` config. This mirrors the
   "define once, reuse across every step" shape `pyats_testbed` already
   established for pyATS (see `doc/PYATS_INTEGRATION.md` → "Add Testbed"),
   just via `metadata` instead of a per-device `attribute_bags` entry, since
   the value is workflow-scoped, not per-device.
5. Run the retention sweep from above.
6. Delete the temp directory (`TemporaryDirectory` context manager handles
   this even on error).

**Fan-out rule: not fan-out-safe, same class as `store-artifact`/git steps.**
This step needs every device's config together in one upload, so it must run
**after a Fan In** in a fanned-out workflow — never inside the fanned-out
branch, for the same reason `git-pull`/`store-artifact` must (see
`doc/HOWTO_BUILD_WORKFLOWS.md` → "Every Git step sits after the Fan In").
`requires: [identity]`, `produces: []` in `registry.yaml` (mirrors
`store-artifact`'s own declaration — the per-device `running_config`
precondition is checked at runtime, not declared as a canvas-level
capability requirement, exactly like `store-artifact` already does for its
own `content_source` choices).

**Why `WorkflowContext.metadata`, not a new `Capability`.** `Capability`
(`models/workflow_context.py`) is a closed enum describing properties of a
single `DeviceContext` — it has no notion of a workflow-level fact like "a
Batfish snapshot exists for this run." Adding one purely to gate three
downstream steps would be modeling a per-run fact as if it were per-device
data, which the data model deliberately keeps separate (see
`doc/ARCHITECTURAL_OVERVIEW.md` → "Per-device data isolation"). Instead, the
three query steps below just declare `requires: [identity]` (a weak
precondition ensuring they're wired downstream of an inventory step, same
role it plays for git steps) and read `context.metadata["batfish"]`
themselves at runtime via a small shared helper
(`workflow_steps/common/batfish_context.py`, mirroring `pyats_batch.py`'s
role as shared logic for a family of steps), raising a `ValueError` ("no
Batfish snapshot found — add an Init Batfish Snapshot step upstream") if
it's missing. Because that one metadata entry carries the connection too,
none of the three query steps need their own `batfish_source_id` config —
only `batfish-init-snapshot` does. One
consequence worth calling out explicitly for whoever builds this: because
`metadata` merges **first-child-wins** under fan-out
(`ARCHITECTURAL_OVERVIEW.md` again), `batfish-init-snapshot` must never run
*inside* a fanned-out branch — not only because of the shared-upload race
covered above, but because a metadata write there would silently lose to
whichever child fan-out picked as "first" once results are merged back.
Running it post-Fan-In (single writer, single segment) avoids this
entirely — one more reason to enforce that placement rather than merely
document it.

## Configuring a source

Mirrors `services/pyats/source_config_service.py` /
`services/ise/source_config_service.py`, minus the credential half — there is
no vault credential to select because the coordinator has no auth. Non-secret
config (`host`, `port` default `9996` — see the single-port finding above)
lives under `sources.batfish.<id>` in the generic `settings` table via
`SettingsRepository`, same as every other source. No `verify_ssl`/TLS
setting — `pybatfish` talks plain TCP to the coordinator (`ssl=False` is the
`Session` default and nothing in this integration changes that), matching
the container's own no-TLS setup on the internal `backend` Docker network.

`POST /api/sources/batfish/{source_id}/test-connection` should do a
single-stage check — there's no separate "process is up" vs "functionally
working" distinction like pyATS's `/health` vs `/health/pyats`, since
`pybatfish` has no lightweight liveness probe of its own. The simplest real
check: `Session(host=...).list_networks()` — succeeds only if the
coordinator actually answers pybatfish's RPC protocol, fails clearly
(connection refused/timeout) if the container is down or unreachable.
Response shape is `{success, message}`, same convention as every other
source's test-connection endpoint.

**Which host to use depends on where the backend process itself runs** —
exactly the same two-case split documented in `docker/batfish/README.md` and
already hit once by pyATS: native-backend dev
(`python start.py` / `python scripts/run_worker_dev.py`) uses
`host=127.0.0.1`; a fully containerized backend uses `host=batfish`. The
loopback case needs `ALLOW_LOOPBACK_SOURCE_URLS=true` in `backend/.env` if
the source URL validation path treats a bare hostname the same way it treats
pyATS's/OpenBao's loopback URLs — verify `validate_outbound_http_url`'s
behavior against a non-HTTP `host:port` pair specifically, since Batfish's
source config isn't a URL in the same shape as every other source (see "Open
items" below). **Remember to restart the Hatchet worker** after changing the
source config or this env var, for the same reason documented in the pyATS
doc's "Configuring a source" section — the worker only re-reads config at its
own process startup.

## Security notes

- The `batfish` container's coordinator has **no authentication of its
  own** — anyone who can reach ports 9996/9997 can create, read, or delete
  any network/snapshot. `docker/batfish/docker-compose.yaml` already binds
  the published ports to `127.0.0.1` only; this integration must never
  change that or add a way to point a Batfish source at a non-local/
  non-`backend`-network host without equivalent protection.
- Device configs — potentially containing secrets (enable passwords, SNMP
  community strings, pre-shared keys) if not scrubbed by the collecting
  step — are uploaded into the Batfish container's `/data` volume as part of
  every snapshot. This is the same trust boundary already accepted for the
  git-mirrored config backups (`doc/ARCHITECTURAL_OVERVIEW.md` → "Version-
  controlled workflows"); nothing here widens it, but it's worth recording
  explicitly in `doc/SECURITY-NOTES.md` alongside the other accepted-risk
  entries once this ships, since a *new* place now holds a copy of raw
  device configs.
- Batfish answers (routing tables, ACL contents, reachable paths) are
  themselves sensitive — they describe exactly how to reach or bypass
  network controls. `sources:batfish` read access should be scoped by
  RBAC the same as `sources:pyats`/`sources:ise`, and query-step results
  should be treated with the same care as raw config content when stored as
  artifacts.

## Workflow steps

All four steps live under `palette_category: batfish` (a new palette
category — see "Frontend: category gating" below for why it's hidden by
default).

### Init Batfish Snapshot (`batfish-init-snapshot`)

`requires: [identity]`, `produces: []`. Builds a fresh Batfish snapshot from
the current run's device configs and stores its location (and connection)
in `WorkflowContext.metadata["batfish"]` — see "Snapshot lifecycle" above
for the full mechanics (directory assembly, naming, retention, the fan-out
placement rule). Config: `batfish_source_id: str` (required — which
configured Batfish source to use) and `retain_snapshots: int` (default `5`).
Snapshot naming uses `run.id` (the `WorkflowRun` ORM object's autoincrement
int, passed into every executor already) — not `context.run_id`, which is
`run.uuid` and not needed here.

This is the one step in this integration with any real I/O cost/risk (it
touches the shared Batfish network for the whole workflow) — the three
query steps below are pure reads against an already-initialized snapshot.

### Batfish Routing Table (`batfish-routing-table`)

`requires: [identity]`, `produces: []`. Wraps `bf.q.routes(...)` — confirmed
against a real two-router snapshot, no required parameters, returns one row
per `(node, VRF, network)` route with columns including `Next_Hop`,
`Protocol`, `Metric`, `Admin_Distance`, `Tag`. Config maps directly onto
`routes()`'s own parameters (all optional — an empty config returns every
route on every node):

```python
bf.q.routes(
    nodes=config.get("nodes"),              # nodeSpec, e.g. "R1" (case-insensitive)
    network=config.get("network_prefix"),   # prefix, e.g. "192.168.1.0/24"
    prefixMatchType=config.get("prefix_match_type"),  # EXACT (default) | LONGEST_PREFIX_MATCH | LONGER_PREFIXES | SHORTER_PREFIXES
    protocols=config.get("protocols"),      # routingProtocolSpec, e.g. "static", "bgp"
    vrfs=config.get("vrfs"),
    rib=config.get("rib"),                  # main (default) | bgp | evpn
).answer().frame()
```

**Naming collision, found and fixed during implementation:** pybatfish's own
`routes()` question has a parameter literally named `network` (the
route-prefix filter above). `BatfishService.routes()` — the async wrapper
every step actually calls, not the raw `bf.q.routes()` shown above — takes
the *Batfish* network name as `batfish_network` specifically to avoid
colliding with that when the step's `network_prefix` config value gets
forwarded through `**params`. The step's own config field is named
`network_prefix` for exactly the same reason — `network` alone would be
ambiguous between "which Batfish network" and "which route prefix."

**Result storage: workflow-level, not per-device — deliberately NOT wired
into `store-artifact`/`content_resolver.py` in v1.** Every existing
`artifact_service.store()` call site in this codebase is per-device (one
artifact per device, keyed by that device's `device_id`) — there is no
established convention for a single workflow-scoped artifact, and
`content_resolver.py`'s contract takes one `device: DeviceContext` at a time
by design. A Batfish routing-table result is inherently one table covering
every queried node, not naturally splittable per device. Rather than force
one of two awkward shapes (fan the same artifact out redundantly to every
device's `parsed`, or extend `content_resolver.py`'s per-device contract to
also handle workflow-level content — a real change to a shared file every
existing step depends on), this step stores the result as one artifact via
`artifact_service.store(device_id=f"batfish-{node_id}", ...)` (a sentinel,
not a real device — confirmed safe: `device_id` is stored as descriptive
metadata alongside the artifact, e.g. for filesystem backends, not used to
build the storage path) and puts the `ArtifactRef` plus a small inline
summary (row count) directly in
`WorkflowContext.metadata[f"{node_id}.{output_key}"]` (`output_key` is a
step config field, default `batfish_routes`/`batfish_path_check`/
`batfish_acl_check` per step). One more `run_id` distinction worth stating
explicitly since it's easy to get backwards: `artifact_service.store()`'s
`run_id` parameter is typed `str` and takes `context.run_id` (confirmed
against `get_pyats_snapshot/executor.py`'s real precedent) — this is
*unrelated* to the `run.id` (int) used for Batfish snapshot naming above;
mixing the two up is a real `pyright` error (`reportArgumentType`), not just
a style nit, since `run.id` is an `int`.
Exporting a Batfish result via `store-artifact` is deferred — see "Open
items" below — rather than casually extending a shared, heavily-used
contract as a side effect of this integration.

### Batfish Path Check (`batfish-path-check`)

`requires: [identity]`, `produces: []`. Wraps `bf.q.reachability(...)` —
this is the actual "is there a path between device A and device B" question,
confirmed working end-to-end against the two-router snapshot:

```python
bf.q.reachability(
    pathConstraints={
        "startLocation": config["start_node"],   # e.g. "R1" -- a device hostname/nodeSpec
        "endLocation": config.get("end_node"),   # optional -- omit to search any destination
    },
    headers=config.get("headers", {}),           # optional headerConstraint, e.g. {"dstIps": "..."}
    actions=config.get("actions", ["success"]),  # dispositionSpec, default ["success"]
    maxTraces=config.get("max_traces"),
    invertSearch=config.get("invert_search", False),
    ignoreFilters=config.get("ignore_filters", False),
).answer().frame()
```

**Important param-shape gotcha, verified the hard way**: `headers` is a
**sibling** top-level parameter of `pathConstraints`, not nested inside it —
`reachability(pathConstraints={"startLocation": ..., "headers": {...}})`
fails with a 400 from the coordinator (`Unrecognized field "headers"`,
`PathConstraintsInput` only recognizes `startLocation`/`endLocation`/
`transitLocations`/`forbiddenLocations`). The step's config schema should
mirror the correct (flat) shape directly rather than a nested one that looks
more "intuitive" but doesn't match the real API.

Empty `answer().frame()` means no matching flow was found for the given
constraints, which for a "does a path exist between A and B" question *is*
the negative-case answer, not an error. Unlike Routing Table's plain
success/failure, this step gives that answer a first-class canvas outcome —
`outcomes: [reachable, not_reachable]` (as implemented — **no `failure`
outcome**: a config/input problem raises `ValueError`, a Batfish-side
failure raises via `BatfishAPIError`, neither is modeled as a third outcome
branch) — so a workflow can branch on it directly (e.g. alert only when a
critical path breaks).

**Not a per-device partition, unlike `compare-pyats-snapshot`'s
`match`/`mismatch`/`failure`.** That step's branching splits
`context.devices` itself into buckets, because it evaluates the same
condition independently *per device*. Path Check evaluates ONE flow
definition from `config` (`start_node`/`end_node`/`headers` — not derived
from `context.devices` at all), so the step returns a single-element
`list[StepOutcome]` — whichever one of `reachable`/`not_reachable`
applies — carrying the **full, unmodified** `context.devices` through that
one outcome. The other declared outcome name simply doesn't fire for that
run, the same way a plain `success`/`failure` step only ever returns one of
the two. Result storage follows the same workflow-level-artifact-plus-
metadata-summary approach as Routing Table above.

### Batfish ACL Check (`batfish-acl-check`)

`requires: [identity]`, `produces: []`. Wraps `bf.q.testFilters(...)` —
confirmed against a real ACL (`permit tcp any host 192.168.1.1 eq 22; deny
ip any any`): a concrete 5-tuple flow through a named filter, returning
`Action` (`PERMIT`/`DENY`) and the matched `Line_Content`:

```python
bf.q.testFilters(
    nodes=config["node"],           # nodeSpec, e.g. "R1"
    filters=config["filter_name"],  # filterSpec, e.g. "TEST-ACL"
    headers={                       # required
        "srcIps": config.get("src_ips"),
        "dstIps": config["dst_ips"],
        "applications": config.get("applications"),   # e.g. ["SSH"], ["TELNET"]
        "ipProtocols": config.get("ip_protocols"),
    },
    startLocation=config.get("start_location"),
).answer().frame()
```

`headers` is documented by pybatfish itself as *Required* for this question
(unlike `reachability`'s optional `headers`) — the config panel should mark
at least `dst_ips` as required, matching this. Like Path Check, this step
uses branchable outcomes — `outcomes: [permit, deny]` (as implemented, same
no-`failure`-outcome reasoning as Path Check) — read from the answer's
`Action` column; also a single-`StepOutcome`, whole-context-passthrough
step, not a per-device partition, for the same reason (one concrete flow
from `config`, not one check per device). An empty result set here is
treated as an execution problem, not a verdict — `raise RuntimeError`
rather than defaulting to `deny`, since "no result" means the
`node`/`filter_name` didn't match anything in the snapshot, not that the
filter denied the traffic. Stores its result the same workflow-level-artifact
way Routing Table does.

**`searchFilters` was considered and rejected as the primary mapping for
"ACL permits this traffic".** `searchFilters()` answers a broader question —
"does *any* flow matching this header space get permitted/denied" — useful
for an existence check across a whole space of traffic, but the user's
framing ("ACL permits this traffic") reads as "check this specific traffic
description," which is exactly `testFilters()`'s contract: one concrete flow
in, one concrete verdict out, no example-searching involved.
`filters`/`nodes` narrow which filter(s) are tested the same way in both
questions, so a v2 "does any SSH traffic reach this host at all" variant of
this step could reuse most of the same config shape with `searchFilters()`
if that broader question turns out to be wanted later.

## Frontend: category gating

Exactly mirrors pyATS's existing mechanism in
`frontend/src/components/features/workflows/components/step-catalog.tsx`
(lines ~121-130 as of this writing):

```typescript
const { data: batfishSourcesData } = useBatfishSourcesQuery();
const hasBatfishSource = (batfishSourcesData?.sources.length ?? 0) > 0;

// The Batfish category only makes sense once a Batfish source is configured.
const visibleGroups = useMemo(() => {
  const withoutPyats = hasPyatsSource ? allGroups : allGroups.filter((g) => g.categoryKey !== "pyats");
  return hasBatfishSource ? withoutPyats : withoutPyats.filter((g) => g.categoryKey !== "batfish");
}, [plugins, hasPyatsSource, hasBatfishSource]);
```

Frontend-only filter, no backend change — the four steps are always
registered in `registry.yaml`/`step_registry.py` (a workflow built before a
source existed and later shared would still execute correctly; only the
*palette* — where you'd drag a new instance from — is gated). `palette_category:
batfish` in `registry.yaml` is the value this filter matches against, exactly
the same field/value pattern as `palette_category: pyats`.

## Viewing results: the run detail UI

The three query steps store their answer as one artifact plus a small
summary dict in `WorkflowContext.metadata[f"{node_id}.{output_key}"]` (see
"Result storage" under each step above) — this section covers where a user
actually sees that after a run finishes, added after real usage surfaced two
navigation/visibility gaps:

**Gap 1 (fixed): the answer was invisible without knowing to open a second
dialog.** The run detail view has two renderings of the same step —
expanding it inline (click the step name) uses `StepResultViewer` in
`compact` mode, which never rendered the Metadata section at all; only
"open in dialog" (a small logs icon) rendered it, and even then only as a
raw `JSON.stringify` blob keyed by `{node_id}.{output_key}`. A user who only
ever expanded inline had no path to the answer whatsoever.

**Gap 2 (fixed): even once found, the metadata blob was a summary, not the
answer.** `{"kind": "batfish_result", "question": "routes", "artifact_ref":
{...}, "row_count": 0}` tells you *that* something happened, not what the
actual routes/path/ACL verdict was — the real content lives in the artifact
the `artifact_ref` points to, and this app has **no generic "click to view
artifact content" UI** (confirmed: `ArtifactRefRow` renders only
`{kind} · {size} bytes`, no click handler, for every step's artifacts, not
just Batfish's — a pre-existing gap, not something this integration
introduced).

**The fix reused an existing mechanism rather than building a new one.**
`ConfigArtifactPanel` + `useArtifactQuery` (`frontend/src/hooks/queries/use-artifact-query.ts`)
already fetch-and-render artifact content by `artifact_id`, scoped to a
`run_id`, via a **generic, kind-agnostic, already-existing backend endpoint**
— `GET /api/runs/{run_id}/artifacts/{artifact_id}`
(`backend/routers/workflow_runs.py` → `RunService.get_run_artifact` →
`ArtifactService.get_for_run`, permission `workflow_runs:read`, scoped by
`run.uuid` so one run can't read another's artifact). This was already used
for device running/startup configs and Genie snapshots — it needed zero
backend changes to work for `batfish_result` artifacts too, since it doesn't
filter by `kind` at all. (Whoever investigates "can we view artifact content
anywhere" for a *different* step in the future should know this already
exists — it's easy to miss since `ArtifactRefRow`, the dumb non-clickable
row component, is the more visible/superficially similar file.)

**New component: `batfish-result-panel.tsx`.** Extracts every
`{node_id}.{output_key}` metadata entry whose value has
`"kind": "batfish_result"` (`extractBatfishResults`), plus the connection
info under the `"batfish"` key (`extractBatfishConnection`), and renders
each as a small card: a human label (`routes` → "Routing table",
`reachability` → "Path check", `testFilters` → "ACL check"), a
reachable/not-reachable or permit/deny badge when present, the row count,
an explicit warning line when `row_count === 0` (a real, common answer —
config didn't parse into Batfish's model, or the filters excluded
everything — not necessarily a bug), and a `ConfigArtifactPanel` that
fetches and displays the actual artifact JSON. `metadata-panel.tsx`'s
generic dump excludes these same keys (`isBatfishMetadataKey`) so they don't
appear twice.

**Wired into two places:**
- `OutcomeContextView` — unconditionally (not gated by `compact`), right
  above the Devices section, so the answer is visible from the inline
  expand view with no extra click. This is the actual fix for Gap 1.
- `DeviceDetailDialog`'s left sidebar (the per-device "Detailed view"
  dialog opened from `DeviceCard`) — a new **"Batfish result"** nav entry
  (Radar icon, count badge) appears whenever the run has any Batfish
  result, in *every* device's dialog, labeled as workflow-level (not
  device-specific) content — this was the explicit, literal feature
  request that prompted this section, mirroring the sidebar's existing
  `DetailSection` list pattern (`{id, label, icon, count, render}`).

Prop threading required to get the extracted `batfishResults`/
`batfishConnection` from `OutcomeContextView` (which has `context.metadata`)
down to `DeviceDetailDialog` (which only receives one `device`): through
`DevicesSection` → `DeviceCard` → `DeviceDetailDialog`, each taking the two
values as optional props defaulting to empty/`null` via a module-level
constant (`EMPTY_BATFISH_RESULTS`), matching this codebase's own
"hold defaults in a module-level constant" convention for avoiding a new
array/object identity every render.

**Deliberately not built**: per-device filtering of a routing-table result
to just the rows where `Node` matches the open device (Batfish's `routes()`
answer does have a `Node` column that could support this). The result is
shown identically regardless of which device's dialog is open. Worth
revisiting if users find the unfiltered table noisy for large topologies.

## Open items / verify during hardening

- **RESOLVED during implementation**: no `validate_outbound_http_url` call
  was needed. `BatfishSourceConfigService` does plain non-empty/length
  validation on `host` (`_validate_host`) rather than routing it through the
  URL/loopback-allowlist path every other source uses — `host` is a bare
  hostname/IP, not a URL, so that path doesn't apply. This also means the
  loopback case (native-backend dev pointing at `127.0.0.1`) needs no
  `ALLOW_LOOPBACK_SOURCE_URLS` exception the way pyATS/OpenBao do — there's
  no URL-shaped value for that guard to reject in the first place.
- **Deferred: no `store-artifact`/`content_resolver.py` integration for
  Batfish query results.** Narrowed in scope since "Viewing results" above
  shipped: *visibility* (seeing the answer in the run detail UI) is solved;
  what's still deferred is *export* — piping a result to git/filesystem via
  `store-artifact` the way device configs can be. Revisit only if a real
  request for that surfaces; the in-run viewer may be sufficient on its own.
- **Not built: a loud signal when a snapshot init parses zero usable
  nodes.** Observed in real usage: a `batfish-routing-table` run returned
  `row_count: 0` with no other indication anything was wrong, and the
  underlying cause (a device's captured "running-config" not being valid
  Batfish-parseable syntax — wrong platform, malformed capture, etc.) is
  invisible without manually inspecting the artifact content via the new
  viewer. `batfish-init-snapshot` already knows the input device count
  (`len(context.devices) - len(skipped)`, in its success summary) but has no
  way today to know how many of those actually became real Batfish nodes
  (`pybatfish` doesn't return a "N nodes parsed" count from `init_snapshot`
  itself — would need a follow-up `bf.q.nodeProperties()` or similar call
  right after init to get a real node count and warn loudly if it's zero
  or far below the device count).
- **Snapshot retention default (`retain_snapshots: int`, proposed default
  `5`).** Chosen for symmetry with pyATS's per-chunk defaults being
  reasonable-guess numbers rather than measured ones — revisit once real
  snapshot sizes/frequency are known. `bf.delete_network()` also exists if a
  "delete this workflow's whole Batfish history" admin action is ever wanted
  (e.g. when a Manus workflow itself is deleted) — not building that in v1,
  noting it exists.
- **Node-name case sensitivity, verified as a non-issue but stated
  explicitly.** Batfish canonicalizes hostnames to lowercase internally (a
  device configured with `hostname R1` appears as node `r1` in every answer
  table), but pybatfish's node/filter specifiers matched `"R1"`/`"TEST-ACL"`
  case-insensitively in testing. Config panels can accept whatever casing
  matches the user's own device hostnames without a normalization step —
  confirmed empirically, not from documentation (Batfish's specifier-language
  docs don't state this explicitly either way).
- **Multi-VRF, multi-AS, or genuinely large topologies** are unverified here —
  every claim above was checked against a deliberately minimal 2-router,
  single-VRF, static-routing snapshot (two `GigabitEthernet` interfaces per
  device, one static route each, one ACL). BGP/OSPF-heavy real inventories,
  multiple VRFs, or very large device counts (Batfish's own parse/model time
  scales with snapshot size) are not covered by anything checked while
  writing this doc.
- **No git-backed snapshot source in v1.** `batfish-init-snapshot` only reads
  live, in-run device configs from `WorkflowContext` (see "Snapshot
  lifecycle" above) — it does not read from a `GitRepository`-backed config
  history. A "build a snapshot from a specific git commit" variant (useful
  for "what did routing look like last Tuesday") is a reasonable future
  step, deliberately deferred: it needs the user to describe how their repo's
  path template maps to device identity, which is a separate design
  conversation from anything resolved here.
- **`docker build`/`up` for `docker/batfish` was verified working in this
  environment** (unlike pyATS's own doc, which flagged this as unverified at
  the time it was written) — the container reaches `healthy`, runs only the
  Batfish coordinator/worker process (no bundled Jupyter notebook — see
  `docker/batfish/docker-compose.yaml`'s `command:` override), and every
  `pybatfish` call shape documented above (`init_snapshot`, `routes`,
  `reachability`, `testFilters`, `list_snapshots`/`delete_snapshot`) was
  exercised against a real running instance, not assumed from pybatfish's
  documentation alone.
