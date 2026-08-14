# pyATS Integration

Backend integration with Cisco pyATS/Genie, a network test-automation
framework, for running ad-hoc `execute`/`parse` operations against network
devices from a workflow. pyATS runs in its own Docker container behind a
thin HTTP shim (`/pyats-shim`) rather than being installed into the main
backend's Python environment.

## Contents

- [Why a separate container](#why-a-separate-container)
- [Architecture](#architecture)
- [File map](#file-map)
- [The shim's HTTP contract](#the-shims-http-contract)
- [How a job actually runs](#how-a-job-actually-runs)
- [Configuring a source](#configuring-a-source)
- [Security notes](#security-notes)
- [Workflow steps: Add Testbed and Get & Parse Config](#workflow-steps-add-testbed-and-get--parse-config)
- [Genie-native snapshot comparison](#genie-native-snapshot-comparison)
- [Configure Replace Config](#configure-replace-config)
- [Open items / verify during hardening](#open-items--verify-during-hardening)

## Why a separate container

pyATS's published wheels only confirm Python 3.12/3.13 support; this
project's backend venv runs **Python 3.14**. pyATS also carries a large,
opinionated dependency tree (its own pinned `paramiko`/`cryptography`/
`pyyaml`, plus `unicon` for device connections) that risks colliding with
the backend's own dependencies. Rather than fight either constraint, pyATS
runs in its own container (`/pyats-shim`, Python 3.12) with a small FastAPI
wrapper, and the backend talks to it over HTTP — the same pattern already
used for Nautobot and Cisco ISE (external service behind a client class in
`services/`), just with a container the project itself builds instead of a
third-party API.

## Architecture

```
Settings -> Sources -> pyATS               backend/services/pyats/client.py
  (Settings UI)              (PyATSShimService: httpx, app-scoped)
        |                              |
        v                              v HTTP, internal `backend` Docker network
  sources.pyats.<id>            pyats-shim container (FastAPI)
  (settings + encrypted               |
   bearer-token credential)           v  `pyats run job` subprocess per request
                                pyATS / Genie / Unicon -> SSH -> network devices
```

No host port is published for `pyats-shim` — it's reachable only from other
containers on the `backend` Docker network (`manus-web` / `manus-worker`),
the same trust model already used for `postgres`/`redis`.

## File map

```
pyats-shim/                                # Standalone service, NOT part of the backend's venv
├── Dockerfile                             # python:3.12-slim + pyats[full] + fastapi/uvicorn
├── requirements.txt / requirements-dev.txt
├── app/
│   ├── main.py                            # FastAPI app, lifespan wires up JobRunner
│   ├── config.py                          # ShimSettings (env-driven: token, port, concurrency, timeout)
│   ├── auth.py                            # Bearer-token dependency for /v1/jobs
│   ├── health.py                          # GET /health, GET /health/pyats
│   ├── jobs.py                            # POST /v1/jobs request/response models + route
│   ├── diff.py                            # POST /v1/diff -- Genie-native snapshot diff (no subprocess/testbed)
│   ├── testbed_builder.py                 # device list -> pyATS testbed dict
│   ├── job_runner.py                      # per-request temp dir, subprocess, timeout, cleanup
│   └── job_scripts/
│       ├── generic_job.py                 # pyATS job file (forwards request/result file paths)
│       └── generic_script.py              # AEtest script: connect, execute/parse, write results
└── tests/                                 # pytest, mocks the subprocess -- no pyATS install needed

docker/pyats/
├── docker-compose.yml                     # builds pyats-shim, joins the `backend` network
├── .env.example                           # PYATS_SHIM_TOKEN
└── README.md

backend/services/pyats/
├── credentials.py                         # PyATSCredentials dataclass (base_url, token, timeout, verify_ssl)
├── client.py                              # PyATSShimService -- low-level HTTP client
├── common/exceptions.py                   # PyATSError, PyATSValidationError, PyATSAPIError
└── source_config_service.py               # PyATSSourceConfigService -- named source (settings + encrypted credential)

backend/models/pyats.py                    # Pydantic request/response models
backend/routers/sources/pyats/
├── crud.py                                # /sources/pyats -- source configuration CRUD
└── ops.py                                 # /sources/pyats/{source_id}/test-connection

backend/service_factory.py                 # get/set_pyats_app_service, build_pyats_source_config_service
backend/dependencies.py                    # get_pyats_source_config_service (FastAPI dependency)
backend/main.py                            # PyATSShimService lifespan startup/shutdown (API process), router registration
backend/hatchet/worker.py                  # PyATSShimService lifespan startup/shutdown (Hatchet worker process)
backend/services/auth/rbac_seed.py         # sources.pyats read/write/delete permissions

backend/workflow_steps/compare_pyats_snapshot/
├── executor.py                            # diffs one feature between a live snapshot and a stored reference
└── config.py

backend/tests/unit/test_pyats_source_config_service.py
backend/tests/unit/test_pyats_router_auth.py
backend/tests/unit/test_pyats_client.py
backend/tests/unit/test_compare_pyats_snapshot_executor.py
pyats-shim/tests/test_diff.py                # genie-gated -- see "Genie-native snapshot comparison" below
```

**Two independent processes, two independent lifespans.** The FastAPI API
process and the Hatchet worker process each construct their own
`PyATSShimService` and register it via `service_factory.set_pyats_app_service`
in their own startup path — `main.py`'s `lifespan()` for the API process,
`hatchet/worker.py`'s `lifespan()` for the worker. Workflow steps always run
in the **worker** process, so registering a new app-scoped service only in
`main.py` (as this integration initially did) leaves
`service_factory.get_pyats_app_service()` raising
`RuntimeError: PyATSShimService is not initialized` for every step that
calls it, while the API's own `/sources/pyats/{id}/test-connection`
endpoint works fine — the failure is worker-only, which makes it easy to
miss in review. Any future app-scoped service (a new external system client,
following the Nautobot/ISE/pyATS pattern) needs its startup/shutdown added
to **both** lifespans.

## The shim's HTTP contract

- `GET /health` — liveness only; does not import pyATS. Used by the Docker
  healthcheck.
- `GET /health/pyats` — imports `pyats`/`genie` and reports their versions.
  Distinguishes "shim process is up" from "pyATS is actually functional
  inside the container".
- `POST /v1/jobs` (Bearer token required) — runs one `execute`/`parse`
  operation against a batch of devices in a **single** job/subprocess
  invocation (one testbed, one AEtest run connecting to every device) so
  parallel callers don't each pay pyATS's `easypy` startup cost per device:

  ```json
  {
    "operation": "execute",
    "devices": [
      {"name": "sw1", "host": "10.0.0.1", "os": "iosxe", "username": "admin", "password": "admin"}
    ],
    "commands": ["show version"],
    "timeout_seconds": 60
  }
  ```

  ```json
  {
    "results": {
      "sw1": {
        "success": true,
        "error": null,
        "commands": {"show version": {"raw": "...", "parsed": null, "error": null}}
      }
    }
  }
  ```

## How a job actually runs

`JobRunner` (`app/job_runner.py`) does, per request:

1. Create a per-request temp dir; write `testbed.yaml` (built by
   `testbed_builder.build_testbed_dict`) and `request.json`
   (`{operation, commands}`) into it.
2. Launch `pyats run job job_scripts/generic_job.py --testbed-file
   testbed.yaml --no-mail --no-archive --runinfo-dir <workdir>/runinfo` as a
   subprocess, passing the request/result file paths via
   `PYATS_SHIM_REQUEST_FILE`/`PYATS_SHIM_RESULT_FILE` env vars.
3. `generic_job.py`'s `main(runtime)` reads those env vars and forwards them
   into `run(testscript=generic_script.py, runtime=runtime, request_file=...,
   result_file=...)` as AEtest parameters — **verified against a real pyATS
   26.7 install**: custom `run()` kwargs are matched by name into
   `CommonSetup`/`Testcase` method arguments, and a value one `CommonSetup`
   subsection stores via `self.parent.parameters.update(...)` is visible to
   a later subsection/testcase in the same run.
4. `generic_script.py`: `CommonSetup` connects to every device in the
   testbed (per-device connect failures are caught and recorded, not
   raised); the `Testcase` loops `devices x commands`, calling
   `device.execute()` or `device.parse()` per the requested operation
   (per-command failures likewise caught, not raised); `CommonCleanup`
   disconnects and writes the results dict to `PYATS_SHIM_RESULT_FILE`.
5. `JobRunner` awaits the subprocess under `asyncio.wait_for(timeout_seconds)`.
   **This outer timeout is the real safety net** — not any per-device
   connect timeout inside pyATS/Unicon (see
   [Open items](#open-items--verify-during-hardening)). On timeout, the
   whole process group is killed (`start_new_session=True` +
   `os.killpg`) and a `JobTimeoutError` (HTTP 504) is raised.
6. On success, `JobRunner` reads and returns `result.json` — trusting its
   own per-device `success`/`error` fields over the subprocess exit code,
   since `easypy` can exit 0 even when individual steps failed. If no
   result file exists (e.g. the job errored before `CommonCleanup`), a
   synthetic per-device error result is built from the captured stderr tail.
7. The temp dir is always removed (`try/finally`), and a semaphore
   (`PYATS_SHIM_MAX_CONCURRENT_JOBS`) bounds concurrent subprocesses.

`--no-archive --runinfo-dir <workdir>/runinfo` keeps every pyATS artifact
scoped to the per-request temp dir instead of accumulating in `~/.pyats/`
inside the container — confirmed during development; without these flags
pyATS writes a zip archive under `~/.pyats/archive` and run metadata under
`~/.pyats/runinfo` on every single job, which would grow unbounded.

## Configuring a source

Mirrors `services/ise/source_config_service.py`. Non-secret config (`url`,
`verify_ssl`, `timeout`) lives in the generic `settings` table under
`sources.pyats.<source_id>`; the bearer token lives Fernet-encrypted in the
`credentials` table (`source="pyats"`, `type="generic"`, username is a fixed
sentinel `"pyats-shim"` since auth is token-only). `verify_ssl` defaults to
`false` since the shim is plain HTTP on the internal Docker network by
default.

`POST /api/sources/pyats/{source_id}/test-connection` does the two-stage
check: `check_health()` first (failure -> "pyATS shim is not reachable"),
then `check_pyats_health()` (failure -> "Shim reachable, but the pyATS
functional check failed"); success reports the installed pyATS/Genie
versions in the message. Response shape is always `{success, message}`,
same as every other source's test-connection endpoint — no HTTP error
status on a *failed* check, only on auth/validation errors.

**Which URL to use depends on where the backend process itself runs** — this
tripped up the first real end-to-end test. `docker/pyats/docker-compose.yml`
joins the `backend` Docker network (for a backend that's *also*
containerized there, e.g. `docker/docker-compose.yml`'s `manus-web`/
`manus-worker`) **and** publishes its port to `127.0.0.1:8100` on the host
(for the common local-dev case: backend running natively via `python
start.py` / `python scripts/run_worker_dev.py`, which cannot resolve
`pyats-shim` as a hostname at all — it isn't on that Docker network).
Native-backend dev uses `http://localhost:8100`; a fully containerized
backend uses `http://pyats-shim:8100`. The loopback URL case additionally
needs `ALLOW_LOOPBACK_SOURCE_URLS=true` in `backend/.env` (see
`backend/.env.example`) — `validate_outbound_http_url` rejects loopback
targets by default. **Remember to restart the Hatchet worker after changing
this env var or the source URL** — see the lifespan note above; the worker
only re-reads config/settings at its own process startup.

If a workflow step fails with a connection error and `docker logs pyats-shim`
shows **no request activity at all** for that run, the request never left
the backend/worker process — that is always a connectivity/URL problem, not
a pyATS/Genie problem. See `docker/pyats/README.md`'s "Watching it work"
section for the log lines to expect on a working call.

## Security notes

- The bearer token is the only thing standing between "internal Docker
  network" and "anyone who can reach `pyats-shim`" — treat it like any
  other credential (rotate via the source's edit dialog, which re-encrypts
  and replaces it).
- Device SSH credentials are sent to the shim in the `POST /v1/jobs` request
  body over plain HTTP. This is safe **only** because the shim is never
  exposed outside the `backend` Docker network (no published port) — if
  that ever changes (e.g. the shim is exposed to a host port or a wider
  network), this must move to HTTPS or an equivalent transport-security
  fix first. Recorded as an accepted risk in `doc/SECURITY-NOTES.md`,
  matching the format used for `verify_ssl=False` and git-argv-credential
  entries there.
- The shim process itself must never log full request/response bodies at
  a level that could leak device passwords or the bearer token; keep
  logging at the summary level shown in `job_runner.py` (stderr tail on
  failure only, no full command output).

## Workflow steps: Add Testbed and Get & Parse Config

Two steps, both under the **PyATS** palette category (only shown once a
pyATS source is configured — a frontend-only filter in `step-catalog.tsx`,
no backend change):

### Add Testbed (`add-pyats-testbed`)

Pure local computation, no network I/O. Given a device list from an
upstream inventory step (`requires: [identity]`), it resolves a
`credential_reference` **once** (via
`workflow_steps/common/credential_resolver.py::resolve_generic_credential`,
which — unlike `resolve_ssh_credential` — accepts both `"ssh"` and
`"generic"` vault credential types, since the shim only needs a plain
username/password over HTTP), computes each device's pyATS `os` (a new
`services/network/pyats/platform.py::resolve_pyats_os`, mirroring the
Netmiko sibling but mapping to Genie's `os` vocabulary — `ios`/`iosxe`/
`nxos`/`iosxr`/`junos`/`eos`, which differs from Netmiko's `device_type`
strings), seals the password with `seal_secret()`, and writes one bundle
per device into `attribute_bags["pyats_testbed"]`:

```python
{"pyats_source_id": ..., "host": ..., "os": ..., "username": ..., "password": <sealed>}
```

This produces the new `Capability.PYATS_TESTBED` (`"pyats_testbed"`) — added
to the closed `Capability` enum in `models/workflow_context.py`, and
mirrored in `frontend/src/lib/capability-types.ts` for canvas connection
validation. `services/workflow_context/secret_fields.py::SECRET_BAG_PATHS`
gained a `("pyats_testbed", "password")` entry so the bundle's password is
redacted at every persist/log boundary, same as the TACACS+ shared-secret
path.

Downstream pyATS steps declare `requires: [pyats_testbed]` and read this
bag instead of asking for their own credential/source — define once, reuse
across every pyATS step in the workflow.

### Get & Parse Config (`get-pyats-config`)

`requires: [identity, pyats_testbed]`, `produces: [parsed]`. For each
device, reads its `pyats_testbed` bag, `unwrap_secret()`s the password
(in-memory only, to build the shim request body — never copied elsewhere),
and calls the shim **once per device**:

```python
shim.run_job(
    shim_credentials, operation="parse",
    devices=[{"name": device_id, "host": ..., "os": ..., "username": ..., "password": ...}],
    commands=["show running-config"],
)
```

One call per device rather than Phase 1's "batch every device into one
call" — because devices may in principle reference different
`pyats_source_id`s, and per-device isolation keeps partial-failure handling
simple (one bad device's shim call failing doesn't block the others). If
job-startup overhead × device count proves too slow in practice, grouping
devices by `pyats_source_id` and batching is a possible follow-up.

Only `show running-config` is requested — `show startup-config` was dropped
after real-world testing hit `ParserNotFound` on every device. Confirmed
against the `CiscoTestAutomation/genieparser` source (`gh search code
"'show startup-config'" --repo CiscoTestAutomation/genieparser` returns zero
hits): genieparser has **no registered parser for `show startup-config` on
any platform**, only for `show running-config`. This isn't a per-device or
per-revision gap, so requesting it via `operation="parse"` would fail on
every device, every time — not something worth carrying as a permanent
per-device failure mode.

The Genie-parsed result is written into `device.parsed[output_key]` as
`{"running": ...}` — this is the Genie-powered analog of the existing
`parse-cisco-config` step (which uses `cisco_config_parser`, not Genie), not
a replacement for `get-device-configs`. No raw-text artifact capture in v1
— only the Genie-parsed structured result, and only for running-config.

Full step-authoring convention: **doc/WORKFLOW-STEPS.md**'s "Calling pyATS
from a step" section.

A third step, `get-pyats-snapshot` ("Get Snapshot"), captures Genie
`device.learn(feature)` output (BGP, OSPF, interfaces, platform, ... or
`"all"`) the same way — one `operation="learn"` shim call per device, with
each feature's `Ops.to_dict()` result stored per feature and tolerant of
partial per-feature failure (a device only fails if *every* requested
feature fails to learn, since feature support varies a lot by platform).
Not detailed further here; see `workflow_steps/get_pyats_snapshot/executor.py`.

## Genie-native snapshot comparison

`get-pyats-snapshot` exists to enable comparing two snapshots of the same
device over time (e.g. before/after a change). The **Compare Snapshot**
step (`compare-pyats-snapshot`) does this the way pyATS/Genie natively
supports — via `genie.utils.diff.Diff`, which understands the data well
enough to ignore noisy dynamic fields (counters, timestamps, uptime), unlike
`compare-data`'s plain line-based text diff. It diffs one Genie feature per
step instance between a live snapshot (from an upstream `get-pyats-snapshot`
step in the current run) and a reference snapshot (a JSON file previously
exported to git/filesystem by `store-artifact` from an earlier
`get-pyats-snapshot` run — there is no cross-run artifact lookup in this
codebase, so "reference" always means a stored file, not a database query).
Implementation: `backend/workflow_steps/compare_pyats_snapshot/executor.py`
(backend step) and `pyats-shim/app/diff.py` (`POST /v1/diff`, the shim
endpoint that runs `Diff` itself). The design considerations below were
worked through before implementing and remain accurate to what was built.

**Decision: all Genie code stays in the shim container, not the backend.**
We considered installing `genie.libs.parser`/`genie.libs.ops` directly into
the backend's own Python 3.14 venv — PyPI metadata confirms both packages
declare **zero** runtime dependency on `unicon`/`pyats` (only `xmltodict` for
`genie.libs.parser`). This looked promising for both parsing and diffing.
Ruled out for now: Netmiko's own `use_genie=True` integration
(`netmiko/utilities.py`) hard-imports `genie.conf.base.Device`
(`genie.libs.conf`), and its own missing-dependency error says `pip install
genie` / `pip install pyats` — so doing this "the supported way" pulls the
full pyats/unicon stack straight back into the backend, hitting the same
Python-version wall (pyats wheels only confirm 3.12/3.13) that justified the
separate shim container to begin with. It may be possible to bypass
Netmiko's wrapper and call Genie parser classes directly with a lightweight
duck-typed device stub (`genie.libs.parser.utils.get_parser`) instead of a
real `pyats` `Device`, but this is unverified. **Revisit only if there's a
concrete reason to move parsing into the backend** — for now, any new
Genie-touching logic (including the diff endpoint below) belongs in
`pyats-shim/`, called from a step the same way `run_job` already is.

**`Ops.info` vs `Ops.to_dict()` — implemented with a documented assumption,
still not empirically verified.** Genie's documented `Diff` usage is
`Diff(output1.info, output2.info)` (confirmed against the official pyATS
getting-started docs). Our shim's `learn` branch (`generic_script.py`)
stores `ops.to_dict()`, not `.info`, because the result has to be
JSON-serializable for the HTTP response / artifact storage, and `.info` can
contain non-JSON-safe types (`QDict`, `netaddr` objects). Whether
`to_dict()` is exactly equivalent to `.info` (vs. e.g. wrapping it or
omitting something) could **not** be confirmed from source: pyATS/Genie's
core `Ops` base class is closed-source — `CiscoTestAutomation/genie` on
GitHub contains only docs, no implementation. Circumstantial evidence
they're equivalent: `genielibs`' own test suite mocks `Ops.to_dict()`'s
return value using a fixture literally named `..._info` (e.g.
`IosxeInterfaceOutput_info`) — i.e. `to_dict()` appears to wrap the `.info`
dict under an `"info"` key. `pyats-shim/app/diff.py`'s `_unwrap()` acts on
that assumption: it extracts `snapshot["info"]` when present, else falls
back to the whole dict unchanged. This is unverified against a real pyATS
install (tracked in "Open items" below, since `docker build` for
`pyats-shim` has never been confirmed working in this dev environment) — if
it turns out to be wrong, `_unwrap()` is the only place that needs to
change.

**What already exists to build on.** `get-pyats-snapshot` stores each
feature's `to_dict()` result as a JSON artifact via `ArtifactService`, plus
a lightweight per-feature success/error summary in
`device.parsed[output_key]` (`{"kind": "pyats_snapshot", "artifact_ref":
..., "features": {...}}`). `workflow_steps/common/content_resolver.py`
already recognizes `content_source: "pyats_snapshot"`, so `store-artifact`
(export a snapshot to git/filesystem) and `compare-data` (compare a live
snapshot against a stored reference) both work with snapshots, with no shim
changes. `compare-data`'s diff (`GitDiffService.compare_text_content`) is a
plain line-based text diff of the JSON, though — no concept of "ignore this
counter" — every dynamic field change shows up as a mismatch. Excluding
that noise automatically is exactly what `compare-pyats-snapshot` adds.

**Implemented shape of the Genie-native Compare Snapshot step:**

- A lightweight shim endpoint — no subprocess, no testbed, no device I/O,
  since this is pure computation on two already-learned dicts:
  `POST /v1/diff` (`pyats-shim/app/diff.py`) takes
  `{"snapshot_a": {...}, "snapshot_b": {...}}`, runs
  `genie.utils.diff.Diff(a, b); diff.findDiff()` (after the `_unwrap()` step
  above), and returns `{"identical": bool, "diff": str}` — `str(diff)` is
  Genie's human-readable line-based format, `identical` is a plain flag so
  the backend step doesn't need to parse that text to route match/mismatch.
- Backend side (`workflow_steps/compare_pyats_snapshot/executor.py`):
  resolve the live `pyats_snapshot` artifact via
  `workflow_steps/common/content_resolver.py`'s existing `pyats_snapshot`
  support (content source is hard-coded, not user-selectable), load the
  reference snapshot JSON via `compare-data`'s
  `reference_reader.py` (git or filesystem — reused as-is, since a
  previously-exported `pyats_snapshot` JSON file **is** a text blob from
  that mechanism's point of view), extract the one configured `feature`'s
  `data` payload from both sides, POST them to `/v1/diff` via
  `PyATSShimService.diff()`, and store/display the result the same way
  `compare-data` stores a unified diff (`ArtifactRef` + a
  `comparison_diff`-shaped `device.parsed` entry, so `store-artifact` can
  export the Genie diff downstream with no `content_resolver.py` changes).
- Scope is **one Genie feature per step instance** (mirrors `compare-data`'s
  single-artifact-per-comparison model) — no `{feature}` filename
  placeholder; compare several features with several step instances.
- Doesn't replace `compare-data` — that step stays the right tool for
  text-based comparisons (raw configs). `compare-pyats-snapshot` is the
  dedicated home for Genie-semantic comparison specifically, since it needs
  the shim round-trip and a different diff algorithm than a text diff.

## Configure Replace Config

`configure-replace-config` applies a configuration file already on a
device (typically written there by an upstream Upload Config step) via
Cisco's `configure replace <file> time <n> force`, which schedules an
automatic on-device rollback after `n` minutes unless `configure confirm`
is sent first. It needs **zero pyATS shim changes** -- the flow is composed
entirely from shim capabilities that already exist and are already used
elsewhere: `operation="learn"` (the same call `get-pyats-snapshot` uses)
captures a Genie `interface` snapshot before and after the replace,
`POST /v1/diff` (the same endpoint `compare-pyats-snapshot` uses) diffs
them, and `operation="execute"` sends both the replace and confirm CLI
commands. Each shim call is its own fresh connect/disconnect; there is no
need to hold one session open across the whole flow, because the rollback
timer is device-side, not tied to the CLI session that issued it.

`configure confirm` is deliberately withheld -- leaving the device to
auto-revert on its own timer -- whenever the post-change snapshot can't be
captured at all (the strongest signal the replace broke connectivity) or
when it differs from the pre-change baseline; both cases are reported as a
step failure. Like `get-pyats-config`/`get-pyats-snapshot`, this step reads
credentials and device connection info entirely from the `pyats_testbed`
bag written by an upstream Add Testbed step. See
`workflow_steps/configure_replace_config/executor.py`.

## Open items / verify during hardening

- **Per-device connect timeout.** `device.connect()` in `generic_script.py`
  currently uses pyATS/Unicon's own default timeout, which was observed
  taking well over 90 seconds against an unreachable address in testing.
  The outer `JobRunner` timeout bounds worst-case latency, but hitting it
  fails the **entire batch**, not just the unreachable device. Before
  relying on this against real device inventories, either tune a short,
  reliable per-connect timeout (the exact Unicon kwarg needs verifying
  against the pinned `pyats[full]` version — `connection_timeout` did not
  visibly shorten the hang in a quick local test) or keep batches small
  enough that one bad device doesn't stall the rest.
- **pyATS/Genie version pin.** `pyats-shim/requirements.txt` pins
  `pyats[full]>=26.0,<27.0` (pyATS uses CalVer tied to the release year).
  Re-verify this range resolves before bumping past the current year.
- **`docker build` not verified end-to-end in this environment** due to a
  local Docker credential-helper/keychain issue unrelated to this change
  (`error getting credentials - err: exit status 1, out: 'Keychain Error.
  (-2532x)'`, OrbStack's docker driver on macOS) — `docker compose config`
  confirms the compose file and variable substitution are valid, and the
  Dockerfile was reviewed manually, but a real `docker build`/`up` should
  be run once to confirm the image builds and the container passes its
  healthcheck.
- **`Ops.info` vs `Ops.to_dict()` unwrap assumption in `POST /v1/diff`.**
  `pyats-shim/app/diff.py`'s `_unwrap()` extracts `snapshot["info"]` before
  calling `genie.utils.diff.Diff()`, based on circumstantial (mocked-test)
  evidence rather than a real pyATS install — see "Genie-native snapshot
  comparison" above for the full reasoning. Verify directly once the
  `docker build` item above is resolved, e.g. in a
  `pyats shell --testbed-file testbed.yaml` session:
  ```python
  ops = dev.learn('interface')
  ops.info == ops.to_dict()   # or a structural diff of the two
  ```
  If they differ, `_unwrap()` is the only place that needs to change.
  `pyats-shim/tests/test_diff.py` is gated on `pytest.importorskip("genie")`
  and has not run against real Genie in this environment either.
