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
backend/main.py                            # PyATSShimService lifespan startup/shutdown, router registration
backend/services/auth/rbac_seed.py         # sources.pyats read/write/delete permissions

backend/tests/unit/test_pyats_source_config_service.py
backend/tests/unit/test_pyats_router_auth.py
```

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
    commands=["show running-config", "show startup-config"],
)
```

One call per device rather than Phase 1's "batch every device into one
call" — because devices may in principle reference different
`pyats_source_id`s, and per-device isolation keeps partial-failure handling
simple (one bad device's shim call failing doesn't block the others). If
job-startup overhead × device count proves too slow in practice, grouping
devices by `pyats_source_id` and batching is a possible follow-up.

The Genie-parsed result for both commands is written into
`device.parsed[output_key]` as `{"running": ..., "startup": ...}` — this is
the Genie-powered analog of the existing `parse-cisco-config` step (which
uses `cisco_config_parser`, not Genie), not a replacement for
`get-device-configs`. No raw-text artifact capture in v1 — only the
Genie-parsed structured result.

Full step-authoring convention: **doc/WORKFLOW-STEPS.md**'s "Calling pyATS
from a step" section.

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
