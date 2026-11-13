# Client data: where is this MAC or IP address?

The `collect-client-data` step ("Collect Client Data") reads the ARP table and the MAC address table
of every device it is given and stores what it finds, so the question "where is this MAC / IP address
right now?" can be answered from live data. It is the workflow-step form of the Celery job in cockpit-ng
(`get_client_data`). This document covers the data model and the rules of the step, the REST API and the
Ask the Net tools; the UI page is not built (see "Open").

## What is collected

| Source command | Stored in | Columns |
|---|---|---|
| `show ip arp` (default VRF) and `show ip arp vrf <name>` for each VRF | `client_ip_addresses` | `ip_address`, `mac_address`, `interface`, `vrf`, `vlan`, `device_name`, `device_ip` |
| `show mac address-table` | `client_mac_addresses` | `mac_address`, `vlan`, `port`, `device_name`, `device_ip` |
| reverse DNS (PTR) of the ARP addresses, optional | `client_hostnames` | `ip_address`, `hostname`, `device_name`, `device_ip` |
| `show lldp neighbors detail` and `show cdp neighbors detail`, with `show etherchannel summary` (IOS, IOS-XE) or `show port-channel summary` (NX-OS), optional (`collect_neighbors`) | `client_port_neighbors` | `port`, `channel`, `neighbor_name`, `neighbor_port`, `protocol` (`lldp`/`cdp`), `capabilities`, `is_infrastructure`, `device_name`, `device_ip` |
| (outcome of the commands) | `client_data_collections` | `session_id`, `device_name`, `arp_status`, `mac_status`, `vrf_status`, `neighbor_status`, `vrf_count`, `vrfs`, `target_host`, `arp_rows`, `mac_rows`, `neighbor_rows` |

* **`session_id`** is the uuid of the workflow run. With `device_name` it identifies one *collection*.
* **MAC format** is normalised to dotted quads (`aabb.ccdd.eeff`) for every platform, so ARP and MAC-table
  rows join.
* **`interface` versus `port`.** `interface` is the layer-3 interface of an ARP entry (an SVI such as `Vlan10`);
  `port` is where the MAC address was learned. They are kept apart.
* **VLAN** comes from the MAC table, or, for an ARP entry, from an SVI interface name (`Vlan10` -> `10`). It is
  `NULL` for other interfaces.
* **VRF** is `NULL` for the default VRF.
* **VRF discovery** runs `show vrf` (there is no TextFSM template for `show ip vrf`). `default` is skipped;
  names that are not plain (letters, digits, `_ . : -`, at most 64) are dropped, because they are put into a
  command.

* **Neighbours** (`collect_neighbors`, off by default because it adds commands per device). `port` is the local port in the short form the
  MAC address table prints (`GigabitEthernet1/0/48` -> `Gi1/0/48`, `Ethernet1/5` -> `Eth1/5` on NX-OS and `Et1/5` on IOS, `Port-channel1` ->
  `Po1`); that is how a neighbour is matched to a MAC-table port, the maintainer checked it live in an IOS-only lab (2026-11-08, it works); NX-OS and port-channels were not covered.
  `channel` is the port-channel the port belongs to, read from the channel summary (without it only the member port matches). `capabilities`
  is a closed vocabulary (`bridge`, `router`, `wlan_ap`, `station`, `telephone`, `repeater`, `docsis`, `other`) from LLDP's letters
  (`B,R`) or CDP's words (`Router Switch IGMP`; CDP's legacy letters mean something else, `S` is Switch there); unknown words are dropped.
  `is_infrastructure` is `bridge`, `router` or `wlan_ap` (a device with other devices behind it). The templates exist in ntc-templates for all
  four commands on IOS and NX-OS (verified in the installed index); the field names are read in `parsing.parse_neighbors` / `parse_channels`.
