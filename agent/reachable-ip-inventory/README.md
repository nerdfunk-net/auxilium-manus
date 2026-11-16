# Auxilium Manus agent: reachable-ip-inventory

Builds a device inventory for the *Get from Agent* workflow step from the network itself. The step sends
the attribute `tag`; the agent reads the IPv4 prefixes with that Nautobot tag, pings each prefix with
**fping**, optionally looks up names with reverse DNS and answers the hosts that replied. It is an
independent copy of `agent/ping-range` (same envelope, transports and security model, see
`agent/example-agent/README.md` and `doc/AGENT_INTEGRATION.md`) plus a small Nautobot GraphQL client and a
`config.yaml`. It is meant to run in Docker because fping needs raw sockets.

## Run it (Docker)

```bash
cd agent/reachable-ip-inventory
cp .env.example .env             # MANUS_AGENT_SECRET (openssl rand -base64 32), MANUS_AGENT_ID, NAUTOBOT_TOKEN,
                                 # NAUTOBOT_DOCKER_NETWORK
cp config.example.yaml config.yaml   # nautobot.url, scan limits, DNS
docker compose up -d --build
```

Nautobot runs in Docker: set `NAUTOBOT_DOCKER_NETWORK` in `.env` to its Docker network (`docker network ls`; start Nautobot
first, the network must exist) and use Nautobot's container/service name and internal port as `nautobot.url`, for example
`http://nautobot:8080`. The agent joins that network **and** keeps its own default network, which stays the default route
(gateway priority) to the pinged addresses and the DNS server. Nautobot outside Docker: remove the `nautobot` network from
the compose file.

Behind a proxy, set `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` (in `.env` or your shell) before `docker compose up -d --build`: they are used
for apt and pip **while the image is built** and are not part of the running container, which never uses a proxy (Nautobot
and the pinged hosts are reached directly).

`docker-compose.yml` mounts `./config.yaml` read-only, publishes `MANUS_AGENT_HTTP_PORT` (default **6668**) on
`MANUS_AGENT_BIND` (default `127.0.0.1`) and gives the container only the `NET_RAW` capability. Do **not** add
`no-new-privileges`: it disables fping's file capability and fping then reports 100 % loss for every host (the agent
notices and fails with a message naming `NET_RAW`). In the app: **Settings → Credentials** (shared secret, global),
**Settings → Sources → Agents → Add agent** with the same Agent ID and credential, then **Test connection**. The other
transport and network notes are those of `agent/ping-range/README.md`. Without Docker: `apt install fping`, run as in
`agent/example-agent/README.md`.

**Start fails with "not a directory" while mounting `config.yaml`?** `config.yaml` did not exist when you ran
`docker compose up`, so Docker created an empty *directory* of that name. Run `rmdir config.yaml`, copy
`config.example.yaml` to `config.yaml`, edit it and start again.

## Using it in a workflow

*Get from Agent* step:

| Field | Value |
|---|---|
| `agent_source_id` | the agent source of this agent |
| `handler` | `list_devices` |
| `attributes` | `tag` = the name of a Nautobot tag, e.g. `ping` (or `{run_input.tag}` to choose it per run) |
| `timeout_seconds` | see "How long does it take" |

Only `tag` is supported; any other attribute is refused.

The answer:

```json
{"devices": [
  {"name": "gw.example.net", "ip_address": "192.168.178.1", "network_driver": ""},
  {"name": "192.168.178.20", "ip_address": "192.168.178.20", "network_driver": ""}
]}
```

`name` is the reverse-DNS name when `resolve_dns.enabled` is on and one was found, otherwise the IP address.
`network_driver` is empty; the step replaces an empty driver with its default (`cisco_ios`), so set the real driver with
a later step if the devices are not Cisco IOS. Devices are sorted by address.

### What it does

1. Asks Nautobot for the prefixes with the tag: `prefixes(tags: $tag) { prefix }` (the tag is a GraphQL variable).
2. Skips IPv6 prefixes (logged). Checks **every** other prefix before the first packet: inside `scan.allowed_networks`,
   never loopback/link-local/multicast/reserved, total at most `scan.max_hosts`. Network and broadcast address are left
   out up to /30. Overlapping prefixes are pinged once.
3. Pings the prefixes one after the other with fping and keeps the reachable addresses.
4. Optionally resolves the names. 5. Returns the inventory.

**Directed broadcasts.** A tagged aggregate such as `10.1.0.0/16` is one prefix: only its own network and broadcast
address (`10.1.0.0`, `10.1.255.255`) are left out, not the broadcast address of every `/24` inside it (`10.1.1.255`, ...).
If your network forwards directed broadcasts, such an address can answer and become a device. Tag the actual subnets
(for example the `/24`s) rather than an aggregate.

