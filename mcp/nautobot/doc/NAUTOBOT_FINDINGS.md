# Nautobot findings (verified live)

Verified 2026-10-27 against the dev instance `http://127.0.0.1:8080`
(Nautobot **3.2.7**, Django 5.2). Re-verify if the target version changes.

## Access

- `admin`/`admin` over HTTP Basic is **rejected** (`Authentication credentials were not
  provided`). Nautobot's REST and GraphQL APIs want a token.
- A Django **session login** works for read-only probing: GET `/login/`, then POST the form
  with `csrfmiddlewaretoken`, then send the session cookie (GraphQL POST also needs
  `X-CSRFToken` and a `Referer`). Probing only; the server itself uses a token.
- REST docs: `/api/docs/`. GraphQL endpoint: `/api/graphql/`.
- Use plain list endpoints; `?brief=1` returned no `results` key here.

## Test data

- Location types: Country, State, City, Building, Room (none nestable).
- 14 locations in a tree: `Country A → State A → City A → Building A → Room A` (plus B and C
  branches). `location_type` is a nested object on each location.
- 2 devices (role `Network`, location `City A`, status `Active`): `LAB.local.zz`, `device-1`.
- 228 IP addresses, 5 prefixes, 3 tags, 2 device types, 2 platforms.
- **Role names mix content types.** The unscoped list has 23 roles (Anycast, HSRP, Server,
  lab, ...); only `Network`, `Server`, `lab` apply to `dcim.device`. Use
  `extras/roles/?content_types=dcim.device` (REST) or `roles(content_types: "dcim.device")`
  (GraphQL).
- There is no role called "router". This is why vocabulary discovery matters.

## Filter behavior

| Check | Result |
|-------|--------|
| `devices?location=Country A` | 2 devices — **includes descendants** (devices sit in City A) |
| `devices?location=City A` | 2 |
| `devices?role=Network` | 2; `role=lab` 0 — role filters by name |
| `devices?location_type=...` | **Unknown filter field** on devices. To filter devices by location type, list the locations of that type first |
| `locations?location_type=Country` | 3 |
| `locations?name__ic=country` | 3 (case-insensitive contains) |
| `locations?parent=Country A` | 1 (direct children only) |

## GraphQL

Root fields and their filter args (selection; the full lists are long, 57–314 args):

- `devices`: `name`, `name__ic`, `location`, `role`, `status`, `tags`, `tenant`,
  `device_type`, `platform`, `q`, `limit`, `offset`
- `locations`: `name`, `name__ic`, `location_type`, `parent`, `status`, `tags`, `tenant`, `q`,
  `limit`, `offset`
- `location_types`: `name`, `parent`, `content_types`, `q`, `limit`, `offset`
- `ip_addresses`: `address`, `parent`, `prefix`, `namespace`, `role`, `status`, `tags`,
  `tenant`, `q`, `limit`, `offset`
- `prefixes`: `prefix`, `parent`, `namespace`, `location`, `locations`, `role`, `status`,
  `tags`, `tenant`, `q`, `limit`, `offset`
- `roles`, `statuses`, `tags`: `name`, `name__ic`, `content_types`, `q`, `limit`, `offset`

Notes:
- Pagination is `limit`/`offset` only. **No total count** in GraphQL.
- Verified query shapes:
  ```graphql
  { devices(location: "Country A") { name role{name} status{name}
      location{name location_type{name}} } }
  { locations(name__ic: "country") { name location_type{name} parent{name} children{name} } }
  { ip_addresses(limit: 2) { address dns_name status{name} parent{prefix}
      interfaces{name device{name}} } }
  { roles(content_types: "dcim.device") { name } }
  ```
- Backend convention (existing resolvers): name filters take a list (`$name: [String]`).
  Check list vs scalar per filter before relying on it.

## Existing backend code worth reading (ideas only, no imports)

- `backend/services/nautobot/devices/query.py` — `DEVICE_DETAILS_QUERY`
  (device with role, type, platform, location, tags, interfaces and their IPs).
- `backend/services/nautobot/resolvers/` — name to UUID lookups (`devices(name:)`,
  `roles(name:)`, `locations(name:)`, `ip_addresses(address:)`, `name__ic`/`name__isw`).
- `backend/services/nautobot/common/rest.py` — bounded REST pagination.
- `backend/services/nautobot/location_types.py` — REST listing of location types.

## Verified with a read-only token (2026-10-27)

Header: `Authorization: Token <key>`. Works for `/api/status/` and `/api/graphql/`.
Never commit the token; the server reads it from `NAUTOBOT_TOKEN`.

- **Every filter is a list of strings** (`[String]`) on `devices`, `locations`,
  `ip_addresses`, `prefixes`, `roles`, `statuses`, `tags`. Only `q` is a scalar string and
  `limit`/`offset` are `Int`. A scalar is coerced to a one-element list.
- **Multi-value filters are accepted** (`role: ["Network","Server"]`). The test data is too
  small to prove OR semantics; Django-filter multi-value is OR. Recheck once data exists.
- **An unknown filter name is an HTTP 400**: `Unknown argument 'nonsense' on field
  'Query.devices'`. Our whitelist prevents this.
- **An unknown filter value fails the whole query**, with `data.devices = null` and
  `Select a valid choice. Nope is not one of the available choices.` (`role`, `location`,
  and by extension status, tag, ...). One bad value in a list fails the entire list. So the
  server must **validate values against the cached vocabulary first** and produce its own
  "did you mean" error. It must not forward unchecked names.
- `q` is a free-text search (`devices(q:"lab")` found `LAB.local.zz`) — the building block
  for a future `search_devices`.
- `limit` + `offset` work (`offset:1` skipped the first device).
- `ip_addresses(prefix:"10.0.0.0/24")` returns the addresses inside that prefix.
- Device to IP path: `devices{interfaces{name ip_addresses{address}}}`.
- `prefixes(location:"Country A")` returned nothing: no prefix in the test data is assigned
  to a location (`locations: []` on all 5), so descendant semantics for prefixes are
  **still unverified**. `devices(location:)` does include descendants (see above).
- Location names are not unique across parents in Nautobot. With name filters, a duplicate
  name matches several locations. The tools must report ambiguity and accept a UUID.

## IPAM (verified 2026-10-27)

- `ip_addresses`: `address` (with or without mask), `prefix` (inside a network),
  `namespace` (name; invalid name is an error), `role`, `status`, `tags`, `dns_name__ic`,
  `device` (**exact name only**; UUID and unknown names silently match nothing).
  `parent` takes a UUID, not a prefix string. `host` and `address__isw` do not exist.
- `prefixes`: `prefix`, `within_include`, `contains`, `namespace`, `role`, `status`, `tags`,
  `location`. **Invalid `contains` input is ignored and returns every prefix.**
- Invalid `address` / `prefix` text is a raw error (`invalid IPNetwork nonsense`).
- IP roles exist (Anycast, CARP, GLBP, HSRP, Loopback, Secondary, VIP, VRRP); prefix roles are
  empty in the dev data. Tags: none apply to IP addresses in the dev data.
- Nested fields used: `parent { prefix namespace { name } }`, `interfaces { name device {
  name } }`, `primary_ip4_for { name }`, prefix `vlan { vid name }`, `locations { name }`.
- Namespaces: `namespaces { name description }` (`Global`, `black`).