* **`vrfs`** (nullable JSON) lists every discovered VRF as `{name, status, rows}`: the status of its `show ip arp vrf <name>` (`ok`,
  `not_supported`, `no_template`; `skipped` when the VRF was found but the default ARP table was unusable, so it was not read) and the
  entries parsed. `ok` with `rows: 0` is an empty VRF; the other statuses mean the table could not be read. `NULL` means VRFs were not
  discovered (`collect_vrfs` off, or `show vrf` refused): unknown, not "no VRFs". `[]` means discovery ran and found none. The list is read from
  the ARP collection and shown by `GET /client-data/devices` (`vrfs`), `get_client_data_coverage` (`vrf_results`) and the step summary
  (`parsed.<node>.client_data.vrf_results`). Existing rows have `NULL` until the next run.

## Per-command outcomes

Each command is judged on its own (`parsing.classify_output`):

| Status | Meaning |
|---|---|
| `ok` | parsed rows, or an empty table: a header and no entry (ntc-templates has a template). Blank output counts as empty only for `show vrf` and per-VRF ARP, which print nothing when there is nothing to show. |
| `not_supported` | the device refused the command (`% Invalid input detected`, ...) - a router has no MAC address table |
| `no_template` | text that is neither a table nor a refusal: a banner, a dropped session, blank output for the default ARP or MAC table, or a table that still has entries that TextFSM did not parse (Netmiko returns raw text for that too, so a header-looking text that contains an IP or MAC is never "empty"). |
| `skipped` | switched off in the step configuration |

Neighbours are judged per command too, and the two (LLDP and CDP) become one `neighbor_status`: `no_template` if either was output that is not
a table (a dropped session, a banner), else `ok` if either was read, else `not_supported` (neither protocol is on). A protocol that is switched
off (`% LLDP is not enabled`) is `not_supported`. **Blank neighbour output is `no_template`, never an empty table** (a dropped session prints
nothing too); only an explicit `Total entries displayed: 0` is empty. Neighbour data only sharpens the uplink guess, so it **never fails the
device**: `no_template` stores no neighbour rows and the older neighbours stay current.