**No partial inventory:** an oversized or not-allowed prefix, Nautobot being unreachable or answering with an error, fping
failing, or no prefix with the tag fails the whole request. A scan where nothing answers returns an empty list only when
ICMP demonstrably works (a probe to 127.0.0.1 answers); otherwise it fails with a message naming `NET_RAW`. The step
accepts at most 5000 devices.

## `config.yaml`

Path: `MANUS_AGENT_CONFIG` (default `config.yaml`; `/app/config.yaml` in the image). Read when the agent starts;
a mistake stops it (exit code 3, the reason on stderr), and a change needs a restart. See `config.example.yaml`.

| Key | Default | Meaning |
|---|---|---|
| `nautobot.url` | required | `http://` or `https://`, no credentials in it |
| `nautobot.token_env` | - | name of the environment variable that holds the API token (preferred; wins over `token`) |
| `nautobot.token` | - | the token itself, if you accept it in a file |
| `nautobot.verify_ssl` | `true` | verify Nautobot's TLS certificate |
| `nautobot.timeout_seconds` | `15` | per request (1-120) |
| `nautobot.max_prefixes` | `100` | more tagged prefixes fail the request (1-1000) |
| `scan.count` | `1` | fping packets per host (1-5) |
| `scan.timeout_ms` | `500` | wait per packet (50-5000) |
| `scan.max_hosts` | `4096` | most addresses one request may ping (1-65536) |
| `scan.allowed_networks` | RFC 1918 | list of IPv4 CIDRs every address must lie in; public space needs an entry such as `0.0.0.0/0` |
| `resolve_dns.enabled` | `false` | name devices by reverse DNS |
| `resolve_dns.timeout_seconds` | `2` | per lookup (0.5-10); all lookups share a 15 s budget |

**Where the token may go.** `nautobot.url` must not name a link-local, multicast or unspecified address or a cloud metadata
name (the file is refused at start), and the connection itself refuses a name that resolves to one (also when the record
changes later), so the token cannot be sent there. Loopback and private addresses are fine (Nautobot on this host).

**What the workflow run sees.** A refused prefix (too large, outside `scan.allowed_networks`, never pingable) fails the
request with a fixed text; the prefix itself is only written to the agent log. A reverse-DNS name that is not a plain host
name (a metadata name, a loopback or link-local address, control characters, too long) is replaced by the IP address
instead of failing the inventory; the log says how many.

The token needs read access to IPAM prefixes. It is never written to a log line, an error message or a `repr`, Nautobot's
answers are never echoed, and redirects are not followed (they would forward the token). `config.yaml` is gitignored.

### No names although `resolve_dns.enabled` is on?

The agent logs one summary per scan (`docker logs manus-reachable-agent`):

```
reverse DNS: 2 of 7 named (no_ptr_record=4, resolved=2, resolver_error=1)
reverse DNS resolver_error, for example: gaierror: [Errno -3] Temporary failure in name resolution
```

* `resolved` - names found. The device is named after them.
* `no_ptr_record` - the DNS server answered, but has no reverse (PTR) record for that address: fix the DNS zone.
* `resolver_error` - the lookup itself failed: the container's resolver got a server failure or no answer (for example
  `herror: [Errno 2] Host name lookup failure`) or cannot reach a DNS server. Docker's resolver forwards to the host's, and
  may not answer reverse lookups of private (RFC 1918) addresses: set `dns:` in `docker-compose.yml` to the DNS server that
  knows your LAN (your router or internal DNS) and recreate the container.
* `timed_out_or_skipped` - the lookup was too slow: raise `resolve_dns.timeout_seconds` (all lookups share a 15 s budget).

A warning is logged when no host got a name. No `reverse DNS` line at all means DNS is off: `config.yaml` is read when the
agent starts, so **restart the container** after changing it. To try the resolver by hand:
`docker exec manus-reachable-agent python -c "import socket; print(socket.gethostbyaddr('192.168.178.1'))"`.

### How long does it take

Per prefix fping needs about `count × max(addresses × 10 ms, timeout_ms)` plus `timeout_ms`: a /24 about 3 s. Prefixes are
scanned one after the other, so add them up, plus up to 15 s for DNS and the Nautobot request. The agent source's maximum
timeout (default 60 s) and the step's `timeout_seconds` must both be above the total; the call is cancelled (and fping
killed) when time runs out.

## Development

```bash
cd agent/reachable-ip-inventory
pip install -r requirements-dev.txt
ruff check . && python -m pytest
```

`manus_agent/envelope.py` is a generated copy of `backend/services/agents/envelope.py`: never edit it here
(`backend/tests/unit/test_agent_envelope_sync.py`). The code of this agent is `manus_agent/inventory_config.py`
(config.yaml), `nautobot.py` (GraphQL), `inventory.py` (the logic) and `handlers/list_devices.py` (the wrapper);
`fping.py`, `ranges.py` and `reverse_dns.py` are copies from `agent/ping-range`.
