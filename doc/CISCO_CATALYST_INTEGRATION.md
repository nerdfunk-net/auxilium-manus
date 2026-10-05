# Cisco Catalyst Center Integration

Backend, API and UI integration with **Cisco Catalyst Center** (formerly DNA Center) through its
REST **Intent API**. It lets Auxilium Manus read a Catalyst Center's device inventory, use those
devices as workflow targets, and then act on them through the controller: run read-only CLI commands
(optionally TextFSM-parsed), fetch running configs, and read device facts, topology and health.

This document explains **what exists, why it was built this way, how to operate it, and how to extend
it** (new API calls, new workflow steps, new settings). It is the entry point; the research it rests
on is in [`CATALYST_CENTER_API_DIFF.md`](./CATALYST_CENTER_API_DIFF.md).

## Contents

- [Status at a glance](#status-at-a-glance)
- [Why it is built this way](#why-it-is-built-this-way)
- [File map](#file-map)
- [Concepts](#concepts)
- [Connection, authentication and resilience](#connection-authentication-and-resilience)
- [Release handling](#release-handling)
- [Device filters](#device-filters)
- [The workflow step: Get from Catalyst Center](#the-workflow-step-get-from-catalyst-center)
- [The command and config steps](#the-command-and-config-steps)
- [The details, topology and health steps](#the-details-topology-and-health-steps)
- [Backend API](#backend-api)
- [Frontend](#frontend)
- [Security](#security)
- [Errors and how they surface](#errors-and-how-they-surface)
- [Testing and live verification](#testing-and-live-verification)
- [How to extend it](#how-to-extend-it)
- [Gotchas learned from a real controller](#gotchas-learned-from-a-real-controller)
- [Known limits and open items](#known-limits-and-open-items)

---

## Status at a glance

| Capability | Backend service | API route | Workflow step | Verified against a real controller |
|---|---|---|---|---|
| Source management (create/edit/delete, test connection) | `source_config_service.py` | `/sources/catalyst_center` | n/a (Settings → Sources) | yes (DevNet sandbox) |
| Device inventory search with filters | `device_service.py` | `…/{id}/devices/preview` | **`get-catalyst-center-devices`** | yes |
| Device lookup (by id / IP / exact name) and counts | `device_service.py` | none | none yet | yes |
| Run read-only CLI (command runner) | `command_service.py` | none | **`run-catalyst-center-command`** | yes (`show clock`, `show ip interface brief` on 2 devices) |
| Fetch a device's configuration | `command_service.py` | none | **`get-catalyst-center-configs`** | yes (running config stored as an artifact) |
| Per-device facts (device, software, interfaces, VLANs, compliance) | `details_service.py` | none | **`get-catalyst-center-details`** | yes |
| Topology (physical, L3 per protocol), sliced per device | `topology_service.py` | none | **`get-catalyst-center-topology`** | yes (`bgp` rejected by the controller) |
| Device health (`/device-detail`) | `health_service.py` | none | **`get-catalyst-center-health`** | yes |
| Site list + site filter (devices by site, with sub-sites) | `site_service.py`, `device_service.py` | `GET …/{id}/sites` | `get-catalyst-center-devices` (`sites`, *Search sites…* button) | yes, but the sandbox has only the `Global` site — see limits |

"Verified" means exercised against the public Cisco DevNet always-on sandbox (a self-signed-certificate
controller with 4 virtual IOS-XE switches). It has **not** been run against a 2.3.3.x controller, a
controller that reports a product release, or 3.3.1 — see [Known limits](#known-limits-and-open-items).

---

## Why it is built this way

These are the decisions future changes should preserve unless there is a concrete reason to revisit them.

| Decision | Reason |
|---|---|
| **Talk to the REST API with `httpx`, not the `catalystcentersdk` / `dnacentersdk` Python SDK.** | The SDKs are synchronous (`requests`), while the backend is async FastAPI plus Hatchet workers. We also need controls the SDK does not offer: the SSRF guard, per-source TLS verify/no-verify pools, vault-resolved credentials per request, typed errors that never leak response bodies, and pooled app-scoped clients. We use ~10 endpoints; the SDK carries 1,100–1,900. It stays useful as an **offline reference** for paths and parameters (that is how the version diff was done). |
| **One shared client and service path, not one adapter per Catalyst Center version.** | For the endpoints we use, 2.3.3.x, 2.3.7.x and 3.1/3.2 expose the **same** set (verified by diffing SDK releases; see the API-diff doc). Per-version adapters would be code with nothing to adapt. Nothing is gated on the release today (see [Release handling](#release-handling)). |
| **Normalized domain models between the API and workflow steps.** | `CatalystCenterDevice` and `CatalystCenterCommandResult` (`models/catalyst_center.py`) and the whitelisted fact models in `models/catalyst_center_facts.py` are the only shapes steps see. Raw Intent API payloads stay inside `services/catalyst_center/`, so a future payload change is fixed in one place. |
| **Filters run on the controller, with a guard against pulling everything.** | A Catalyst Center can hold thousands of devices. The step requires a filter (or an explicit `allow_all`) and offers a `max_devices` cap that **fails** rather than truncates, because a workflow acting on a silently-incomplete target list is worse than a failed one. |
| **Site filtering resolves names to device ids with `GET /site` + `GET /membership/{siteId}`.** | The device list has no usable site filter (`location*` are deprecated/empty). This pair exists on **every** supported release line (2.3.3.x, 2.3.7.x, 3.x); the newer `/sites` and `networkDevices/assignedToSite` endpoints only exist from 2.3.7.x, so they are not used. Site names are validated against the real site list because the controller answers an unknown site with a 500 and a bad membership id with **HTTP 200 + an error body**. |
| **Credentials are a vault reference, not stored on the source.** | Same model as ISE/Nautobot/pyATS/Mattermost: the source stores a `credential_id` pointing at a **global** vault credential. Background (Hatchet) runs have no acting user, so private credentials can never resolve. |
| **The client is app-scoped and registered in *both* lifespans.** | `main.py` (API) **and** `hatchet/worker_services.py` (both workers). A step runs in a worker, so a service registered only in the API process would raise "not initialized" at run time. |
| **Immutable data throughout.** | Filters are a frozen dataclass; models are frozen Pydantic; the executor builds a new `WorkflowContext` with `model_copy` instead of mutating the input. |

---

## File map

```
backend/services/catalyst_center/
├── client.py                  # CatalystCenterService — app-scoped httpx pools, token auth, 401 retry, 429 backoff
├── credentials.py             # CatalystCenterCredentials (frozen: base_url, username, password, timeout, verify_ssl)
├── common/
│   ├── exceptions.py          # typed error hierarchy (see "Errors")
│   ├── ids.py                 # safe_device_id() — id validation before path interpolation
│   ├── coerce.py              # lenient text/number/integer/boolean coercion for controller payloads
│   ├── output.py              # clean_command_output() — strip echoed command + trailing prompt
│   └── version.py             # installed_version_label() (display only)
├── device_filters.py          # CatalystCenterDeviceFilters — validation, query params, CIDR prefilter/check
├── device_service.py          # CatalystCenterDeviceService — search/preview/get/find/count, site-aware selection
├── site_service.py            # CatalystCenterSiteService — site list + site -> member device ids
├── command_service.py         # CatalystCenterCommandService — command runner + device config
├── details_service.py         # CatalystCenterDetailsService — device/software, interfaces, VLANs, compliance
├── topology_service.py        # CatalystCenterTopologyService — physical + L3 graphs
├── health_service.py          # CatalystCenterHealthService — /device-detail
└── source_config_service.py   # CatalystCenterSourceConfigService — settings entry + vault credential

backend/models/catalyst_center.py                  # source API models + CatalystCenterDevice / CommandResult / preview models
backend/models/catalyst_center_facts.py            # normalized facts: details, software, interface, VLAN, compliance, health, topology
backend/routers/sources/catalyst_center/
├── crud.py                    # /sources/catalyst_center  (CRUD + test-connection)
└── ops.py                     # /sources/catalyst_center/{id}/devices/preview
backend/workflow_steps/get_catalyst_center_devices/  # executor.py, config.py
backend/workflow_steps/run_catalyst_center_command/  # executor.py, config.py
backend/workflow_steps/get_catalyst_center_configs/  # executor.py, config.py
backend/workflow_steps/get_catalyst_center_{details,topology,health}/  # executor.py, config.py
backend/workflow_steps/common/catalyst_center_targets.py  # per-source grouping, credentials, outcomes (shared by the command/config steps)
backend/workflow_steps/common/catalyst_center_facts.py    # run_fact_step(): shared driver of the three fact steps
backend/workflow_steps/common/device_builders.py     # device_context_from_catalyst_center()
backend/workflow_steps/common/textfsm_parse.py       # parse_with_textfsm(): ntc-templates -> {parsed, error}
backend/workflow_steps/registry.yaml                 # six entries, ids starting get-/run-catalyst-center-* (palette_category: cisco)
backend/services/execution/step_registry.py          # dispatch table entries
backend/service_factory.py                           # get/set_catalyst_center_app_service, build_catalyst_center_*_service
backend/dependencies.py                              # get_catalyst_center_source_config_service
backend/services/settings/source_keys.py             # SourceType "catalyst_center" -> sources.catalyst_center.<id>
backend/services/auth/rbac_seed.py                   # permissions sources.catalyst_center:{read,write,delete}
backend/main.py + backend/hatchet/worker_services.py # client startup/shutdown (BOTH)

frontend/src/components/features/settings/
├── dialogs/catalyst-center-source-dialog.tsx        # Add/Edit source dialog (with Test connection)
├── components/sources-settings-canvas.tsx           # section placed right below Cisco ISE
├── hooks/use-sources-settings*.ts                   # list/dialog/save state
└── types/settings-api.ts                            # CatalystCenter* payload types
frontend/src/components/features/workflow-steps/get-catalyst-center-devices/
├── index.tsx                  # ConfigPanel + PluginUIComponent export
├── filter-kinds.ts            # the filter catalogue (keys, labels, hints) — mirrors the backend
├── sites-dialog.tsx           # "Search sites…" picker (searchable multi-select of the controller's sites)
├── help-panel.tsx             # Help tab
└── preview-dialog.tsx         # device preview table
frontend/src/components/features/workflow-steps/{run-catalyst-center-command,get-catalyst-center-configs,get-catalyst-center-details,get-catalyst-center-topology,get-catalyst-center-health}/  # index.tsx + help-panel.tsx
frontend/src/components/features/workflow-steps/shared/catalyst-center-fact-fields.tsx  # checkbox group + output-key field
frontend/src/components/features/workflow-steps/shared/catalyst-center-source-{config.ts,select-dialog.tsx}
frontend/src/hooks/queries/use-catalyst-center-sources-{query,mutations}.ts, use-catalyst-center-sites-query.ts
frontend/src/hooks/queries/use-get-catalyst-center-devices-preview-mutation.ts
frontend/src/lib/{plugin-ui-registry.ts,query-keys.ts}  # registry entry; sourcesCatalystCenter keys
frontend/src/components/features/workflows/utils/step-visuals.ts  # icon (cisco palette needs one per step)

backend/tests/unit/test_catalyst_center_*.py (client, version, filters, services, output, facts services, fact-step executors,
  step registration), test_get_catalyst_center_devices_*.py, test_run_catalyst_center_command_executor.py,
  test_get_catalyst_center_configs_executor.py, test_device_builders.py
```

---

## Concepts

**Source.** A named connection (`source_id`, e.g. `lab-catalyst`). Non-secret settings live in the generic
`settings` table under `sources.catalyst_center.<source_id>`: `url`, `verify_ssl`, `timeout`,
`credential_id`, plus `source_id` / `source_type`. The username and password are a **global vault
credential** chosen by `credential_id` (it must carry a username; Catalyst Center's token endpoint uses
HTTP Basic). Multiple sources can coexist.

**Credentials resolution.** Every call resolves `CatalystCenterCredentials` server-side from the source
(`CatalystCenterSourceConfigService.resolve_credentials`). Steps and routes reference a `source_id`; they never
carry a URL or password.

**Service layers** (mirror the Nautobot/ISE split; no Repository, because Catalyst Center is an external
API, not a local table):

```
CatalystCenterService        low-level HTTP: auth, retries, error mapping       (one per process)
  └── per-credentials facades: Device / Site / Command / Details / Topology / Health services
        └── routers (ops.py, crud.py) and workflow-step executors
```

`service_factory.build_catalyst_center_{device,command,details,topology,health}_service(credentials)` wrap the shared client with
one source's credentials.

---

## Connection, authentication and resilience

`CatalystCenterService.request(credentials, method, path, *, params=None, json=None)` returns the decoded JSON
body (`{}` for an empty body).

- **Token auth.** `POST /dna/system/api/v1/auth/token` with HTTP Basic returns `{"Token": ...}`, sent afterwards
  as `X-Auth-Token`.
- **Token cache.** In memory, keyed by `(base_url, username, sha256(password))`, refreshed after 50 minutes
  (Catalyst Center tokens last 60). Changing a source's password therefore forces a fresh token. A lock prevents a
  thundering herd of token requests.
- **401 → re-authenticate once and retry.** A second 401 raises `CatalystCenterAuthError`.
- **429 → bounded retry.** Up to 3 retries; waits the server's `Retry-After` (seconds, capped at 30 s), otherwise
  1 s / 2 s / 4 s. Applies to the token request too. Exhausted retries raise `CatalystCenterRateLimitError`.
- **Two connection pools**, TLS-verifying and non-verifying, because `verify_ssl` is a per-source setting
  (lab controllers are usually self-signed). A warning is logged with the host (never credentials) when verification
  is off.
- **SSRF guard.** The URL passes `validate_outbound_http_url_async` on every request (blocks metadata addresses etc.).
- **Timeouts and transport errors** map to `CatalystCenterAPIError` with generic text; response bodies are never
  included in messages.

---

## Release handling

`common/version.py` has one function, `installed_version_label(payload)`: it returns the string
`GET /dna/intent/api/v1/dnac-release` reports (`response.installedVersion`, then `response.version`) **verbatim, for
display only**. The DevNet sandbox returns the platform build `3.722.75335` there, not a product release, so nothing is
gated on it; test connection shows it as the "reported version". Release gating (a `CatalystCenterRelease` class and a
release-gated `/network-device/count`) existed until 2026-10 and was removed because no step used it.

---

## Device filters

`CatalystCenterDeviceFilters` (frozen) is the single source of truth, shared by the workflow step, the preview
endpoint and the tests. Build it with `CatalystCenterDeviceFilters.from_config(dict)`.

| Config key | Catalyst query param | Example |
|---|---|---|
| `sites` | *(not a query param — resolved via site membership)* | `Global/EMEA/Berlin` |
| `include_child_sites` (boolean, default `true`) | option of `sites` | `false` |
| `hostnames` | `hostname` | `sw.*`, `.*-core` |
| `management_ips` | `managementIpAddress` | `10.10.20.5`, `10.10.20..*` |
| `cidr` (single string) | prefilter on `managementIpAddress` + client check | `10.10.20.0/24` |
| `families` | `family` | `Switches and Hubs` |
| `roles` | `role` | `ACCESS`, `CORE` |
| `software_types` | `softwareType` | `IOS-XE` |
| `software_versions` | `softwareVersion` | `17.12.*` |
| `platform_ids` | `platformId` | `C9300-.*` |
| `serial_numbers` | `serialNumber` | `FOC.*` |
| `series` | `series` | `.*Catalyst 9000.*` |
| `device_types` | `type` | `.*9300.*` |
| `reachability_statuses` | `reachabilityStatus` | `Reachable` |
| `collection_statuses` | `collectionStatus` | `Managed` |

Server semantics (verified live; see the API-diff doc for the evidence):

- **Case-sensitive, whole-value match.** `sw` finds nothing; `sw.*` finds `sw1`–`sw4`; `SW1` does not match `sw1`.
- **`.*` is the only wildcard.** `.`, `|`, `[12]`, `\d`, `?`, `+`, `^`, `$` are *not* regex here and match nothing.
  A `.` is literal — which is why a wildcard IP range is written `10.10.20..*` (literal dot, then `.*`).
- **Repeated parameter = OR; different filters = AND.** `hostnames: [sw1, sw2]` + `roles: [ACCESS]` means
  (sw1 OR sw2) AND ACCESS. `to_query_params()` therefore returns a list per parameter.
- **Values are passed through untouched.** Nothing translates regex syntax, because the server would not honour it.
- **Validation** (raises `CatalystCenterValidationError`): unknown filter keys (catches typos like `hostname`),
  non-list values, > 50 values per filter, values > 255 chars or containing control characters, invalid CIDR.

**CIDR.** Catalyst Center has no subnet filter, so a CIDR is a two-stage filter: the controller is asked for the
whole octets the CIDR's first and last address share (`10.10.20.0/24` → `10.10.20..*`; `/32` → the exact IP; no shared
octet or IPv6 → no prefilter), then `matches_ip()` checks exact membership client-side (`10.10.20.176/31` selects
exactly `.176` and `.177`). If `management_ips` is also set, those are sent to the server and the CIDR is applied
client-side, preserving AND semantics.

---

## Site filter

A site is selected by its exact, case-sensitive `siteNameHierarchy` (`Global/EMEA/Berlin`). `CatalystCenterSiteService`
(`site_service.py`) does the resolution; `CatalystCenterDeviceService._select()` decides how to fetch.

**Endpoints** (same on 2.3.3.x, 2.3.7.x, 3.x): `GET /dna/intent/api/v1/site` (paged with 1-based `offset`/`limit`) and
`GET /dna/intent/api/v1/membership/{siteId}` (paged the same way; devices are in
`device[*].response[*]`, identified by `instanceUuid`, which equals the device list's `id`).

**Resolution rules**

1. Names are validated against the real site list. Unknown or wrong-case names raise
   `Unknown site '<name>'; use Search sites to pick an existing one` **before any membership call**.
2. `include_child_sites` (default true) adds every site whose path starts with `<name>/` — a path-prefix match, so
   `Global/EMEA` never pulls in `Global/EMEAX`. Doing this by name (not by trusting the controller) makes the result
   independent of whether membership is itself recursive, which could not be verified on the single-site sandbox.
3. More than 100 target sites is rejected (`MAX_TARGET_SITES`) — a parent such as `Global` on a big tree would otherwise
   fan out into hundreds of membership calls. Membership calls run with a concurrency of 5.
4. The member ids of all targets are unioned and de-duplicated.

**How devices are then fetched** (`_select`):

| Filters set | Strategy |
|---|---|
| no site | ordinary server-side filtered listing (+ exact client-side CIDR) |
| site **and** other filters | the controller narrows by the other filters; results are intersected with the site's member ids **client-side** |
| site only | fetch exactly the member devices with `GET /network-device?id=a,b,c`, 50 ids per request |

An **empty member set returns no devices without querying** — an empty `id` parameter would make the controller list
everything. The intersect strategy deliberately does not send `id=` together with other filters: the controller's docs say
`id` ignores other parameters, although the sandbox behaved as AND, so that behaviour is not relied on.

**Search sites… (UI).** In the Site filter row the button opens a dialog that calls `GET …/sites`, lists every site (indented
by depth) with a text filter, and adds the ticked ones to the filter. Sites already in the filter show as added. It is
disabled until a source is configured.

---

## The workflow step: Get from Catalyst Center

`id: get-catalyst-center-devices` · display name **Get from Catalyst Center** · `palette_category: cisco` ·
`artifact_type: inventory_selector` · `requires: []`, `produces: [identity]` · outcomes `success` / `failure`.
(When discussing it with the maintainer, cite id **and** name together.)

### Configuration

| Key | Meaning |
|---|---|
| `catalyst_center_source_id` | Required. A source from Settings → Sources. |
| `filters` | Object of the [filters above](#device-filters). |
| `allow_all` | Default `false`. With **no** filter the step fails unless this is `true`. |
| `max_devices` | Optional positive integer. More matches than this **fail** the step (never truncate). |
| `fan_out` | Standard inventory fan-out block, off by default (`workflow_steps/common/fan_out.py`). |

### Behaviour (`workflow_steps/get_catalyst_center_devices/executor.py`)

1. Parse and validate config. Bad config raises `ValueError` **before any I/O** (empty filters without `allow_all`,
   unknown filter key, invalid CIDR, bad `max_devices`, missing source).
2. Resolve the source's credentials; unknown source or unusable credential → `ValueError`.
3. `device_service.search_devices(filters, max_devices=…)`: pages through `GET /network-device` (500 per page,
   1-based `offset`), applies the CIDR check, and stops early once the cap is exceeded.
4. Map errors: validation / "matched more than N" → `ValueError` (configuration problem); API / auth failures →
   `RuntimeError`.
5. Build one `DeviceContext` per device (`device_context_from_catalyst_center`) and return a single `success`
   outcome with `summary="found N device(s)"`, metadata `<node>.source_id`, `<node>.total`, and `_fan_out` when enabled.
   Zero matches is a normal success.
6. Logs a start and a finish line (`get-catalyst-center-devices started/finished …`) per the step logging rule. Filter
   *values* are not logged.

### What a device looks like downstream

| `DeviceContext` field | Value |
|---|---|
| `id` | Catalyst Center device UUID |
| `name` | hostname, else management IP, else id |
| `hostname` (SSH target) | management IP when present (`bare_hostname`), else the name |
| `primary_ip4` | `managementIpAddress` |
| `platform` | `softwareType` |
| `network_driver` | `IOS-XE→cisco_xe`, `IOS-XR→cisco_xr`, `NX-OS→cisco_nxos`, `IOS→cisco_ios`; otherwise `None` (SSH steps then use their own default/override) |
| `source` / `source_id` | `catalyst_center` / the source id |
| `attribute_bags["catalyst_center"]` | a **copy** of the full inventory record, e.g. `{catalyst_center.role}`, `{catalyst_center.platformId}` |
| `capabilities` | `{identity}` |

The device-list payload carries no credentials, so nothing in the bag is sealed.

---

## The command and config steps

Two steps act on devices **through the controller** instead of over SSH, so a workflow needs no SSH credential for them.
Both are `palette_category: cisco`, `requires: [identity]`, outcomes `success` / `failure`, and take no source id of their
own: the target controller is each device's own `source_id`, so devices from several Catalyst Center sources can be mixed
in one step (credentials resolve once per source, before any I/O). A device whose `source` is not `catalyst_center`
fails individually with `not_catalyst_center_device` and goes out through `failure`. Shared helpers:
`workflow_steps/common/catalyst_center_targets.py`.

| Step (id · name) | Config | Result on the device |
|---|---|---|
| `run-catalyst-center-command` · **Run Command via Catalyst Center** | `commands` (1-20, unique, non-empty), `timeout` (1-300 s, default 300), `parser` (`none`/`textfsm`), `parsed_output_key` (default `parsed`), `network_driver_override` | one `CommandResult` per command under `command_results[node_id]`; the **cleaned** output (echoed command and trailing prompt removed) is stored as a `command_output` artifact; with `textfsm`, also `parsed.<key>.<command> = {parsed, error}` and capability `parsed` |
| `get-catalyst-center-configs` · **Get Config from Catalyst Center** | none | running config stored as a `running_config` artifact, `running_config_ref` set, capability `running_config` added |

Behaviour notes:

- **Batching.** The command step sends 20 devices per controller request, at most 3 requests in flight (the device limit is
  undocumented and not verified above 4 devices). **A controller request takes at most 5 commands** (verified live: 5 pass, 6 fail
  with HTTP 400 `Invalid input request`, whatever the device count), so `CatalystCenterCommandService.run_commands` splits longer
  lists into sequential requests of 5. The config step does one request per device, at most 5 in flight.
- **Failure scope.** Config errors (empty/duplicate/too many commands, bad `timeout`, unknown source) raise `ValueError`
  before any I/O. A controller or transport failure fails only the devices of that request (`catalyst_center_error`); a
  `failure`/`blocklisted` command status or a command missing from the response fails that device (`command_failed`,
  message lists the commands) but keeps its `CommandResult`s. The other devices continue through `success`.
- **`timeout` is capped at 300** because `CatalystCenterCommandService` polls the controller task for at most 150 x 2 s.
  Raising the cap means raising `max_polls` through `service_factory.build_catalyst_center_command_service` as well.
- **Read-only.** The step does not filter commands itself; the controller accepts `show`-class commands and answers
  anything else with `BLOCKLISTED`, which fails the device.
- **Config text.** What the controller returns starts with `Building configuration...` / `Current configuration : N bytes`
  and the byte count does not match the text length, so it is not byte-identical to an SSH `show running-config`. Compare
  steps that mix the two sources will see that header difference. Startup config is not offered by the controller; use the
  command step with `show startup-config`.
- **TextFSM parsing** (`parser: textfsm`) reuses Netmiko's `get_structured_data_textfsm` (ntc-templates) through
  `workflow_steps/common/textfsm_parse.py`, on the *cleaned* output, with the device's `network_driver` (`cisco_xe` falls back to
  `cisco_ios` inside Netmiko) or `network_driver_override`. The result has the same shape as Run Command's
  (`parsed.<parsed_output_key>.<command> = {"parsed": rows|None, "error": str|None}`), so downstream steps do not care which step
  produced it. It is non-fatal per command: no template, no driver, or a parse error gives `{parsed: null, error}` and the device
  still succeeds. Like `run-command`, the step promises no capability on its own (`guards.effective_produces`); downstream steps
  that need structured data use `requires_parsed`. Verified live on the sandbox: `show ip interface brief`, `show vlan brief`,
  `show spanning-tree`, `show vrf`, `show interfaces status`, `show version`. Genie is not offered here.
- Fan-out safe: per-device reads with no shared sink (see `WORKFLOW-STEPS.md`).

---

## The details, topology and health steps

Three read-only steps that read structured facts from the Intent API (no SSH, no command runner). All are `palette_category: cisco`,
`requires: [identity]`, `produces: [parsed]`, outcomes `success` / `failure`; like the command/config steps they use each device's
own `source_id` and reject non-Catalyst-Center devices (`not_catalyst_center_device`). They share `workflow_steps/common/
catalyst_center_facts.py::run_fact_step`, which runs at most 5 devices in flight and applies one result rule:

```
device.parsed[<parsed_output_key>][<fact>] = {"parsed": data | None, "error": str | None}
```

the same shape `run-command` (TextFSM/Genie) uses. A fact that fails is recorded as an error and **does not fail the device**; a device
fails (`catalyst_center_error`) only when *every* requested fact failed. Capability `parsed` is added to every device on the `success`
outcome (a device with no successful fact goes to `failure`), so these steps **do** guarantee `parsed` (`guards.effective_produces`
keeps their registry `produces: [parsed]`) and steps that `require` it, such as Config to Attributes, can follow them. Unlike
them, `run-command` and `run-catalyst-center-command` promise nothing, because their parsers are non-fatal. Facts are normalized, whitelisted models
(`models/catalyst_center_facts.py`) — never the raw record.

| Step (id · name) | Config | Endpoints |
|---|---|---|
| `get-catalyst-center-details` · **Get Details from Catalyst Center** | `facts` checkboxes: `device`, `software`, `interfaces`, `vlans`, `compliance` (default `device`, `interfaces`); `parsed_output_key` (default `catalyst_details`) | `GET /network-device/{id}` (serves both `device` and `software`, one request), `/interface/network-device/{id}`, `/network-device/{id}/vlan`, `/compliance/{id}` + `/compliance/{id}/detail` |
| `get-catalyst-center-topology` · **Get Network Topology from CC** | `topologies` checkboxes: `physical`, `l3_ospf`, `l3_isis`, `l3_eigrp`, `l3_static` (default `physical`); `parsed_output_key` (default `catalyst_topology`) | `GET /topology/physical-topology`, `/topology/l3/{ospf,isis,eigrp,static}` |
| `get-catalyst-center-health` · **Get Health Status from Catalyst Center** | `parsed_output_key` (default `catalyst_health`) | `GET /device-detail?identifier=uuid&searchBy=<id>` (fact name `health`) |

The topology is a **controller-wide graph**, fetched once per controller per step (`run_fact_step(prepare=...)`) and sliced per device by
`CatalystCenterTopology.for_device`: the device's own node plus its links seen from its side (`local_port`, `remote_port`, `remote_name`,
`remote_ip`, `remote_id`, speeds, `status`). A device missing from a graph gets `{node: null, links: []}`, not an error.

**URLs checked against the DevNet sandbox** (the first versions of these steps were specified from web search results; several were wrong):

| URL suggested | Result | Used |
|---|---|---|
| `/network-device/{id}`, `/interface/network-device/{id}`, `/device-detail` | OK (`/device-detail` needs `identifier=uuid&searchBy=<uuid>`) | as suggested |
| `/image/importation/device/{id}` | **404**; `/image/importation` and `/images` are a global catalog (empty on the sandbox) | `software` fact read from the device record |
| `/compliance/device/{id}` | **404** | `/compliance/{id}` (overall) and `/compliance/{id}/detail` (per type) |
| `/topology/network-topology` | **404** | `/topology/physical-topology`, `/topology/l3/{protocol}` |
| `/topology/l3/bgp` | HTTP 400 | not offered |
| `/topology/l2/{vlanId}` | HTTP 400 for vlan 1 | not offered (not investigated) |

**Feeding Nautobot.** `config-to-attributes` has a `source_format: catalyst_details` ("Cisco Catalyst Details") that turns the
`device`, `software` and `interfaces` facts into the device's `nautobot` attribute bag, for Add to Nautobot / Update Device
(`workflow_steps/config_to_attributes/catalyst_details.py`). Set its `parsed_key` to this step's `parsed_output_key`. Groups:
`interfaces` (name, `enabled` from `admin_status`, description, MAC, MTU, IPv4 as CIDR; access port -> `untagged_vlan = vlan_id`,
trunk -> `untagged_vlan = native_vlan_id`, VLAN 0 ignored, never `tagged_vlans` because the controller has no allowed-VLAN list)
and `device` (only for this format: `serial`, `software_version`, `platform.name = softwareType`, `device_type.model = platformId`
falling back to the long type string, manufacturer = the raw record's `vendor`, default Cisco). Role, status and location are not
derivable; use Set Default Attributes. The Nautobot platform must exist under the `softwareType` name (for example `IOS-XE`).

Notes: `/device-health` is a bulk alternative to `/device-detail` (one call for all devices) and is not used yet. The image catalog was
not built because the sandbox has no images to verify a shape against.

---

## Backend API

All under the API prefix; the frontend reaches them through the Next.js proxy (`/api/proxy/sources/catalyst_center/...`).

| Route | Permission | Purpose |
|---|---|---|
| `GET /sources/catalyst_center` | `sources.catalyst_center:read` | list sources |
| `GET /sources/catalyst_center/{source_id}` | read | one source |
| `POST /sources/catalyst_center` | `…:write` | create (`source_id`, `url`, `credential_id`, `verify_ssl`, `timeout`) |
| `PUT /sources/catalyst_center/{source_id}` | write | update |
| `DELETE /sources/catalyst_center/{source_id}` | `…:delete` | delete (never deletes the credential) |
| `POST /sources/catalyst_center/test-connection` | write | body is **either** `{source_id}` **or** `{url, credential_id, verify_ssl, timeout}` (XOR, like the other sources); returns `{success, message, release}` |
| `GET /sources/catalyst_center/{source_id}/sites` | read | the controller's sites `{sites: [{id, name, name_hierarchy}], total}`, sorted by hierarchy — feeds the *Search sites…* picker |
| `POST /sources/catalyst_center/{source_id}/devices/preview` | read | body `{filters, limit}` (`limit` 1–100, default 25) → `{devices[summary], truncated}`; the summary deliberately omits the raw record |

Permissions are seeded in `services/auth/rbac_seed.py`. `admin` gets all three; `viewer` gets `read`; the
**`ai-assistant` role is not granted** any of them (its allowlist is curated — add one only deliberately).

---

## Frontend

- **Settings → Sources** has a "Cisco Catalyst Center" section placed directly below Cisco ISE, with an Add/Edit dialog
  (source id, URL, credential picker, "Verify TLS certificate" toggle, timeout, Test connection). The toast shows the
  controller's *reported version*. Self-signed lab controllers need the TLS toggle off.
- **The step's ConfigPanel** follows `WORKFLOW-STEPS-STYLE_GUIDE.md`: narrow, `font-mono text-xs` parameter labels, `h-7`
  controls, step tokens only, no explanatory banner on the Configuration tab. Filters are a dynamic row list: *Add
  filter…* picks a kind, one value per line (`cidr` is a single input), × removes it. The filter catalogue lives in
  `filter-kinds.ts` and must match `device_filters.py`.
- Warning banners: "Add at least one filter, or enable allow_all" and "No filter set: every device … will be selected".
- **Help tab:** `help-panel.tsx` documents every control (case-sensitivity, `.*`, OR/AND, CIDR, the guard, preview).
- Server state uses TanStack Query via the `queryKeys.sourcesCatalystCenter` factory; no manual `useState + useEffect`.
- The cisco palette category has no `artifact_type` icon fallback, so `step-visuals.ts` maps each Catalyst Center step to an icon
  (`Server`, `TerminalSquare`, `HardDriveDownload`, `ListTree`, `Network`, `HeartPulse`).
- **Run Command via Catalyst Center** panel: command list (add/remove, max 20), `timeout`, `parser` select; the TextFSM option reveals
  `parsed_output_key` and `network_driver_override`.
- **Details / Topology** panels use the shared `FactCheckboxGroup` (`shared/catalyst-center-fact-fields.tsx`) — checkbox options must
  match `FACTS` / `TOPOLOGIES` in the executors — plus `ParsedOutputKeyField`; **Health** has only the output key; **Get Config**
  has no configuration. None of these panels has a source picker (the source comes from the devices).

---

## Security

- Credentials are **global vault** credentials only; the password never appears in settings, logs, step config, run
  data or error messages.
- Every outbound request passes the SSRF guard; `verify_ssl=false` is an explicit per-source opt-in and is logged.
- Device and task/file ids are validated against `^[A-Za-z0-9_-]{1,64}$` before being placed in a request path
  (`safe_device_id`), blocking path injection through ids returned by — or passed to — the controller.
- Upstream failures return generic text; 5xx responses use `core.safe_http_errors.raise_internal_server_error`
  (`{message, error_id}`), enforced by `scripts/check_http_500_leaks.py`. Never put `str(exc)` into a 5xx `detail`.
- The preview response excludes the raw inventory record.
- Command runner is **read-only** (Catalyst Center accepts only `show`-class commands); the service exposes no write path. The
  details/topology/health services issue GET requests only.
- Fact models are whitelisted: fields such as serial numbers of interface modules or raw inventory blobs are not copied through.

---

## Errors and how they surface

`services/catalyst_center/common/exceptions.py`:

```
CatalystCenterError
├── CatalystCenterValidationError          bad input / 400          → HTTP 400, step ValueError
│   └── CatalystCenterTooManyDevicesError  "matched more than N"    → step ValueError (mentions the cap)
├── CatalystCenterAuthError                bad credentials / 401·403 → test-connection "failed"; step RuntimeError
└── CatalystCenterAPIError                 transport / 5xx / bad body → HTTP 502 (preview); step RuntimeError
    ├── CatalystCenterNotFoundError        404
    ├── CatalystCenterRateLimitError       429 after bounded retries
    └── CatalystCenterTaskError            async command task failed / timed out
```

Test-connection never returns an upstream failure as a 5xx: it returns `{success: false, message: "Connection failed
(ref: <uuid>)…"}` and logs the detail against that reference.

---

## Testing and live verification

**Unit tests** (all mocked, no network; run from `backend/` with the project venv):

```bash
python -m pytest tests/unit/test_catalyst_center_*.py tests/unit/test_get_catalyst_center_*.py \
  tests/unit/test_run_catalyst_center_*.py tests/unit/test_device_builders.py tests/unit/test_sources_crud_routers.py -q
ruff check <touched files>        # scope to touched files; never repo-wide
pyright services/catalyst_center routers/sources/catalyst_center models/catalyst_center.py models/catalyst_center_facts.py \
  workflow_steps/get_catalyst_center_* workflow_steps/run_catalyst_center_command workflow_steps/common/catalyst_center_*.py
python scripts/check_asyncio_run.py && python scripts/check_http_500_leaks.py \
  && python scripts/check_router_repositories.py && python scripts/check_text_sql.py
```

Frontend: `npx tsc --noEmit` and a scoped `npx eslint <files>` from `frontend/`.

| Test file | Covers |
|---|---|
| `test_catalyst_center_client.py` | token auth/cache/expiry, 401 retry, 429 backoff, error mapping, TLS pool choice, SSRF |
| `test_catalyst_center_version_label.py` | label from the reported payload, incl. the real sandbox payload |
| `test_catalyst_center_device_filters.py` | parsing, query params, CIDR prefilter/check |
| `test_catalyst_center_device_service.py` | normalization, pagination, search/preview/cap |
| `test_catalyst_center_command_service.py` | command-runner flow, id validation, config text |
| `test_catalyst_center_source_config_service.py` | settings + vault credential handling |
| `test_catalyst_center_router.py`, `…_ops_router.py`, `test_sources_crud_routers.py` | routes, auth, status mapping, preview |
| `test_get_catalyst_center_devices_executor.py` | config guard, caps, mapping, fan-out, logging |
| `test_get_catalyst_center_devices_registration.py` | registry entry ↔ dispatch table ↔ `get_config()` stay in sync |
| `test_catalyst_center_output.py` | echo/prompt stripping |
| `test_run_catalyst_center_command_executor.py`, `test_get_catalyst_center_configs_executor.py` | config guard, batching, per-source credentials, failure scoping, artifacts |
| `test_catalyst_center_facts_services.py` | details / health / topology services: payload shapes from the sandbox, coercion, whitelisting, topology slicing |
| `test_catalyst_center_fact_steps_executors.py` | details / topology / health executors: config guard, checkbox selection, shared requests, partial vs total failure, per-source credentials |
| `test_catalyst_center_command_steps_registration.py` | all five command/config/fact steps: registry ↔ dispatch ↔ `get_config()` |

(`test_catalyst_center_command_service.py` also covers the 5-commands-per-request split; `test_run_catalyst_center_command_executor.py` the TextFSM parser.)

The command-runner response shapes in the unit tests were first spec-derived fixtures; live runs on the sandbox confirmed them.
The fact-service fixtures are trimmed copies of real sandbox payloads.

**Live verification** (how this integration was checked): write a throw-away script that instantiates
`CatalystCenterService` directly and calls the services with in-memory `CatalystCenterCredentials` — no DB rows, no
vault entries, and only read-only calls. The Cisco DevNet always-on sandbox is `https://sandboxdnac2.cisco.com`
(credentials are published on Cisco DevNet; do not commit them). It needs `verify_ssl=false`. To run the real executor
without a DB, patch `object_session` and `service_factory.build_catalyst_center_source_config_service`, and call
`service_factory.set_catalyst_center_app_service(...)`.

Browser UI automation is not available in every environment here; if it is not, say so and give a manual click-through
instead of claiming the UI was verified.

---

## How to extend it

### A. Add a new read-only API call

1. Confirm the path, verb, parameters and body shape — first in the SDK source or DevNet docs, then **against a real
   controller** (response bodies are where assumptions fail; the SDK validates requests only).
2. Add a path constant and an `async` method on `CatalystCenterDeviceService` or `CatalystCenterCommandService`
   (or a new focused service if it is a new domain; follow the Nautobot "resolver/manager" guidance in
   `doc/claude/backend.md`). Call everything through `self._client.request(...)` so auth, retries and error mapping are
   inherited.
3. Validate any id interpolated into a path with `safe_device_id`; validate inputs and raise
   `CatalystCenterValidationError`.
4. Return a **normalized frozen model** (`models/catalyst_center.py`, or `models/catalyst_center_facts.py` for per-device facts) with a
   whitelist of fields, using `common/coerce.py` for the loosely typed values; keep the raw payload inside the service.
5. Tests first (`AsyncMock` for the client; follow `test_catalyst_center_device_service.py`), then a live probe, then
   add the finding to `CATALYST_CENTER_API_DIFF.md`.

### B. Add a new workflow step

Three step kinds already exist: an **inventory selector** (`get-catalyst-center-devices`), **command/config** steps (command runner,
see above) and **fact** steps. A new read-only fact step (another Intent API read per device) should not copy an executor: write a
`collect(credentials, state, device_id, device)` coroutine returning `{fact: entry}` and hand it to
`workflow_steps/common/catalyst_center_facts.py::run_fact_step` (optional `prepare` for a once-per-controller fetch). It gives
the per-source credentials, concurrency limit, `{parsed, error}` shape, partial-failure rule and logging for free. Fact steps write
`device.parsed[<parsed_output_key>][<fact>]` directly (the `run-command` convention), not through `node_result.set_node_result`.

Read [`WORKFLOW-STEPS.md`](./WORKFLOW-STEPS.md) and [`WORKFLOW-STEPS-STYLE_GUIDE.md`](./WORKFLOW-STEPS-STYLE_GUIDE.md) first, then:

1. **Backend package** `backend/workflow_steps/<snake_step_id>/` with `__init__.py`, `config.py` (`get_config()`),
   `executor.py` using the exact `execute(*, config, context, run, artifact_service, node_id, device_sessions)` signature.
   Copy the shape of `get_catalyst_center_devices/executor.py`: parse config → `ValueError` before any I/O →
   `object_session(run)` →
   `service_factory.build_catalyst_center_source_config_service(db).resolve_credentials(source_id)` →
   `service_factory.build_catalyst_center_command_service(credentials)` → map errors (validation → `ValueError`,
   API/auth/task → `RuntimeError`) → start/finish `logger.info` → new `WorkflowContext` via `model_copy`.
2. **Registry** entry in `workflow_steps/registry.yaml` (use `palette_category: cisco` to sit with the other Cisco steps;
   document every config key in `metadata.configuration_input`) and one import + one entry in
   `services/execution/step_registry.py`.
3. **Frontend** `workflow-steps/<kebab-id>/index.tsx` (`ConfigPanel` + `HelpPanel`), register in
   `lib/plugin-ui-registry.ts`, and add an icon in `step-visuals.ts` (required for the cisco category).
   Reuse `shared/catalyst-center-source-select-dialog.tsx` and `shared/catalyst-center-source-config.ts`.
4. **Tests**: executor tests (mirror `test_get_catalyst_center_devices_executor.py`) and a registration test (mirror
   `test_get_catalyst_center_devices_registration.py`); the plugin-registry consistency suites must stay green.
5. **Docs**: add the step to this file's status table, and to the inventory/step lists in `WORKFLOW-STEPS.md` if relevant.

Notes specific to Catalyst Center steps:

- **Command output is raw terminal text** — it includes the echoed command and the trailing prompt
  (`show clock\n*15:22:13.553 UTC …\nsw1#`). Strip them before parsing. Write results through the existing
  `command_results` / `running_config_ref` + `ArtifactService` conventions, and `node_result.set_node_result` for
  `device.parsed`.
- Command runner request limits: **5 commands per request** (verified live; `run_commands` splits for you). The devices-per-request
  limit is not documented; chunk conservatively and verify live.
- The command runner is asynchronous (submit → poll task → download file). `CatalystCenterCommandService` already does
  this and raises `CatalystCenterTaskError` on failure or timeout; the poll interval and maximum polls are constructor
  arguments.
- Respect fan-out safety (see `WORKFLOW-STEPS.md`): per-device reads are concurrency-safe; anything writing to a shared
  sink must be per-device-unique or placed after a Fan In. Fan-out also multiplies requests against one controller — the
  429 backoff protects you, but prefer a sensible `max_concurrency`.
- If the step writes any secret-like value into `attribute_bags`, seal it with `seal_secret()` (see the secret-valued
  attributes section of `WORKFLOW-STEPS.md`).

### C. Add behaviour that differs between Catalyst Center releases

Do **not** add a per-version adapter unless the endpoint sets truly diverge. Instead:

1. Prove the difference with the SDK diff method in `CATALYST_CENTER_API_DIFF.md` and on a real controller of each line.
2. Re-introduce a small release type in `common/version.py` and gate on it in the service.
3. Fail safe: when the release is unknown, take the path that works on every release.

### D. Add a field to the source configuration

Touch: `models/catalyst_center.py` (create/update/response models) → `source_config_service.py`
(`create_source`/`update_source`/`resolve_credentials`, and `CatalystCenterCredentials` if the client needs it) →
`routers/sources/catalyst_center/crud.py` → frontend `types/settings-api.ts`, `catalyst-center-source-dialog.tsx`,
`use-sources-settings.ts`. There is no backward-compatibility layer to maintain (single-user dev system, no saved
workflows to migrate), so a clean breaking change is acceptable.

### E. Add another filter kind

A filter that maps to a device-list query parameter: add it to `_LIST_FILTERS` in `device_filters.py`, to
`FILTER_KINDS` in `filter-kinds.ts` (same key), to the registry `filters` description, and to the Help tab — keep all four
in sync, and add a case to `test_catalyst_center_device_filters.py`. A filter that needs a lookup (like `sites`) instead
gets its own resolution step in a service and a branch in `CatalystCenterDeviceService._select()`; keep the
`allow_all`/`max_devices` guard semantics unchanged.

---

## Gotchas learned from a real controller

| Symptom / assumption | Reality (DevNet sandbox) |
|---|---|
| "`dnac-release` returns the product release." | It returned the platform build `3.722.75335` (`systemVersion 2.7.72`, packages `2.722.x`). No field held `2.3.7.x`. Never trust it for gating. |
| TLS verification | Fails (self-signed). Works with `verify_ssl=false`. |
| "`hostname=sw` finds `sw1`." | No: whole-value, case-sensitive. Use `sw.*`. |
| Regex filters | Only `.*` works; `.`, `\|`, `[12]`, anchors match nothing. |
| Several values in one filter | Repeat the query parameter (OR). Comma lists only work for `id`. |
| A subnet filter | Does not exist. Prefix prefilter + client-side check. |
| `location` / `locationName` for site filtering | Deprecated and `null` on every sandbox device. |
| `GET /site?name=<unknown path>` | HTTP **500**, not an empty list — never pass user text through; validate against the site list. |
| `GET /membership/{bad id}` | HTTP **200** with `{"response": {"errorCode": …}}` bodies instead of an error status — check the body shape. |
| Devices in `Global` | Appear in `Global`'s membership although their `location`/`locationName` are `null`. |
| `network-device?id=<sw1>&hostname=sw4` | Returned nothing (AND) on the sandbox although the docs say `id` ignores other params — not relied on. |
| Command output | Contains the echoed command and the prompt. |
| Device config response | `GET /network-device/{id}/config` returns a plain text body in `response`. |
| Filtered `count` | `count?hostname=sw1` returned 1 (vs 4 unfiltered), so hostname is honoured. IP and role counts were inconclusive (every sandbox device matches them). The count endpoint is not used by the code any more (removed with the release gating). |

---

## Known limits and open items

- **Not verified live:** 2.3.3.x controllers, a controller reporting a real product release, and 3.3.1. No `catalystcentersdk` exists for 2.3.3.x or 3.3.1, so the SDK diff stops at
  2.3.7.9 / 3.1.6 / 3.2.3.
- **Preview with a very wide CIDR** (for example `/1`, no shared octet) can scan every page of devices; the page bound is
  200 × 500 devices. Unbounded in time on a huge controller. Narrow the CIDR or add another filter.
- **Details/topology/health steps verified live only on the sandbox** (`sw1`/`sw2`, all facts and all four L3 protocols). The sandbox
  has no OSPF/IS-IS/EIGRP/static data of its own (the L3 graphs are the same as the physical one), so the L3 shapes are only
  proven to parse, not to carry protocol-specific data. Compliance types other than RUNNING_CONFIG/PSIRT/IMAGE/EOX/NETWORK_SETTINGS
  and multi-site fields (`location_name`) are unseen.
- **Command/config steps verified live only on the sandbox** (2 virtual IOS-XE switches, `show clock` / `show ip interface brief`,
  running config). Not verified: batches above one device chunk, a blocklisted command on a real controller, other platforms
  (IOS-XR, NX-OS) and the controller's real per-request limits.
- **Site filter on a multi-site tree is not verified live.** The sandbox only has `Global`. Verified there: site list,
  membership by id (paged), site-only / site+filters / site+CIDR selection, unknown and wrong-case names, the cap, and the
  preview. Not verified: sub-site expansion on a real hierarchy, whether a parent's membership already includes
  descendants (harmless — the union is idempotent), `/site` and `/membership` paging beyond one page, and that the
  `/site` response on 2.3.3.x matches (it is in the 2.3.3.0 SDK; shape assumed identical).
- **Site-only selection of a very large site** issues one request per 50 member devices; combine it with another filter
  (for example a role) so the controller narrows first.
- **Token lifetime** is assumed to be 60 minutes (refreshed at 50); expiry is handled by the 401 retry either way.
- **Command-runner limits:** 5 commands per request is verified; the per-request device limit is not (the sandbox has 4 devices).
- The browser UI was reviewed through type-checking, linting and the API, not an automated browser session.
