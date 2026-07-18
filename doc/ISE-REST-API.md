# Cisco ISE REST API Integration

Backend integration with Cisco Identity Services Engine (ISE) via its ERS
(External RESTful Services) API. Lets the manus backend manage ISE
**network devices** (RADIUS/TACACS clients) and **network device groups**
(Location, Device Type, and arbitrary custom group categories).

This document is the authoritative reference for the integration — it
captures several ISE-specific behaviors that were only discovered by
live-probing a Cisco DevNet ISE sandbox (self-signed cert, no persistent
test environment). **The sandbox used during development has since been
torn down**, so treat this document, the unit tests, and the scripts under
`backend/scripts/ise_test*.py` as the record of verified behavior — there
is currently no live ISE instance to re-verify against.

## Contents

- [File map](#file-map)
- [Concepts](#concepts)
- [Configuring a source](#configuring-a-source)
- [Network device endpoints](#network-device-endpoints)
- [Network device group endpoints](#network-device-group-endpoints)
- [Error handling](#error-handling)
- [Permissions](#permissions)
- [Calling this from a workflow step](#calling-this-from-a-workflow-step)
- [ISE quirks discovered during development](#ise-quirks-discovered-during-development)
- [Manual test scripts](#manual-test-scripts)

## File map

```
backend/services/ise/
├── credentials.py                  # ISECredentials dataclass (base_url, username, password, verify_ssl, timeout)
├── client.py                       # ISEService — low-level ERS HTTP client
├── common/exceptions.py            # ISEError, ISEValidationError, ISEAPIError, ISENotFoundError
├── network_device_service.py       # ISENetworkDeviceService — device CRUD
├── network_device_group_service.py # ISENetworkDeviceGroupService — group CRUD
└── source_config_service.py        # ISESourceConfigService — named source config (settings + encrypted credential)

backend/models/ise.py               # All Pydantic request/response models
backend/routers/sources/ise/
├── crud.py                         # /sources/ise — source configuration CRUD
└── ops.py                          # /sources/ise/{source_id}/... — devices, groups, test-connection

backend/service_factory.py          # get/set_ise_app_service, build_ise_network_device_service,
                                     # build_ise_network_device_group_service, build_ise_source_config_service
backend/dependencies.py             # get_ise_source_config_service (FastAPI dependency)
backend/main.py                     # ISEService lifespan startup/shutdown, router registration

backend/scripts/ise_test*.py        # Executable, live-verified usage examples (see below)
backend/tests/test_ise_*.py         # Unit tests (all mocked — no network access)
```

## Concepts

**Source** — a named ISE connection (`source_id`, e.g. `"lab-ise"`). Config
lives in the generic `settings` table under `sources.ise.<source_id>`
(non-secret: `url`, `verify_ssl`, `timeout`, plus a `credential_id`
pointer). The password lives Fernet-encrypted in the `credentials` table
(`source="ise"`, `type="generic"`), via the existing
`CredentialsService`/`EncryptionService` — unlike the Nautobot integration,
the ISE password is **never** stored in plaintext. Multiple sources can
coexist (e.g. `lab-ise`, `prod-ise`).

**Credentials resolution** — every device/group endpoint takes `source_id`
in the URL and resolves `ISECredentials` server-side
(`ISESourceConfigService.resolve_credentials`) — callers never pass ISE
username/password per request. This differs from the Nautobot integration,
where the caller supplies `nautobot_url`/`nautobot_token` in the request
body; it matches how a workflow step will want to use it (reference a
`source_id`, not carry a live credential).

**Transport** — `ISEService` (`services/ise/client.py`) is an app-scoped
client holding two pooled `httpx.AsyncClient`s (one `verify=True`, one
`verify=False`), because `verify_ssl` is a per-source setting and ISE
sandboxes commonly use self-signed certificates. All ERS calls go through
`ers_request(endpoint, credentials, method, data, params)`, which builds
`{base_url}/ers/config/{endpoint}`, sends HTTP Basic auth, and maps
ISE's HTTP status codes to typed exceptions (see
[Error handling](#error-handling)).

## Configuring a source

```
POST   /api/sources/ise                  create a source
GET    /api/sources/ise                  list sources (no secrets)
GET    /api/sources/ise/{source_id}      get one source (no secrets)
PUT    /api/sources/ise/{source_id}      update a source (blank/omitted password keeps the existing one)
DELETE /api/sources/ise/{source_id}      delete a source (also deletes its paired credential)
```

```bash
curl -X POST /api/sources/ise -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{
  "source_id": "lab-ise",
  "url": "https://10.10.20.77",
  "username": "admin",
  "password": "C1sco12345!",
  "verify_ssl": false,
  "timeout": 30
}'
# -> 201 {"source_id": "lab-ise", "url": "https://10.10.20.77", "verify_ssl": false, "timeout": 30}
# (password is never echoed back by any endpoint)
```

`source_id` must match `^[a-z][a-z0-9_-]{0,63}$` (same pattern as
Nautobot/Git source IDs, `services/settings/source_keys.py`). Requires
`sources.ise:write` for create/update, `sources.ise:delete` for delete,
`sources.ise:read` for get/list.

## Network device endpoints

All under `/api/sources/ise/{source_id}/...`:

```
GET    /devices                    list, with pagination + ISE-native filter
GET    /devices/name/{name}        get by device name
GET    /devices/ndg/{group_name}   list devices belonging to a network device group
GET    /devices/{device_id}        get by ISE-assigned UUID
POST   /devices                    create
PUT    /devices/{device_id}        update (merge-safe, see below)
DELETE /devices/{device_id}        delete
POST   /test-connection            connectivity check (GET networkdevice?size=1)
```

### List + filter

```
GET /devices?page=1&size=20&filter=ipaddress.EQ.192.168.1.1
```

`filter` is passed through **verbatim** to ISE's own filter query syntax —
`{field}.{operator}.{value}`. It is not validated or interpreted on our
side; ISE returns `400` with a clear message if the field is unsupported
(confirmed live: `ip` and `NDG` are rejected, `ipaddress` and `location`
work).

| Filter                                              | Matches                                                  | Status |
|------------------------------------------------------|-----------------------------------------------------------|--------|
| `filter=ipaddress.EQ.192.168.1.1`                     | Device whose `NetworkDeviceIPList` contains that IP       | confirmed live |
| `filter=location.EQ.Location#All Locations`           | Device's location group — **must be the full hierarchical group name**, not just the display name (`All Locations` alone returns 0 results) | confirmed live |
| `filter=location.CONTAINS.Building1`                  | Substring match on the hierarchical location name          | confirmed live (tested as `CONTAINS.All`) |
| `filter=name.CONTAINS.router`                         | Device name substring match                                | not independently tested this session — `name` is the primary ERS field and highly likely to work by analogy with the others, but treat as unverified until confirmed against a live instance |

Operators observed: `EQ`, `CONTAINS`. Remember to percent-encode `#` and
spaces in the raw ISE filter value if constructing the query string by
hand (`httpx`'s `params=` dict does this automatically; a browser/`curl -G
--data-urlencode` does too).

### List devices by network device group

```
GET /devices/ndg/{group_name}?page=1&size=20
```

`{group_name}` is the full hierarchical NDG name, percent-encoded (e.g.
`/devices/ndg/myGroup%23myGroup%23my-test-001`). Internally this calls
`ISENetworkDeviceService.list_devices_by_group`, which reuses the list
endpoint with `filter=location.EQ.{group_name}` — see quirk 8 below for why
the `location` field name is misleading here. Response shape is identical
to `GET /devices`. Confirmed live: a device with
`NetworkDeviceGroupList` containing `myGroup#myGroup#my-test-001` (a
custom, non-Location category) was correctly returned by this endpoint; an
unrelated/nonexistent group name returns `{"total": 0, "resources": []}`,
not an error.

### Create

```json
POST /devices
{
  "name": "test-001",
  "description": "testdevice",
  "profileName": "Cisco",
  "NetworkDeviceIPList": [{"ipaddress": "10.10.10.1", "mask": 32}],
  "NetworkDeviceGroupList": [
    "Location#All Locations",
    "IPSEC#Is IPSEC Device#No",
    "Device Type#All Device Types"
  ],
  "tacacsSettings": {"sharedSecret": "tacacskey12345", "connectModeOptions": "OFF"},
  "authenticationSettings": {"networkProtocol": "RADIUS", "radiusSharedSecret": "..."}
}
```

Response is `201` with an **empty body** — ISE returns the new device's id
only via the `Location` response header (`.../networkdevice/{uuid}`). The
backend parses that header and returns `{"id": "<uuid>", "location": "<url>"}`.

`ISENetworkDeviceCreate` (`models/ise.py`) declares `name`,
`NetworkDeviceIPList`, `NetworkDeviceGroupList`,
`authenticationSettings`/`snmpsettings`/`tacacsSettings` as typed/loosely-typed
fields but allows extra keys (`ConfigDict(extra="allow")`) — ISE's full
`NetworkDevice` schema is large (SNMP, TrustSec, etc.) and not worth
fully modeling; unrecognized fields pass through untouched.

`NetworkDeviceGroupList` entries must be **full hierarchical group
names** exactly as ISE stores them (see
[Network device group endpoints](#network-device-group-endpoints)) — not
just the display name. Built-in defaults on a fresh ISE install:
`"Location#All Locations"`, `"Device Type#All Device Types"`,
`"IPSEC#Is IPSEC Device#No"` (or `#Yes`).

### Update — merge-safe

```
PUT /devices/{device_id}
{"description": "new description"}
```

**Critical ISE behavior**: a raw ISE `PUT` on `networkdevice` *replaces the
whole representation* — any top-level field omitted from the request body
is **cleared**, not left alone. Confirmed live: sending only
`{"description": ...}` directly to ISE silently wiped the device's
`authenticationSettings` (deleted the RADIUS secret) in the same request.

`ISENetworkDeviceService.update_device` (`network_device_service.py`)
works around this: it fetches the current device, shallow-merges the
caller's fields over it, strips the `link` field, and `PUT`s the merged
result. **Callers of our `PUT /devices/{id}` endpoint get normal partial-update
semantics** — send only the fields you want to change. This is handled
entirely server-side; do not try to "help" by resending the whole device.

### Delete

```
DELETE /devices/{device_id}   -> 204
```

Note: a raw `DELETE` to ISE without an `Accept: application/json` header
returns `415 Illegal Request Header`. Our client always sends
`Accept`/`Content-Type: application/json`, so this only matters if you are
calling ISE directly outside the backend.

## Network device group endpoints

ISE's `NetworkDeviceGroup` resource has **no separate parent-id field** —
hierarchy is encoded entirely inside the `name` string as a
`#`-delimited path, whose **first segment is the group's category**
(`othername` must equal that first segment):

```
Location#All Locations                    <- built-in root of the "Location" category
Location#All Locations#Building1          <- child of the root
Location#All Locations#Building1#Floor1   <- grandchild
nautobot#nautobot                         <- a custom root category (the leaf equals the category name)
nautobot#nautobot#location-001            <- child of that custom root
```

A brand-new category's own root member needs **at least two `#`-delimited
segments** (confirmed live: `name="new-root"` alone is rejected with
`"The name should have at least type(othername) and name, delimited by
pound sign"`) — the convention this codebase follows, matching what was
already present in the sandbox, is to name the root member identically to
the category: `name = f"{category}#{category}"`.

Endpoints, all under `/api/sources/ise/{source_id}/...`:

```
GET    /network-device-groups/                   list, with pagination + ISE-native filter
POST   /location-groups                         create a child of an existing Location group (convenience)
POST   /network-device-groups/roots              create a brand-new category (root group)
POST   /network-device-groups/children            create a child under ANY existing group
GET    /network-device-groups/name/{name}         get by full hierarchical name
PUT    /network-device-groups/{group_id}          update description (merge-safe)
DELETE /network-device-groups/{group_id}          delete
```

### `GET /network-device-groups/` — list

```
GET /network-device-groups/?page=1&size=20&filter=name.CONTAINS.Location
```

Same shape and semantics as [`GET /devices`](#list--filter): `page`/`size`
pagination and a verbatim ISE `filter` query param, response is
`{total, resources, next_page}` built from ISE's `SearchResult`. Confirmed
live against the DevNet sandbox (returned the 5 built-in groups: `Device
Type#All Device Types`, `IPSEC#Is IPSEC Device`, `IPSEC#Is IPSEC
Device#No`, `IPSEC#Is IPSEC Device#Yes`, `Location#All Locations`).

### `POST /location-groups` — Location-specific convenience

```json
{"name": "Building1", "description": "HQ building", "parent_group": "All Locations"}
```

`parent_group` is the **short** name — the `Location#` root prefix is
added automatically. Supports nesting: for a grandchild, pass
`"parent_group": "All Locations#Building1"`. Response:
`{"id": ..., "name": "Location#All Locations#Building1", "description": ..., "parent_group": "All Locations"}`.
Returns `400 Parent location '...' not found` if the parent doesn't exist
(the service looks the parent up before creating — see
[quirks](#ise-quirks-discovered-during-development) for why this matters).

### `POST /network-device-groups/roots` — new category

```json
{"name": "new-root", "description": "a new root group"}
```

Creates the category's root member: stored as `name="new-root#new-root"`,
`othername="new-root"`. Response includes the resolved `name`/`othername`.

### `POST /network-device-groups/children` — generic child, any category

```json
{"name": "location-001", "description": "...", "parent_group": "new-root#new-root"}
```

`parent_group` here must be the **full existing ISE name** (unlike
`/location-groups`, no prefix is assumed — this endpoint works for any
category, so it can't guess one). The child inherits the parent's
`othername` automatically (looked up server-side). Also works for Location
groups if you'd rather pass the full name yourself:
`"parent_group": "Location#All Locations"`.

### `GET /network-device-groups/name/{name}`

`{name}` is the full hierarchical name, e.g.
`/network-device-groups/name/Location%23All%20Locations` — percent-encode
`#` and spaces (a literal `#` in a URL starts a fragment and is never sent
to the server, so it must be encoded client-side). `404` if not found.

### `PUT /network-device-groups/{group_id}` — description only, merge-safe

```json
{"description": "new description"}
```

Same ISE gotcha as devices: a raw `PUT` on `networkdevicegroup` requires
`name` and `othername` in the body and **rejects the request entirely**
(`400 Mandatory fields missing: [name, othername]`) if you send
description-only. `ISENetworkDeviceGroupService.update_group` fetches the
current group, merges in the new description, and resends the full
`{name, othername, description}` triplet. The public endpoint only takes
`description` — the group's `name`/`othername` cannot be changed via this
API (renaming would require delete+recreate, which is out of scope here).

### `DELETE /network-device-groups/{group_id}`

`204` on success. **Delete children before parents** — ISE does not
cascade-delete, and deleting a group that still has children will fail (not
independently re-verified after the sandbox teardown, but standard ISE ERS
behavior; the `ise_test_ndg_delete.py` script always deletes leaf groups
first).

## Error handling

All ISE routers follow the same mapping (see
`core/safe_http_errors.py::raise_internal_server_error`):

| Condition                                             | HTTP status | Notes |
|---------------------------------------------------------|:-----------:|-------|
| Source/device/group not found                          | 404         | `ISESourceNotFoundError`, `ISENotFoundError` |
| Bad input / ISE validation error / duplicate name       | 400         | `ISEValidationError` — includes ISE's own error message text (safe to expose; contains no secrets) |
| ISE unreachable, timeout, or unexpected ISE-side error  | 502         | `ISEAPIError` — sanitized `{message, error_id}`, detail logged server-side only |
| Anything else unexpected                                | 500         | sanitized `{message, error_id}` |

`test_ise_client.py::test_error_message_never_contains_password` locks in
that ISE error text never leaks the configured password.

## Permissions

All ISE endpoints require RBAC permission on resource `sources.ise`
(`services/auth/rbac_seed.py`):

| Action   | Applies to |
|----------|------------|
| `read`   | GET everything (also the router-level dependency — every ISE route requires at least `read`) |
| `write`  | POST/PUT source config, devices, and groups |
| `delete` | DELETE source config, devices, and groups |

## Calling this from a workflow step

Workflow step executors run in-process — call the service layer directly,
**never** the HTTP endpoints (same rule as every other integration; see
`doc/WORKFLOW-STEPS.md`). Do not import `routers.sources.ise` from a step.

```python
# backend/workflow_steps/my_ise_step/executor.py
import service_factory
from core.database import SessionLocal

async def execute(*, config, context, run, artifact_service, node_id) -> list[StepOutcome]:
    source_id = config["ise_source_id"]

    with SessionLocal() as db:
        source_config_service = service_factory.build_ise_source_config_service(db)
        credentials = source_config_service.resolve_credentials(source_id)

    device_service = service_factory.build_ise_network_device_service(credentials)
    result = await device_service.list_devices(filter_=f"ipaddress.EQ.{ip}")
    ...
```

Key points:
- `resolve_credentials` needs a DB session (it reads the settings row and
  decrypts the paired credential) — open one with `SessionLocal()`, resolve,
  and close it before the (potentially slow) ISE call, same pattern as
  other DB-then-external-API steps.
- `service_factory.get_ise_app_service()` (the shared pooled `httpx`
  client) is only initialized during the FastAPI app lifespan
  (`main.py`), which is active for the whole worker process — safe to call
  from workflow steps running in the same process.
- Use `ISENetworkDeviceGroupService` the same way via
  `service_factory.build_ise_network_device_group_service(credentials)`
  for group operations.
- Raise `ValueError` for config errors (missing `ise_source_id`, etc.),
  `RuntimeError` for unexpected execution failures — the `StepRunner`
  catches both per the standard executor contract. `ISEValidationError`,
  `ISENotFoundError`, and `ISEAPIError` from the service layer are not
  `ValueError`/`RuntimeError` subclasses; catch and re-raise/wrap them
  explicitly if you want step-level failures to carry a clean message.

## ISE quirks discovered during development

Collected here because none of this is documented by Cisco in an
easily-fetchable form (the DevNet docs pages are JS-rendered SPAs) — all
verified by direct HTTP probing of the sandbox before it was decommissioned.

1. **`PUT` replaces the whole representation** for both `networkdevice`
   and `networkdevicegroup` — omitted top-level fields are wiped or the
   request is rejected outright (`networkdevicegroup` requires
   `name`/`othername` present; `networkdevice` silently clears
   `authenticationSettings`/`description` if omitted). Both our services
   handle this with read-merge-write; if you add new ISE resource types,
   assume this is universal ERS behavior unless you verify otherwise.
2. **Group hierarchy is a `#`-delimited string, not a parent-id field.**
   `othername` must equal the first segment. A new category's root member
   needs ≥2 segments (`"foo"` alone is rejected; `"foo#foo"` works).
3. **Creating a group under a nonexistent parent returns ISE `500`**
   (`"Failed to create Network Device Group. Please check the log for
   error."`), not `400`. Both group-creation service methods look the
   parent up first and raise a clean `ISEValidationError` → `400` instead
   of forwarding ISE's opaque 500.
4. **`DELETE` without `Accept: application/json` returns `415`.** Always
   set the header (our client always does).
5. **`POST`/create responses are `201` with an empty body** — the new
   resource's id is only in the `Location` response header. Both
   `create_device` and the group-creation methods parse it from there
   (`ISEService._id_from_location`).
6. **`filter=location.EQ.<value>` needs the full hierarchical name**
   (`Location#All Locations`), not the display name (`All Locations`
   alone silently matches zero devices — no error, which makes this easy
   to misdiagnose as "the device isn't tagged" when it's actually a
   filter-syntax mistake).
7. Basic auth over HTTPS with `Accept`/`Content-Type: application/json`
   headers is the only auth ERS supports (no OAuth/token flow) — see
   `services/ise/client.py::ers_request`.
8. **The `networkdevice` list filter field `location` is not actually
   scoped to the `Location` category** — confirmed live, filtering by
   `location.EQ.<full NDG name>` matches against *any* entry in a
   device's `NetworkDeviceGroupList`, regardless of category. A custom
   group (`myGroup#myGroup#my-test-001`) and non-Location built-ins
   (`Device Type#All Device Types`, `IPSEC#Is IPSEC Device#No`) all
   correctly filtered the device set exactly like a real
   `Location#...` group would, while an unrelated/nonexistent group
   name returned zero results (no error). `filter=NDG.EQ....` itself is
   rejected as an unsupported field (see the filter table above) — this
   `location` behavior is the only working way to filter devices by
   arbitrary group membership, and is what
   `GET /devices/ndg/{group_name}` (`ISENetworkDeviceService.list_devices_by_group`)
   relies on.

## Manual test scripts

`backend/scripts/ise_test*.py` are executable, self-contained examples
that exercise every endpoint above through the real HTTP API (not just the
service layer) — read them as worked examples if this document is ever
unclear. They require a running backend and were **last verified against
a live sandbox that no longer exists**; they will need a fresh ISE
instance (edit `--ise-url`/`--ise-username`/`--ise-password`, or update the
defaults) to run again.

| Script                          | Demonstrates |
|----------------------------------|--------------|
| `ise_test.py`                    | Source create/update, `test-connection`, device create-or-update with TACACS key |
| `ise_test_devices_by_ndg.py`     | List devices by network device group (`GET /devices/ndg/{group_name}`), including a non-Location custom group |
| `ise_test_update_tacacs.py`      | Device `PUT` merge-safety (TACACS-only update, other fields untouched) |
| `ise_test_delete_device.py`      | Device delete + verify-gone |
| `ise_test_ndg_add.py`            | Location child, new root category, child of new root |
| `ise_test_ndg_list.py`           | Group list, pagination (`--all`), ISE-native `filter` passthrough |
| `ise_test_ndg_update.py`         | Group `PUT` merge-safety (description-only update) |
| `ise_test_ndg_delete.py`         | Group delete, children-before-parents, verify-gone |

Unit tests (`backend/tests/test_ise_*.py`) are fully mocked (`AsyncMock`
around `ISEService.ers_request`) and do **not** require any ISE instance,
sandbox or otherwise — they will keep passing regardless of sandbox
availability and are the safety net for any future changes to this
integration.
