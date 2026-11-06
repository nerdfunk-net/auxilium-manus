# Cisco ACI (APIC) Integration — Plan

Status (2026-11-06): **phases 1-5 built** (client, device service, source + CRUD + test-connection, workflow step + preview, frontend); Ask the Net still to do. Read-only source for the leaf and spine switches of an
ACI fabric, usable as workflow targets and from Ask the Net. Modelled on
[`CISCO_CATALYST_INTEGRATION.md`](./CISCO_CATALYST_INTEGRATION.md).

## Decisions (maintainer, 2026-11-06)

| # | Decision |
|---|---|
| 1 | v1 = device inventory as workflow targets (one step). Design so facts (interfaces, LLDP, health, faults) can be added later without reshaping the client. |
| 2 | Leaf and spine only. APIC controllers are filtered out. |
| 3 | ACI is a data source only (no SSH through it). Keep the device model able to carry a management IP and platform later. |
| 4 | Username + password (no certificate/signature auth). |
| 5 | One APIC URL per source. |
| 6 | Ask the Net gets read tools for ACI. |
| 7 | Verification target: the DevNet always-on sandbox `sandboxapicdc.cisco.com`. Its credentials live in the vault credential and a git-ignored `backend/.env.test`, never in source, docs or tests. |

## What the sandbox showed (probed read-only, 2026-11-06)

* Login `POST /api/aaaLogin.json` returns `refreshTimeoutSeconds=600`, `maximumLifetimeSeconds=86400` and a
  `version` field (`6.1(4h)`), so **test-connection can read the APIC version straight from the login reply**.
* **The sandbox runs 6.1(4h), not 6.2.** 6.2 cannot be verified here; production is 6.1, so 6.1 is covered.
  6.2 support rests on the documented class model being unchanged — flag it as unverified in the final doc.
* `fabricNode` (4 rows: apic1, leaf-1, leaf-2, spine-1): `id`, `name`, `role` (`leaf|spine|controller`), `serial`,
  `model`, `version` (`simsw-6.1(4h)` on the simulated switches), `fabricSt`, `dn` (contains the pod), and
  `address` = **TEP address (10.0.64.x), not a management IP**.
* `topSystem` carries `oobMgmtAddr` / `inbMgmtAddr`, but on the sandbox switches both are `0.0.0.0`. Only the APIC has
  one. `mgmtRsOoBStNode` (static OOB node addresses, `addr` is `ip/prefix`) exists and lists the APIC only.
  → The management IP must be **optional** in the model; treat `0.0.0.0` / `::` as "unknown". Never present the TEP
  address as a management IP.
* `firmwareRunning` (switches, 3 rows) and `firmwareCtrlrRunning` (APIC) give the running version.
* `query-target-filter=and(eq(fabricNode.role,"leaf"),wcard(fabricNode.name,"leaf"))` works server-side.
* Logout `POST /api/aaaLogout.json` → 200.

## Design

```
backend/services/aci/
├── client.py            AciService — app-scoped httpx pools (verify / no-verify), session cache per
│                        (base_url, login name, sha256(password)); a new login (not aaaRefresh) 60 s before the
│                        `refreshTimeoutSeconds` the APIC reports, one re-login on 403, 429 backoff, SSRF guard,
│                        explicit `Cookie: APIC-cookie=` header + pool cookie jars cleared after every response
│                        (the pools are shared by all sources), paging, typed errors; GET only (the transport
│                        refuses every method except GET and the login POST)
├── credentials.py       AciCredentials (frozen: base_url, username, password, timeout, verify_ssl, login_domain)
├── common/              exceptions.py, coerce.py (APIC returns every number as a string), dn.py (pod/node from dn)
├── device_filters.py    AciDeviceFilters (frozen): names, roles(leaf|spine), pod_ids, node_ids, models, serials,
│                        versions, fabric_states, management CIDR. Only the role is narrowed on the APIC; the rest
│                        is client-side: case-sensitive whole-value match, `*` and `?` the only wildcards (regex
│                        characters are literal), values of one filter OR, filters AND, a device without a
│                        management IP never matches a CIDR. (Deliberately not Catalyst's `.*` dialect.)
├── device_service.py    AciDeviceService — fabricNode (+ topSystem for mgmt IPs) -> AciDevice
└── source_config_service.py  AciSourceConfigService (CredentialedHttpSourceService subclass)
backend/models/aci.py                         source API models + AciDevice (frozen)
backend/routers/sources/aci/{crud.py,ops.py}  via build_source_crud_router; ops = devices/preview
backend/workflow_steps/get_aci_devices/       executor.py, config.py; registry.yaml; step_registry.py
backend/core/source_keys.py                   SourceType "aci"
backend/services/auth/rbac_seed.py            sources.aci:{read,write,delete} (write/delete admin-only, P3)
backend/service_factory.py, dependencies.py   app service + builders
backend/main.py + backend/hatchet/worker_services.py   startup/shutdown in BOTH lifespans
backend/services/ai_assistant/tools/aci_tools.py + aci_reader.py   Ask the Net tools (see below)
frontend: source dialog, sources canvas section, step ConfigPanel + preview, plugin-ui-registry, query keys,
          hooks/queries/use-aci-sources-*, step-visuals icon
```

