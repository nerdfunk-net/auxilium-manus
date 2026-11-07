# Cisco ACI (APIC) Integration — Plan

Status (2026-11-07): **built:** client, device service, source type + CRUD + test-connection, and six workflow steps with frontend
(`get-aci-devices`, `get-aci-details`, `get-aci-policy`, `find-aci-endpoints`, `compare-aci-subnets`, `backup-aci-config`; see the sections
at the end of this file) plus the `config-to-attributes` format `aci_details`. **Not done:** the Ask the Net tools (plan:
[`plans/ACI_TOOL_CHAIN.md`](./plans/ACI_TOOL_CHAIN.md)) and the live check of the newer read paths (list in
[`plans/ACI_CONTINUE.md`](./plans/ACI_CONTINUE.md)). Read-only source for the leaf and spine switches of an
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
6. Ask the Net tools + docs: planned in `doc/plans/ACI_TOOL_CHAIN.md` (the `CLAUDE.md` integrations line and the `auth.md` note exist already; `AI_TOOL_CHAIN.md` section 47 comes with the tools).
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


## Step `get-aci-details` ("Get Details from ACI", 2026-11-06)

Reads per-switch facts from the APIC REST API (no SSH). Place it after `get-aci-devices`; other devices fail with
`not_aci_device` (`aci_node_unknown` if the node id cannot be found). Output: `parsed.<parsed_output_key>.<fact> = {parsed, error}`,
default key `aci_details`. A fact that fails is recorded with its error; the device fails only if every fact failed.

| Fact | APIC classes | Notes |
|---|---|---|
| `device` | `fabricNode` (the node MO itself), `topSystem` | uptime, serial, role, state |
| `software` | `topSystem` / `firmwareRunning` data | version, model |
| `hardware` | `eqpt*` | chassis, cards, PSU, fans |
| `interfaces` | `l1PhysIf`+`ethpmPhysIf`, `pcAggrIf`, `pcRsMbrIfs`, `mgmtMgmtIf`, `l3LbRtdIf`, `sviIf`, `ipv4Addr` | row caps per class |
| `neighbors` | `lldpAdjEp`, `cdpAdjEp` | CDP attribute names best effort, unverified live |
| `vlans` | `l2BD`, `l3Ctx` | |
| `health` | `sys/health`, `sys/ch/health` | |
| `faults` | `faultInst` | |
| `routes` | `ipv4Route`, `ipv4Nexthop` | |
| `protocols` | `bgpPeer`, `bgpPeerEntry`, `isisAdjEp`, `ospfAdjEp` | state names best effort, sandbox has no rows |
| `endpoints` | `epmMacEp`, `epmIpEp` | |
| `vpc` | `vpcDom`, `vpcIf` | |
| `epgs` | `vlanCktEp` (+ `l2BD`, `l3Ctx`) | EPGs deployed on the leaf: tenant / app profile / EPG from `epgDn`, `pcTag`, encap, bridge domain, VRF. `vlanCktEp` and its `pcTag` are verified on the sandbox |
| `contracts` | `actrlRule`, `actrlEntry` | The zoning rules the leaf enforces (source and destination `pcTag`, filter id, action) plus filter entries. Verified live 2026-11-07 on leaf-101 (rules with `implarp` / `implicit` filters, `deny,log` actions); the sandbox has no user-contract rules on that leaf, so the EPG-name join is not exercised. Tag and filter id fall back to the rule dn. EPG names only for EPGs deployed on that leaf. Rows capped at 20 000 (`too_many_objects`) |

Defaults: `device, software, interfaces`. Optional classes (a spine has no `sviIf`, a fabric without vPC no `vpcDom`) are skipped
only when the APIC answers HTTP 400 with text "unresolved class"; any other error, including another 400, fails the fact. A missing `sys/health` or `sys/ch/health` object (404) leaves that score empty and keeps the other.

