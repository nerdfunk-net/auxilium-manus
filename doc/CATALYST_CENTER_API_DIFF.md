# Catalyst Center API diff: 2.3.3.x vs 2.3.7.x (in-scope endpoints)

Phase 0 research for the Catalyst Center source (device inventory + command runner / config).

## How this was derived (read the limits first)

| Item | Detail |
|------|--------|
| Old side | `dnacentersdk` branch `develop_2.3.3.0` (module `v2_3_3_0`) - **2.3.3.0, not 2.3.3.6** |
| New side | `dnacentersdk` branch `develop_2.3.7.6` (module `v2_3_7_6`) - **2.3.7.6, not 2.3.7.9** |
| Extraction | Regex over `e_url` / HTTP verb / query-param dicts in `devices`, `command_runner`, `task`, `file`, `configuration_archive` |
| Cross-check | DevNet pages for 2.3.7.9 (device list, command runner) |

Limits:
- The Cisco-published `catalyst-center-api-specs` repo only contains Assurance specs, and DevNet
  does not appear to host 2.3.3.x pages, so the exact releases could not be diffed directly.
  The SDK is Cisco-maintained and generated per release, so it is a good proxy for **paths, verbs
  and query parameters**; patch releases (3.0->3.6, 7.6->7.9) are assumed not to remove endpoints.
- The SDK has request validators only. **Response body shapes were NOT diffed** and remain unverified.
- Not yet verified against a live controller.

## Version alignment matrix (supplied by the project owner)

| Catalyst Center version | REST API / DevNet docs version | Python SDK (`catalystcentersdk`) |
|---|---|---|
| 3.1.6 | API 3.1.6 | 3.1.6.x |
| 3.1.3 | API 3.1.3 | 3.1.3.0.x |
| 2.3.7.9 | API 2.3.7.9 | 2.3.7.9.x |
| 2.3.7.6 | API 2.3.7.6 | 2.3.7.6.x |
| 2.3.7.5 | API 2.3.7.5 | compatible with 2.3.7.x SDKs |
| 2.3.7.4 | API 2.3.7.4 | compatible with 2.3.7.x SDKs |

Notes:
- The matrix has **no 2.3.3.x row**. The 2.3.3.x comparison below therefore rests on the older
  `dnacentersdk` 2.3.3.0 branch and has no matching published `catalystcentersdk` or DevNet page.
- It also has no 3.2.x / 3.3.x row. PyPI has `catalystcentersdk` 3.2.3.0.x (diffed below);
  3.3.1 has no SDK yet.
- Used here as a **research source only**. The backend does not depend on the SDK (see next section).

## Why the backend uses httpx, not the Python SDK

- `catalystcentersdk` / `dnacentersdk` are synchronous (`requests` + `requests-toolbelt`); the
  backend is async FastAPI plus Hatchet workers, so SDK calls would block the event loop or need
  thread offloading.
- The backend needs controls the SDK does not provide: the SSRF guard
  (`validate_outbound_http_url_async`), per-source TLS verify/no-verify pools, vault-resolved
  credentials per request, typed errors that never leak response bodies, and pooled app-scoped clients.
- We use ~10 endpoints; the SDK carries 1,100+ operations (about 1,130 in 2.3.7.9, about 1,960 in 3.2.3) plus its own session and schema layer,
  with a version-bound module per release.
- It stays useful as an offline reference for endpoint paths and parameters.

## Findings

**In-scope endpoints are essentially identical across both versions.** Every 2.3.3.0 endpoint in
these modules still exists in 2.3.7.6 with the same verb; nothing was removed or renamed.