Decisions inherited from Catalyst Center: `httpx` not the `acitoolkit`/`cobra` SDK (sync, no SSRF/TLS control);
one client for 6.1 and 6.2, nothing gated on the version (the version is displayed only); filters run on the
controller where APIC supports it, with a `max_devices` cap that **fails** rather than truncates; credential is a
global vault credential referenced by `credential_id`; frozen dataclasses/models.

**Read-only enforcement.** The client exposes only `get()`, plus private login/refresh/logout. A unit test asserts no
other method can be issued. Operators should still use an APIC user with a read-all role.

**Login domain.** Optional source field; sent as `apic:<domain>\<user>`.

**Paging.** `page-size=1000`, loop on `page` until `len(imdata) < page-size`; `totalCount` is a string.

**Class-name injection.** Class names and filter values are never taken raw from a user/model: classes are constants,
filter values are validated (no `"`, control characters, length cap) before being put in a `query-target-filter`.

## Ask the Net

Same pattern as `catalyst_center_tools.py` (§42 of `AI_TOOL_CHAIN.md`): `find_aci_device` (name, serial or node id) and
`get_aci_device_details`; permission `sources.aci:read` checked on every call; the user's inventory switch gates
names/models, the addresses switch gates management IPs and serials; a missing source is reported to the user.
Wiring: `surfaces.py`, `routers/ai_assistant.py` (`can_read_aci`), `playbook_tools.known_general_tool_names`,
`DataClass` per field (fail closed). Document as a new section in `AI_TOOL_CHAIN.md`.

## Build order (test first, one commit per phase)

1. Client + credentials + errors + read-only guard (unit tests with `httpx.MockTransport`).
2. Models, filters, device service (unit tests; fixtures copied from the real sandbox payloads above).
3. Source config service, source type, RBAC, CRUD router, lifespans (both), test-connection (shows APIC version).
4. Workflow step `get-aci-devices` + registry + preview endpoint + `device_builders` entry.
5. Frontend: source dialog, step panel, preview.
6. Ask the Net tools + docs (`AI_TOOL_CHAIN.md`, `CLAUDE.md` integrations line, `rbac_seed` docs in `auth.md`).
7. Live check against the sandbox from a scratch cwd (see memory: live test isolation), integration test marked opt-in.

## Open items / risks

* 6.2 unverified (sandbox is 6.1(4h)).
* Management IPs absent on the sandbox switches; the step must work (and be honest) with no IP. Whether to fall back to
  `mgmtRsOoBStNode` / `mgmtRsInBStNode` when `topSystem` is empty is to be decided against a real fabric.
* The sandbox switches are simulated (`simsw-` versions); real hardware may differ in `version` format.
* DevNet sandbox is shared and resets; do not rely on its contents in tests.

## Built so far (phase 3 notes)

* Source type `aci` (`sources.aci.<id>` settings rows), credential type `generic` (user + password), permissions
  `sources.aci:{read,write,delete}` (write/delete admin-only through the existing `sources.*` rule P3). The seeded
  `viewer` role does **not** hold `sources.aci:read`, so viewers have no ACI source and, later, no ACI tools.
* Routes `GET/POST /sources/aci`, `GET/PUT/DELETE /sources/aci/{id}` from `build_source_crud_router`, plus
  `POST /sources/aci/test-connection` (needs `write`, rate limited as `aci-test-connection`). Test-connection logs in afresh,
  reads one `fabricNode` row (a login can succeed for a user who may read nothing) and reports the APIC version.
* A remote (non-local) APIC user is entered in the credential's username as `apic:<domain>\<user>`; the source has no
  separate login-domain field.
* The client is started and stopped in `hatchet/worker_services.py`, the one lifespan the API and both workers share.
* Request models forbid unknown fields (the ratchet list in `test_request_models_forbid_extra.py` was not extended).

## Built so far (phase 4 notes)

* Step `get-aci-devices` ("Get from ACI", `cisco` palette, `inventory_selector`, produces `identity`):
  `workflow_steps/get_aci_devices/{config,executor}.py`, registry entry, dispatch entry. Config keys `aci_source_id`,
  `filters`, `allow_all`, `max_devices`, `fan_out` (fan-out off by default, like the other inventory steps).
  An empty filter fails unless `allow_all` is set (a downstream step may act on every switch of the fabric);
  `max_devices` fails instead of truncating. Config problems are `ValueError`, APIC problems `RuntimeError ... from exc`
  so the runner reads the structured failure record from the cause chain.