**Lessons.** `fabricNode` is the switch node itself: it must be read with `get_node_mo(..., relative_dn="")`
(`/api/mo/topology/pod-1/node-101.json`); the class query returns nothing. Unit fakes cannot catch this, so re-run the live sandbox
check after changing queries. Sandbox switches are simulated (`simsw-` versions, speeds `inherit`, no management IPs).

**Persisted size (per fact).** A step value above `STEP_OUTPUT_VALUE_MAX_BYTES` (64 KB) is stored as a "too large" marker in the run result;
a spine's `interfaces` fact (about 395 rows, 222 KB) hits this. `output_cap` replaces the oversized fact only, so `device` and `software` next to it stay readable. The live context is unaffected, so later steps still read it.

**Mapper (`config-to-attributes`, `source_format: aci_details`).** Maps interfaces (name, status, description, MAC, MTU, IPv4) and
device fields (serial, software version, platform `Cisco ACI`, device type with manufacturer `Cisco`). Not mapped: VLANs and port mode
(ACI VLAN ids are local to one leaf), role, status, location. Interface `type` comes from the kind, else a known speed, else `other`.
`duplex` is never sent (Nautobot accepts it on copper twisted-pair types only, and the APIC speed does not say the media); 100M and 1G ports are typed `other` for the same reason (only `mgmt0` is known copper). The TEP address on `lo0` is dropped unless primary-IP selection picked it. Fields this mapper does not produce (VLANs, mode, SVI addresses) keep the value an earlier step set on the same interface. SVI addresses are not mapped (the anycast gateway is the same on every leaf, so several devices would create one address). The TEP loopback `lo0` is never the primary IPv4 under the default priorities (only via `custom_interface`).

Shared code: `workflow_steps/common/fact_entries.py` and `device_outcomes.py` hold the source-agnostic core that the Catalyst Center
fact modules now wrap.

## Step `get-aci-policy` ("Get Policy from ACI", 2026-11-06)

Fabric policy for each switch. `AciPolicyService.snapshot()` reads once per APIC, with fabric-wide class queries (`/api/class/...`):
`fvAEPg`, `fvRsBd`, `fvRsProv`, `fvRsCons`, `vzBrCP`, `vzSubj`, `vzRsSubjFiltAtt`, `vzEntry` (cap `MAX_POLICY_ROWS` = 50 000 per class,
`too_many_objects` instead of truncation). Each device then gets the EPGs deployed on it (the `epgs` read above) joined with the snapshot.

Also read (verified live 2026-11-07: 3 L3Outs, 2 external EPGs, 4 node and 4 path attachments; the sandbox has one `bgpExtP` and no OSPF / EIGRP, and the one L3Out checked showed no protocols, so protocol attribution to an L3Out is still unconfirmed): `l3extOut`, `l3extRsEctx` (VRF), `l3extInstP` (external EPGs, `pcTag`),
`l3extSubnet` (`ip`, `scope`, `aggregate` flags copied as they are), `l3extRsNodeL3OutAtt` (node, router id), `l3extRsPathL3OutAtt`
(path `tDn` → node(s), interface, `addr`, `ifInstT`, `encap`, `mtu`; a `protpaths-A-B` vPC path puts the L3Out on both nodes) and the
protocol objects `bgpExtP` / `ospfExtP` / `eigrpExtP` under the L3Out. An external EPG takes part in `fvRsProv` / `fvRsCons` like an
application EPG, so contracts' `provider_epgs` / `consumer_epgs` include `uni/tn-…/out-…/instP-…`. A switch gets the L3Outs whose
nodes or interface paths name it (no entry when none), and the contracts of their external EPGs next to those of its deployed EPGs.

Output: `parsed.<key>.l3outs.parsed` (the L3Outs of the switch), `parsed.<key>.epgs.parsed` (EPGs with `provided` / `consumed` as `tenant/name`, class tag, bridge domain) and
`parsed.<key>.contracts.parsed` (the contracts those EPGs use: scope, priority, subjects, filters, entries, and `provider_epgs` /
`consumer_epgs` fabric-wide). Default key `aci_policy`. A relation names its contract or filter without a tenant: it resolves in the EPG's tenant,
then in `common`. If the snapshot fails, every device fails with the APIC error.