| Capability | Endpoint | 2.3.3.x | 2.3.7.x | Notes |
|---|---|---|---|---|
| Auth | `POST /dna/system/api/v1/auth/token` | yes | yes | Basic auth -> `X-Auth-Token` |
| Release detect | `GET /dna/intent/api/v1/dnac-release` | yes | yes | in `platform_configuration` (old) / `platform` (new) |
| Device list | `GET /dna/intent/api/v1/network-device` | yes | yes | identical query params; `offset` >= 1 (1-based), `limit` 1-500 |
| Device by id | `GET /dna/intent/api/v1/network-device/{id}` | yes | yes | |
| Device by IP | `GET /dna/intent/api/v1/network-device/ip-address/{ipAddress}` | yes | yes | |
| Device count | `GET /dna/intent/api/v1/network-device/count` | yes | yes | **new in 2.3.7.x: accepts `hostname`, `locationName`, `macAddress`, `managementIpAddress` filters** (2.3.3.x: unfiltered total only) |
| Command runner | `POST /dna/intent/api/v1/network-device-poller/cli/read-request` | yes | yes | body: `commands`, `deviceUuids`, `timeout`, `name`, `description` |
| Allowed commands | `GET .../network-device-poller/cli/legit-reads` | yes | yes | |
| Task status | `GET /dna/intent/api/v1/task/{taskId}` | yes | yes | |
| New task API | `GET /dna/intent/api/v1/tasks/{id}` (+ list/count/detail) | **no** | yes | additive; legacy `/task` still present in 2.3.7.x |
| File fetch | `GET /dna/intent/api/v1/file/{fileId}` | yes | yes | command-runner results retrieved via task -> `fileId` |
| Config (running) | `GET /dna/intent/api/v1/network-device/{networkDeviceId}/config` family: `network-device/config`, `.../config/count` | yes | yes | |
| Config archive | `GET /dna/intent/api/v1/network-device-config` | **no** | yes | additive |

2.3.7.x additions with no 2.3.3.x equivalent (all out of scope, listed for awareness): the
`/dna/data/api/v1/networkDevices`, `/interfaces`, `/assuranceEvents` families, health score
definitions, user-defined fields, resync-interval settings, management-address update.

Deprecation: only one deprecation marker found in the in-scope modules (new side). DevNet 2.3.7.9
marks the `location` / `locationName` **response fields** of the device list as deprecated.

## Design consequence

The version surface for v1 is a **thin capability layer, not two full adapters**:
1. Shared code path for auth, device list/get, pagination, command runner, file fetch.
2. Version-gated only where needed: filtered `count`, and preferring `/tasks/{id}` over `/task/{taskId}`
   (optional; legacy `/task/{taskId}` works on both so it can be used everywhere).
3. Normalization layer still isolates workflow steps from raw payloads, so future version drift
   (and out-of-scope features such as sites) can be added without touching steps.

## 2.3.7.9 -> 3.1.6 / 3.2.3 (added later)

Source: `catalystcentersdk` 2.3.7.9.5 (module `v2_3_7_9`) vs 3.1.6.0.7 (`v3_1_6_0`) vs 3.2.3.0.3 (`v3_2_3_0`).
This SDK matches the exact 2.3.7.9 release. **3.3.1 is not covered** (newest SDK on PyPI is 3.2.3).

Result for the same endpoint families (`/network-device*`, `/task*`, `/tasks*`, `/file*`, `dnac-release`):
- 66 in-scope operations in 2.3.7.9; **all 66 exist in 3.1.6 and 3.2.3** (same verb + path). Nothing removed, nothing added.
- Every endpoint the v1 source uses is unchanged: auth token, `dnac-release`, device list/get/count/by-IP,
  `network-device/{id}/config`, command-runner `read-request` + `legit-reads`, `/task/{taskId}`, `/tasks/{id}`, `/file/{fileId}`.
- Signature differences exist on 7-8 operations, none used by v1 (functional-capability, tenantinfo,
  user-defined-field list, equipment, poe-detail, delete device `clean_config`, vlan; 3.2.3 adds
  `restricted_access`/`to_encrypt` to file upload). Treat as parser-sensitive and unverified.
- Caveat: a first run of the diff reported 60 "removed" endpoints; that was a parser artifact
  (the 3.x SDK uses a different code style), caught because the counts did not add up. The corrected
  extractor compares normalized full URLs.

Conclusion: 2.3.3.x, 2.3.7.x and 3.1/3.2 share one endpoint set for our scope. Response bodies and
3.3.1 remain unverified.