* `DeviceContext` (`device_context_from_aci`): id `aci-<source_id>-<node_id>` (unique across sources), `name` = fabric
  node name, `source="aci"`, `platform="Cisco ACI"`, `primary_ip4` = management IP or `None`, hostname falls back to the
  name; the TEP address is never used as an address. **`network_driver` is deliberately unset**: ACI is a data source
  here and SSH to the switches was never verified. Set it (probably `cisco_nxos`) when SSH steps are in scope.
  `attribute_bags["aci"]` holds the normalized fields plus `raw.fabric_node` / `raw.top_system` for downstream steps.
* `POST /sources/aci/{source_id}/devices/preview` (needs `sources.aci:read`, rate limited as `aci-device-preview`) for the
  step's preview dialog; a summary only, never the raw record.
* Verified live against the DevNet sandbox with the real executor: name/role/node-id filters, `allow_all`, the
  `max_devices` and no-filter guards.

## Built so far (phase 5 notes: frontend)

* Settings -> Sources: a **Cisco ACI** section and `aci-source-dialog.tsx` (source id, URL, global credential, verify TLS,
  timeout, Test connection that shows the APIC version). Wired through `use-sources-settings*.ts`, `sources-settings-canvas.tsx`,
  `settings-sections.ts` (`sources.aci:read` shows the Sources tab). Hooks `use-aci-sources-{query,mutations}.ts`, query key
  `sourcesAci`, types `Aci*` in `settings-api.ts`.
* Step UI `workflow-steps/get-aci-devices/` (`index.tsx` ConfigPanel, `filter-kinds.ts`, `preview-dialog.tsx`, `help-panel.tsx`),
  `shared/aci-source-{config.ts,select-dialog.tsx}`, `use-get-aci-devices-preview-mutation.ts`; palette group **Cisco -> ACI**
  (`step-visuals.ts`, `Waypoints` icon) and `plugin-ui-registry.ts`.
* Filters: `roles` is a pair of checkboxes (leaf/spine, never the controller); `pod_ids` / `node_ids` digit-only lines are sent as
  numbers (anything else stays text so the backend names the problem); `*` / `?` wildcards are documented, not Catalyst's `.*`.
  Blank lines are kept while typing and ignored by the backend (a bug in the number filters found here and fixed + tested).
* Tests: filter-kinds, aci-source-config, source select dialog, ConfigPanel (roles, guards, preview gating, immutability),
  plus ACI rows in the two settings-hook tests. Frontend suite 2267 pass, `tsc` and ESLint clean, coverage above the ratchet.
* **Browser pass** on an isolated stack against the DevNet sandbox: create the source in the UI, Test connection toast "Connection
  successful (APIC version 6.1(4h))", step in the library under Cisco -> ACI, node on the canvas, ConfigPanel with real Radix
  selects, preview of the leaves (2) and of role=leaf AND node 101 (1, with a trailing blank line), Help tab.
* Known, not ACI-specific: on a short window the dialog's Save button is below the fold (Catalyst's dialog is the same);
  the builder logs a 422 for `GET /workflows/null` on a new workflow.

## Review fixes (2026-11-06, `doc/analysis/REVIEW.md`)

All eight findings were reproduced or confirmed in code and fixed test-first.

1. **Wildcard ReDoS.** `*` / `?` matching is a linear scan with one backtrack point (`device_filters._wildcard_match`), no
   regular expression; a test compares it with the regex definition on every short input and another proves 255 stars are instant.
2. **Paging with a missing `totalCount`.** `totalCount` is only an extra stop when it parses; a missing or garbage value never ends
   paging, only a short page does.
3. **Runaway paging.** Every raw object counts toward `max_objects` (also objects of another class that are not returned), so a source
   that keeps sending full pages ends with `too_many_objects` after about 51 requests at the defaults.
4. **Numeric `pod_ids` / `node_ids` in the step panel.** `filtersFromConfig` keeps whole numbers (as the text the textarea edits), so
   the panel, the preview and the saved config describe the same filter.
5. **Malformed `source_id` on test-connection / preview.** `routers/sources/aci/resolve.py` validates the id like `build_source_key`
   and answers 400; one shared resolver replaces the two copies. (The Catalyst/ISE/pyATS routers have the same gap; not changed here.)
6. **IPv6 CIDR.** Rejected with a validation error, since management addresses are IPv4 only.
7. **Unticked role row.** The hint and the Help tab now say it is not a filter: leaf and spine are both taken only together with another
   filter or `allow_all`.
8. **Login lock.** One lock per fabric login, so a slow APIC does not block other sources; a short APIC session timeout is never cached
   past its real expiry (`max(timeout - 60, timeout / 2)`).

Deliberate, not defects: IPv6 management addresses (`oobMgmtAddr6` / `inbMgmtAddr6`) are ignored, so an IPv6-only fabric shows
switches without a management IP; there is no `aaaLogout` (a new login replaces the cached token before the old one idles out);
`attribute_bags["aci"]` keeps the raw APIC attributes including the TEP, like the other inventory steps keep their raw record, and no
step may use `tep_address` as a management address.