**Not covered:** `vzAny`, route-control (route maps, prefix lists), static routes of an L3Out, contract interfaces, taboo contracts, contracts attached to a contract without subjects.
**Verified live 2026-11-07** (sandbox: 33 EPGs, 10 contracts, 13 subjects, 16 entries, 14 provide / 12 consume relations): the snapshot (0.9 s, 17 reads) resolves `common/sql` with its `tcp/1433` and `udp/1434` entries and its provider and consumer EPGs. Real rows: `backend/tests/unit/fixtures/aci_policy_sandbox.json`.

## Step `find-aci-endpoints` ("Find Endpoint in ACI", 2026-11-06)

Where does a device's address live in the fabric? Unlike the other ACI steps it works on devices of **any** source (for example Nautobot):
each device's `address_path` (default `primary_ip4`; an IPv4 or a MAC in any usual spelling) is looked up in the APIC's learned endpoints.
Output: `parsed.<key>.endpoints = {parsed, error}`, `parsed` a list of `{mac, ips, tenant, app_profile, epg | external_epg, encap,
attachments: [{pod_id, node_ids, interface}]}`; a vPC path (`protpaths-A-B`) lists both nodes. Unknown address = empty list, device succeeds;
no value at the path = failure `no_address`; APIC error = failure with the message. Default key `aci_endpoint`.

Reads (`AciEndpointService`, `AciService.query_class_tree`): a MAC is one `fvCEp` query with children (`fvIp`, `fvRsCEpToPathEp`); an IPv4
is first found as `fvIp` (its dn names the endpoint, so secondary addresses work), then those endpoints are read. Addresses are validated
before they reach a filter (`ipaddress`, a MAC regex); endpoint DNs taken from the APIC pass a character allow-list. More than 50 endpoints
for one address fails with `too_many_objects`. `parse_path` (`services/aci/common/paths.py`) is shared with the L3Out reader.

**Verified live 2026-11-07** (7 endpoints, 18 addresses): lookup by MAC and by IPv4 returns tenant, app profile, EPG, encap and the vPC attachment (`protpaths-101-102`). IPv6 addresses are listed on an endpoint but not accepted as a search key. **Not read:** endpoints behind a hypervisor (VMM relations), so they show no attachment.

## Step `compare-aci-subnets` ("Compare ACI Subnets with Nautobot", 2026-11-06)

**Report only**: nothing is written to ACI or Nautobot, and the workflow's devices are not used (`requires: []`; they pass through unchanged).
ACI side (`AciSubnetService`): `fvSubnet` (gateway address with mask under `BD-<name>` or an EPG), `fvRsCtx` (the bridge domain's VRF), `fvRsBd`
(the bridge domain an EPG uses) and `fvBD` (a bridge domain named without a tenant resolves in the same tenant, then `common`). IPv4 and IPv6.
L3Out `extsubnet` objects are not gateway subnets and are not read. Nautobot side (`NautobotPrefixReader`): GraphQL `prefixes(limit, offset)`
paged by 1000, normalised to the network form; GraphQL `errors` or a missing list fail instead of looking like "no prefixes"; above 200 000 prefixes
it fails with `too_many_objects`.

Match = same network in the same namespace; type and status of the Nautobot prefix do not matter. Namespace: one fixed namespace (`namespace`,
default `Global`) or the subnet's VRF name (`namespace_from_vrf`; a subnet whose bridge domain has no VRF is `skipped`; VRFs of different tenants
with the same name share a namespace). Report (JSON artifact, kind `aci_subnet_report`): `matched`; `missing_in_nautobot` with tenant / VRF /
bridge domain / gateway and `covered_by` (the smallest containing Nautobot prefix of that namespace); `missing_in_aci` only when `scope_prefixes`
is set (Nautobot prefixes of type network strictly inside a scope prefix that no ACI subnet matches; containers, pools and the scope itself are
not candidates; a fixed namespace only looks at that namespace); `overlaps` (the same network from more than one bridge domain/EPG in one
namespace); `skipped`; `summary`. The run metadata entry `<node id>.<output_key>` (default `aci_subnet_report`) carries the summary, the first 50 prefixes of
each list and `artifact_ref`. Outcomes: `success` always, `differences` as well when the sources disagree, so a workflow can branch on drift.