A device **fails** when it cannot be reached (connection, authentication, timeout), when a VRF ARP command fails
mid-way, when the output of a requested table is not a table (`unparsable_output`: storing it as "no rows" would
replace the device's good data), or when the device refused every table the step was asked for
(`nothing_collected`), when a table is above `CLIENT_DATA_MAX_ROWS_PER_TABLE` (`too_many_rows`), or when another execution already stored a device of the same name for the run (`duplicate_key`). A refused MAC table on a router is a success. A failed device stores nothing, so its older
data stays current. Supported platforms: Cisco IOS, IOS-XE and NX-OS; any other device fails with
`unsupported_platform`.

## "Current" data is per device and per table

For each device, ARP (with its VRFs and hostnames), the MAC table and the neighbours are each current from **the newest collection that read
that table** (`client_data_collections`; status `ok` or `not_supported`, see `core.models.client_data.table_was_read`; `skipped` and a
neighbour `no_template` are not observations). A run may cover only some devices, so there is no global "latest session"; and
a run that left a table out (`collect_ip_address` or `collect_mac_address` off) does not hide the earlier rows of that table, so ARP and the
MAC table of one device can come from different runs. A table the device **refused** (`not_supported`) or that was **empty** is an observation
and does supersede the older rows, which is why every device writes a collection row even when it found nothing. Coverage
(`GET /client-data/devices`, `get_client_data_coverage`) reports the time and status of each table separately.

`ClientDataQueryRepository.get_client_data` returns one row per *observation*:

* a MAC-table entry (MAC, device, VLAN, port) with the IPs the same device has in ARP for that MAC **and VLAN**;
  without one, an IP any other device saw for that MAC in the same VLAN, or in no known VLAN (a routed
  interface). A MAC with no VLAN takes any IP. An IP seen in a different VLAN is never attributed to it.
* an ARP entry that no MAC-table entry of its device matches, as its own row (port = the ARP interface, so a
  router without a MAC table still shows its ARP).
* the DNS hostname of the IP.

Every observation has two times: `collected_at` is the port (MAC table) or the ARP entry, `ip_collected_at` is the ARP collection that gave the
`ip_address` (none without an IP). They differ when the MAC table was read later than ARP or the IP came from another device. An IPv6 address
matches in any notation (`2001:DB8::5`, the expanded form), as a MAC does. Exact matching of a hostname ignores case.

Observations are ordered by IP address (on PostgreSQL numerically and IPv4 before IPv6: `10.0.0.2` before `10.0.0.10`; SQLite, used in unit tests,
sorts the text), then MAC and device. With `likely_first` the likely location and access ports come before that order.

Each fallback is a single row per key, so joins never multiply rows (a MAC in two VLANs with two ARP entries is
four observations, not a product). Filters are case-insensitive substrings; the MAC filter accepts
`aa:bb:cc...`, `aa-bb-cc...` and `aabbcc...` as well as the stored form. `page` must be at least 1 and
`page_size` at most 500. `get_client_history` takes any MAC notation, any hostname case, and returns at most
`limit` (default 500, max 1000) rows per list.


## Limits

* `device_ip` (45 characters) holds the device's address only when the SSH target is an IP address; a hostname
  target leaves it empty. Parsed values are cut to their column widths (VLAN 20, VRF 64, interface/port and
  hostname 255), so one overlong value cannot drop a collection.
* Reverse DNS resolves each address once per run, skips non-addresses and multicast, unspecified, loopback and
  reserved addresses, and stops after 1000 distinct addresses. It uses the worker's system resolver. The timeout
  counts from the start of a lookup, and an abandoned lookup keeps its slot until it ends, so at most
  `dns_concurrency` resolver calls are in flight.
* The rows of one device are written in one transaction. A device whose ARP or MAC table has more rows than `CLIENT_DATA_MAX_ROWS_PER_TABLE` (default 200 000, at least 1; equal is allowed) fails with `too_many_rows` (`FailureInfo(phase="command", kind="payload_too_large")`) and stores nothing, so its older data stays current. The collector counts the raw rows of each table **before parsing** them, right after the first round trip and before any per-VRF read, so an oversized default ARP or MAC table is refused without a second round trip. Per-VRF ARP tables are read **one command at a time**, the running total (default VRF plus the VRFs read so far) is checked after each, and reading stops at the first overflow (later VRFs are never requested). Nothing is sent to DNS and the service checks again before writing. **Limit:** Netmiko reads one command's output to completion, so the cap does not bound the bytes of a single table the device sends; it bounds the parsing, the further round trips, the DNS and the storage. A byte limit on the read would be a change in the shared Netmiko service.

## Same device name twice

Collections are keyed by run and device name (`uq_client_data_collection_session`), and each remembers the SSH target it came from
(`target_host`). Two devices with one name inside one step are caught before any connection (`duplicate_key`). Two fan-out children (or sibling
branches) are separate executions, so the repository decides at write time, **before deleting anything**: a collection already stored for this
run and name from a *different* target is another device with the same name, so `CollectionConflictError` is raised and the first device's rows
stay; the device fails as `duplicate_key` ("another device in this run has the same name ... client data is stored per device name"), not as
`storage_failed`. The same target (a retry or a rerun of the same device) replaces its own rows. A collection without a recorded target (rows
from before the column existed) is replaceable, and so is a write without a target. If the two writes overlap, the unique key fires at insert and
gives the same error. It is an inventory problem and is not retried as a replace.

## Retention

* Each device keeps its newest `CLIENT_DATA_KEEP_SESSIONS` collections (default 5, at least 1); the step prunes
  while it writes.
* The `purge_client_data` task of the retention cron (`hatchet/workflows/purge_retention.py`) deletes
  collections older than `CLIENT_DATA_RETENTION_DAYS` (default 90, 0 keeps all) **except each device's newest collection and its
  newest collection of each table**.
* Running the step again in the same run replaces that run's rows for the device.
* A collection is stamped when collection starts (before DNS and the write queue). The pruning never removes the
  collection being written, even when an overlapping run stored newer ones first, and never the newest collection that read ARP or
  the MAC table (a device may hold a few more than `CLIENT_DATA_KEEP_SESSIONS`).

## Code map

* Models `core/models/client_data.py`, validated rows `models/client_data.py`
* Repositories `repositories/client_data_repository.py` (write, retention),
  `repositories/client_data_query_repository.py` (reads; window functions only, so they run on SQLite in the
  unit tests)
* Service `services/client_data/client_data_service.py`
* Step `workflow_steps/collect_client_data/`: `options.py`, `commands.py`, `parsing.py`, `collector.py`,
  `dns.py`, `executor.py`; panel `frontend/.../workflow-steps/collect-client-data/`
* Tests `tests/unit/test_collect_client_data_*.py`, `test_client_data_*.py`, `test_ai_host_lookup_tools.py`

## Cost of a lookup (2026-11-13)

The correlated view (MAC table x ARP table x VLAN fallbacks x hostnames, `_combined`) is built from window-function CTEs. PostgreSQL has no
statistics for a window column, guesses a handful of rows and plans **nested loops**, which compare every MAC row with every ARP row. On a
production copy (9,800 MAC rows, 5,800 ARP rows) one IP lookup discarded 176 million rows in join filters and took 61 s, and the cost grows with the
square of the table sizes. Two measures, both in `repositories/client_data_query_repository.py`:

* **Narrowing** (`_narrowing`): every filter (`ip_address`, `ip_prefix`, `mac_address`, `hostname`, `device_name`, `port`, `vlan`, `vrf`) selects the
  MACs that have a matching MAC-table or ARP row (CTE `candidate_macs_<filter>`), and the correlation reads only those MACs. This is exact, not an
  approximation: everything computed for a MAC (IP fallbacks, `likely_location`) is computed among that MAC's own rows, and the filter still runs on
  the result. `macs_on_port` is deliberately **not** narrowed (it counts all MACs of the port). The filter meaning lives in one place
  (`_predicates`), used for the final filter and for the narrowing, so the two cannot drift. `tests/unit/test_client_data_narrowing.py` compares the
  narrowed lookup with the full view for every filter, exact/substring, `likely_first` and `hide_uplinks`.
* **Hash-join guard** (`_hash_joins`, PostgreSQL only): `enable_nestloop = off` for the count and data statements (restored afterwards). A lookup that
  cannot be narrowed (no filter, `hide_uplinks` only, a substring that matches everything) is then linear too. It does not forbid a nested loop, it
  makes one expensive.

Measured on a scratch database with the same shape (lab, PostgreSQL 17): 9,750 MAC / 5,800 ARP rows 50 s -> 0.05 s for an IP lookup; 29,000 MAC rows
and 17,400 hostnames: 0.1-0.5 s for every kind of lookup, also without a filter; 97,500 MAC / 58,000 ARP rows: 0.2-1.7 s. At three times the
production size the old query needed 242-302 s (822 million discarded rows). `tests/integration/test_client_data_pg.py` checks the plan (rows
removed by join filters) on PostgreSQL. Diagnose with `backend/scripts/analyze_client_tool.py` (`plan`, `time`).

## Uplinks and the likely location

A MAC address appears on every switch it passes through, so a lookup lists each of them. For every MAC-table observation the query computes,
from the current data and without storing anything:

| Field | Meaning |
|---|---|
| `macs_on_port` | distinct MACs that device learned on that port (`NULL` for an ARP-only observation) |
| `is_uplink` | the port has an infrastructure neighbour (below), **or** `macs_on_port` is above `CLIENT_DATA_UPLINK_MAC_THRESHOLD` (default 10, at least 1) |
| `uplink_reason` | `neighbor` (a bridge, router or wireless access point seen through LLDP/CDP on the port or on a member of its port-channel; wins when both apply) or `mac_count` (only the count); `NULL` for an access port |
| `uplink_to` | the neighbour behind a `neighbor` uplink (the lowest name when several, for example LLDP and CDP both) |
| `likely_location` | per MAC, the MAC-table observation on a **non-uplink** port with the fewest MACs (ties: device name, port) |

An uplink never beats an access port in the ranking, however few MACs it has learned: a trunk with two MACs and a router behind it does not
become the likely location of a host that also sits on a busy access port. The tie-break is a full ordering (device, port, VLAN, VRF, IP), so
equal scores pick the same row every time. `likely_first` (the Ask the Net lookup) orders the likely location, then access ports, then uplinks
**before** the page is cut, so the best answer is on the first page however many switches saw the MAC. History is collapsed to one entry per
collection in SQL before its limit.

What the neighbour data fixes and what it does not. It fixes a **lightly used trunk** (below the threshold) and a **port-channel** (the bundle
counts as one port through its members). It does not fix a **busy access port** (a hypervisor, a hub, an access point that does not advertise
itself): the count rule still applies as an OR, because ports without neighbour data (a device that was not collected with `collect_neighbors`,
or one that runs neither protocol) have nothing else to go on. A phone or host neighbour does not make a port an uplink. Neighbour ports are
matched to MAC-table ports by name after `normalise_port`; a port named differently by the two commands would not match (works in the maintainer's IOS-only lab without port-channels, 2026-11-08; NX-OS, port-channels and other port types unchecked).
A MAC seen only on uplinks has no `likely_location`. `hide_uplinks` leaves uplink rows out.

## REST API

`client_data:read` (not in the seeded `viewer` role; an admin grants it) gives:

| Route | Returns |
|---|---|
| `GET /client-data` | observations; filters `device_name`, `ip_address`, `mac_address`, `port`, `vlan`, `vrf`, `hostname` (substrings, or whole values with `exact=true`), `ip_prefix` (the start of the address, `10.1.` does not match `110.1.2.3`; digits, hex letters, `.` and `:` only), `hide_uplinks`, `page` (>= 1), `page_size` (1-500) |
| `GET /client-data/history` | **exactly one** of `ip_address`, `mac_address`, `hostname` (400 for none or several), `limit` (1-1000) |
| `GET /client-data/devices` | each device's newest collection: age and the status of its commands (coverage) |

Reads are rate limited (`client-data-read`, 120 per minute per user). The router goes through `ClientDataService`
(`routers/` may not import repositories).

## Ask the Net

Four read tools (`find_client`, `list_clients`, `get_client_history`, `get_client_data_coverage`) answer "where is this MAC / IP?" from the same
queries: `doc/AI_TOOL_CHAIN.md` §48. They need `client_data:read` (checked on every call) and the user's inventory and addresses switches.
Where an ACI source is configured as well, `find_host` asks the client data and the APIC in one call (`tools/host_lookup_tools.py`): two sections,
each with its own source, status (`found`, `not_seen` / `not_learned`, `not_applicable`, `error`) and freshness (the client data is stored and
has ages; the APIC is the live view at the call), never merged into one schema or one age. The fabric is asked for a MAC or an IPv4 address only;
an IPv6 address or a hostname is client data only. It is a composition of `find_client` and `find_aci_endpoint`, so each keeps its own checks
(`client_data:read`, `sources.aci:read`, the data switches, the ACI rate budget), a source that is denied or failing is a status of its section and
not a reason to drop the other, and it is offered only when both readers exist. Only the first five rows of each source are shown.

## Open

A UI page (`doc/OPEN_TODOS.md`), the IPv6 neighbour table and other platforms than Cisco IOS, IOS-XE and NX-OS. The list with detail is
`doc/plans/CLIENT_DATA_CONTINUE.md`.

## Verification status

* Unit tests cover parsing, the executor (scripted Netmiko), DNS, options, the repositories and retention; the
  read queries also run on PostgreSQL in `tests/integration/test_client_data_pg.py` (the `manus_test` database).
* **Run live:** the step ran on a lab IOS router and switch (2026-11-07), and the maintainer checked the LLDP/CDP uplinks (`collect_neighbors`),
  `find_host` and the Ask the Net playbook/prompt change in their lab on 2026-11-08 (they work). That lab is IOS only and has no port-channel.
* **Not verified:** NX-OS (output beyond the ntc-templates field names, `Eth` port names, the port-channel summary), port-channels (the `show etherchannel summary` parsing and an uplink found through a bundle's member ports), VPC / FEX / breakout / stack port names, `show vrf` on very old IOS, a
  VRF with ARP entries, the volume of large ARP tables (`read_timeout`), a larger network, and the frontend panel in a browser.