## Live verification: DevNet sandbox (2026-10-03)

Run against `https://sandboxdnac2.cisco.com` with the real `services/catalyst_center` code
(read-only calls only). Confirmed working end to end:
`auth/token`, `dnac-release`, `network-device` (list + `count` + `{id}` + `ip-address/{ip}`),
`network-device/{id}/config` (returns a text body), and the command runner
(`read-request` -> `task/{id}` with `progress` carrying `{"fileId": ...}` -> `file/{fileId}`).
The sandbox has 4 virtual IOS-XE switches. Device payload fields matched the parser as written.

Findings that changed the code:
- **`dnac-release` does not report a product release here.** `installedVersion` was `3.722.75335`
  (a platform build; `systemVersion` `2.7.72`, packages `2.722.x`). The earlier parser accepted it as
  release 3.722.75335. Now rejected as implausible (component > 99); an unknown release means "no optional
  capabilities" (filtered device count falls back to listing, which works everywhere). The controller-reported
  string is shown in test-connection as "reported version". We could not confirm from the API whether this
  sandbox is 2.3.7.x.
- **TLS verification fails against the sandbox** (self-signed); it works with `verify_ssl=false`.
  The source dialog's "Verify TLS certificate" toggle covers this.
- **Command output is raw terminal text**: it includes the echoed command and the trailing prompt
  (e.g. `show clock\n*15:22:13.553 UTC ...\nsw1#`). Steps that parse output should strip those.
- The filtered `network-device/count` was not exercised (release unknown -> fallback path used).

## Device-list filter semantics (verified live, 2026-10-03)

`GET /dna/intent/api/v1/network-device` on the DevNet sandbox. These shape the
`get-catalyst-center-devices` step (`services/catalyst_center/device_filters.py`):

- Filters: `hostname`, `managementIpAddress`, `macAddress`, `serialNumber`, `platformId`, `family`, `series`, `type`,
  `role`, `softwareType`, `softwareVersion`, `reachabilityStatus`, `collectionStatus`, `id` (comma list),
  `offset` (1-based) / `limit` (<= 500). Different filters combine with AND.
- **Case-sensitive, full-string match** (`sw` finds nothing, `sw.*` finds `sw1`..`sw4`, `SW1` does not match `sw1`).
- **`.*` is the only wildcard.** `.` (single char), `|`, `[..]`, `\d`, `?`, `+`, `^`, `$`, `(?i)` all match nothing;
  a `.` is literal (`10.10.20.17.*` works because the first dot is a literal dot).
- **A repeated query parameter is OR** (`hostname=sw1&hostname=sw2`); comma lists only work for `id`.
  Multiple filter kinds with lists combine as AND-of-ORs (confirmed: hostnames [sw1, sw2] AND roles [ACCESS, CORE] -> 2,
  AND roles [CORE] -> 0).
- **No CIDR filter.** The step prefilters on the whole octets shared by the CIDR's first/last address
  (`10.10.20.0/24` -> `10.10.20..*`; a /32 -> the exact IP) and checks exact membership client-side.
- **No usable site filter**: `location` / `locationName` are deprecated and were empty for every sandbox device; the
  sandbox has only the `Global` site. A site filter would need the site-membership endpoints (not built).
- `GET /network-device/count` honoured `hostname`, `managementIpAddress` and also `role` on this controller.

## Open items
- Response bodies on 2.3.3.x (no sandbox for it) and on 3.3.1.
- Whether the filtered `count` endpoint behaves as the SDK suggests on a controller that reports a product release.
- Command-runner limits (commands/devices per request) - not stated in the docs.
- Token lifetime and expiry behaviour (401 retry is implemented; lifetime assumed 60 min, refreshed at 50).

## Earlier open items (superseded above)
- Response body shapes for device list and task/file results on 2.3.3.6 vs 2.3.7.9.
- Whether `location` / `locationName` are still populated on 2.3.7.9.
- Exact token lifetime and behavior of `X-Auth-Token` expiry (401 vs other).
- Command-runner limits (commands/devices per request) - not stated on the 2.3.7.9 page.
