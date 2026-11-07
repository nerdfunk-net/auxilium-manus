# Client data: where is this MAC or IP address?

The `collect-client-data` step ("Collect Client Data") reads the ARP table and the MAC address table
of every device it is given and stores what it finds, so the question "where is this MAC / IP address
right now?" can be answered from live data. It is the workflow-step form of the Celery job in cockpit-ng
(`get_client_data`). This document covers the data model and the rules of the step; the REST endpoint,
the UI page and the Ask the Net tools are not built yet (see "Not built yet").

## What is collected

| Source command | Stored in | Columns |
|---|---|---|
| `show ip arp` (default VRF) and `show ip arp vrf <name>` for each VRF | `client_ip_addresses` | `ip_address`, `mac_address`, `interface`, `vrf`, `vlan`, `device_name`, `device_ip` |
| `show mac address-table` | `client_mac_addresses` | `mac_address`, `vlan`, `port`, `device_name`, `device_ip` |
| reverse DNS (PTR) of the ARP addresses, optional | `client_hostnames` | `ip_address`, `hostname`, `device_name`, `device_ip` |
| (outcome of the commands) | `client_data_collections` | `session_id`, `device_name`, `arp_status`, `mac_status`, `vrf_status`, `vrf_count`, `arp_rows`, `mac_rows` |

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

## Per-command outcomes

Each command is judged on its own (`parsing.classify_output`):

| Status | Meaning |
|---|---|
| `ok` | parsed rows, or an empty table: a header and no entry (ntc-templates has a template). Blank output counts as empty only for `show vrf` and per-VRF ARP, which print nothing when there is nothing to show. |
| `not_supported` | the device refused the command (`% Invalid input detected`, ...) - a router has no MAC address table |
| `no_template` | text that is neither a table nor a refusal: a banner, a dropped session, blank output for the default ARP or MAC table, or a table that still has entries that TextFSM did not parse (Netmiko returns raw text for that too, so a header-looking text that contains an IP or MAC is never "empty"). |
| `skipped` | switched off in the step configuration |

A device **fails** when it cannot be reached (connection, authentication, timeout), when a VRF ARP command fails
mid-way, when the output of a requested table is not a table (`unparsable_output`: storing it as "no rows" would
replace the device's good data), or when the device refused every table the step was asked for
(`nothing_collected`). A refused MAC table on a router is a success. A failed device stores nothing, so its older
data stays current. Supported platforms: Cisco IOS, IOS-XE and NX-OS; any other device fails with
`unsupported_platform`.

## "Current" data is per device

Each device's newest collection (`client_data_collections`, newest `collected_at`) is what queries show. A run
may cover only some devices, so there is no global "latest session": a device not in the newest run still shows
its own newest collection. An *empty* newest collection hides that device's older rows, which is why every
device writes a collection row even when it found nothing. `ClientDataQueryRepository.get_client_data` returns one row per *observation*:

* a MAC-table entry (MAC, device, VLAN, port) with the IPs the same device has in ARP for that MAC **and VLAN**;
  without one, an IP any other device saw for that MAC in the same VLAN, or in no known VLAN (a routed
  interface). A MAC with no VLAN takes any IP. An IP seen in a different VLAN is never attributed to it.
* an ARP entry that no MAC-table entry of its device matches, as its own row (port = the ARP interface, so a
  router without a MAC table still shows its ARP).
* the DNS hostname of the IP.

Each fallback is a single row per key, so joins never multiply rows (a MAC in two VLANs with two ARP entries is
four observations, not a product). Filters are case-insensitive substrings; the MAC filter accepts
`aa:bb:cc...`, `aa-bb-cc...` and `aabbcc...` as well as the stored form. `page` must be at least 1 and
`page_size` at most 500. `get_client_history` takes any MAC notation, any hostname case, and returns at most
`limit` (default 500, max 1000) rows per list.

**Caveat:** "newest" is decided per device, not per table. A run with `collect_ip_address` or
`collect_mac_address` switched off writes a collection with that table `skipped` and no rows for it, which
supersedes the device's earlier rows of that table in queries. Keep one configuration per device.

## Limits

* `device_ip` (45 characters) holds the device's address only when the SSH target is an IP address; a hostname
  target leaves it empty. Parsed values are cut to their column widths (VLAN 20, VRF 64, interface/port and
  hostname 255), so one overlong value cannot drop a collection.
* Reverse DNS resolves each address once per run, skips non-addresses and multicast, unspecified, loopback and
  reserved addresses, and stops after 1000 distinct addresses. It uses the worker's system resolver. The timeout
  counts from the start of a lookup, and an abandoned lookup keeps its slot until it ends, so at most
  `dns_concurrency` resolver calls are in flight.
* The rows of one device are written in one transaction (no row cap yet).

## Retention

* Each device keeps its newest `CLIENT_DATA_KEEP_SESSIONS` collections (default 5, at least 1); the step prunes
  while it writes.
* The `purge_client_data` task of the retention cron (`hatchet/workflows/purge_retention.py`) deletes
  collections older than `CLIENT_DATA_RETENTION_DAYS` (default 90, 0 keeps all) **except each device's newest**.
* Running the step again in the same run replaces that run's rows for the device.
* A collection is stamped when collection starts (before DNS and the write queue). The pruning never removes the
  collection being written, even when an overlapping run stored newer ones first (a device may briefly hold
  one more than `CLIENT_DATA_KEEP_SESSIONS`).

## Code map

* Models `core/models/client_data.py`, validated rows `models/client_data.py`
* Repositories `repositories/client_data_repository.py` (write, retention),
  `repositories/client_data_query_repository.py` (reads; window functions only, so they run on SQLite in the
  unit tests)
* Service `services/client_data/client_data_service.py`
* Step `workflow_steps/collect_client_data/`: `options.py`, `commands.py`, `parsing.py`, `collector.py`,
  `dns.py`, `executor.py`; panel `frontend/.../workflow-steps/collect-client-data/`
* Tests `tests/unit/test_collect_client_data_*.py`, `test_client_data_*.py`

## Not built yet

REST router and `client_data:read` permission, a UI page, Ask the Net tools (with the usual opt-in gating),
merging ACI endpoint data, the IPv6 neighbour table, and flagging trunk / uplink ports (a MAC address appears on
every switch it passes through, so "where is it" currently lists each of them).

## Verification status

* Unit tests cover parsing, the executor (scripted Netmiko), DNS, options, the repositories and retention; the
  read queries also run on PostgreSQL in `tests/integration/test_client_data_pg.py` (the `manus_test` database).
* **Not verified:** the step has not been run against real devices or through a real workflow run. Untested:
  IOS / IOS-XE / NX-OS output beyond the ntc-templates field names, `show vrf` on very old IOS, the volume of
  large ARP tables (`read_timeout`), and the frontend panel in a browser.