**Verified live 2026-11-07:** `fvSubnet` / `fvRsCtx` / `fvRsBd` / `fvBD` (14 subnets, 0.2 s; BD and VRF resolved). **Unverified:** the Nautobot GraphQL `prefixes(limit, offset)` page arguments
(taken from `libs/nautobot_read`, which uses them) were not run against a real Nautobot. Creating the missing prefixes is deliberately not part of this step.

## Step `backup-aci-config` ("Back Up ACI Config to Git", 2026-11-06)

Writes the **configuration** (not the state) of the fabric into a `GitRepository`: one file per tenant, `tenants/<tenant>.json`
(`GET /api/mo/uni/tn-<tenant>.json`) and one for the access policies, `access-policies.json` (`GET /api/mo/uni/infra.json`), inside
`repository_subdirectory` (default `aci`; one fabric per folder). Both reads use `rsp-subtree=full&rsp-prop-include=config-only`. Not backed
up: fabric policies (`uni/fabric`), APIC settings, anything outside `uni/tn-*` and `uni/infra`. The workflow's devices are not used (`requires: []`).

**Stable files.** Two reads of an unchanged fabric must give identical text or every run would be a commit: volatile attributes (`modTs`, `createTs`,
`childAction`, `lcOwn`, `uid`) are removed, the children of every object are sorted (by class, then `rn` / `dn` / `name`, else their JSON), keys are
sorted, 2-space indent, trailing newline. Unchanged files give no commit. The list of volatile attributes is best effort (not checked on the sandbox).

**All or nothing.** Everything is read first (tenants four at a time). If any object cannot be read, for example a tenant larger than the APIC will return
in one answer, the step fails with the list of objects and **writes nothing** and takes no repository lock, so the repository never mixes old and new files.
A tenant name outside `[A-Za-z0-9_.-]{1,64}` is never put in a URL or file name (reported as an error). An unknown name in `tenants` is a configuration error.

**Git.** Same lifecycle as `store-artifact` (destination git): `GitArtifactSink` with `pull_before_write`, the per-repository lease held from prepare to finalize
and always released, commit (`commit`, default on, message with `{source_id}`), push (`push`, default off, needs `commit`). Files of tenants the APIC no
longer has are **reported** as `stale_files` in the metadata (only when all tenants are backed up) and are not deleted. The metadata entry
`<node id>.<output_key>` (default `aci_backup`) lists files, tenants, `committed`, `pushed`, `commit_sha`, `files_changed`. Outcomes: `success` always,
`changed` as well when the commit changed files.

**Review before pushing.** The export holds whatever the APIC returns as configuration; check a repository before it goes to a shared remote. Attributes named `key`, `password`, `authKey`, `community` and the like are replaced by `<secret removed>` when the APIC returns a value (the sandbox returns them empty). A tenant name with `..` or an edge dot is refused (the git sink would rewrite it and two tenants could share a file). A failure after the first write restores the files the step touched (`GitArtifactSink.discard_written`), so the next pull is not blocked; the stale-file listing refuses a symlinked folder (`list_files_in_repo_dir`).
**Verified live 2026-11-07:** 13 tenant files plus `access-policies.json` (14 files, 1.5 MB), no errors, and two consecutive exports are byte-identical (so a second run makes no commit). **Unverified:** the push to a real git remote.
