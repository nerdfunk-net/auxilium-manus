# Auxilium Manus agent: ping-range

Pings an IPv4 range with **fping** for the *Route to Agent* step and answers, per host, whether it
is reachable, the average round-trip time, the packet loss and (if asked) the reverse-DNS name.
It is an independent copy of `agent/example-agent` (same envelope, transports, security model, see
that README and `doc/AGENT_INTEGRATION.md`) plus the `ping_range` handler. It is meant to run in
Docker because fping needs raw sockets and is not always runnable on the host.

## Run it (Docker)

```bash
cd agent/ping-range
cp .env.example .env     # set MANUS_AGENT_SECRET (openssl rand -base64 32), MANUS_AGENT_ID
docker compose up -d --build
```

`docker-compose.yml` publishes the agent's HTTP port on the Docker host: `MANUS_AGENT_HTTP_PORT`
(default 6667, because 8080 is Nautobot's) bound to `MANUS_AGENT_BIND` (default `127.0.0.1`). An
application running outside Docker uses `http://127.0.0.1:6667` as the agent URL (loopback source URLs
need `ALLOW_LOOPBACK_SOURCE_URLS=true`); for an app on another machine set `MANUS_AGENT_BIND` to the
host's address. The container's default network already routes to the pinged addresses and the DNS
server. If the app runs in Docker, attach the `data` and `egress` networks instead (commented block in the
compose file) and use `http://manus-ping-agent:6667`. In the app: **Settings → Credentials** (shared
secret, global), **Settings → Sources → Agents → Add agent** with the same Agent ID and credential, then
**Test connection**. For the Redis transport add the agent's user to `docker/redis/agents.acl` (see
`doc/AGENT_INTEGRATION.md`) and set `MANUS_AGENT_REDIS_URL`.

**Capabilities.** The container drops everything except `NET_RAW`. This compose file is deliberately
not under `docker/`, whose files must drop `NET_RAW` (`test_compose_networks.py`). Do **not** add
`no-new-privileges`: it disables fping's file capability and fping then reports 100 % loss for every
host without an error. The agent notices (nothing answered and 127.0.0.1 does not either) and fails
with a message naming `NET_RAW`.

Air-gapped hosts: `./prepare-agent-image.sh` builds the image and saves `airgap-artifacts/manus-agent-ping.tar.gz`
(`docker load` it on the target). Behind a proxy set `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` (used for apt and pip at build time; the container itself does not use a proxy).

Without Docker: `apt install fping`, then run as in `agent/example-agent/README.md`; the sample
`manus-agent.service` grants `CAP_NET_RAW` as an ambient capability.

## Using it in a workflow

Route to Agent step:

| Field | Value |
|---|---|
| `handler` | `ping_range` |
| `input_paths` | the attribute holding the range, e.g. `custom.range` (set by Update Attributes) or a Get from User/List attribute |
| `params` | optional JSON object, for example `{"resolve_dns": true}` (see below). With a single input path nothing else is needed; with several, add `range_attribute` to name the one that holds the range |
| `destination_path` | e.g. `agent.ping` |
| `output_keys` | `hosts`, `total`, `reachable`, `truncated` |
| `timeout_seconds` | see "How long does it take" |

The step calls the agent **once per device**: one device = one range = one scan. The results are then
`agent.ping.hosts`, `agent.ping.reachable`, ...

Example (range set earlier by an Update Attributes step, names looked up in DNS):

```
input_paths:      custom.range
params:           {"resolve_dns": true}
destination_path: agent.ping
output_keys:      hosts, total, reachable, truncated
```

More params in one object, and the case of several input paths:

```json
{"resolve_dns": true, "count": 2, "timeout_ms": 800, "include_unreachable": false}
{"range_attribute": "custom.range", "resolve_dns": true}
```

### Range syntax

Separated by commas, semicolons or new lines: `10.0.0.5`, `10.0.0.0/24` (network and broadcast address
left out up to /30; /31 and /32 keep all addresses), `10.0.0.5-10.0.0.40`, `10.0.0.5-40` (last octet).
IPv4 only. Hostnames are not accepted.

### Params (all optional)

| Param | Default | Meaning |
|---|---|---|
| `range_attribute` | the only input path sent | input path that holds the range; needed only when the step sends several (or none is named `range`) |
| `resolve_dns` | `false` | reverse-lookup the reachable hosts with the container's resolver |
| `count` | `1` (1-5) | packets per host |
| `timeout_ms` | `500` (50-5000) | wait per packet |
| `include_unreachable` | `false` | also list hosts that did not answer |
| `dns_timeout_seconds` | `2` (0.5-10) | deadline per lookup |

### Answer

```json
{"hosts": [{"ip": "10.0.0.1", "reachable": true, "rtt_ms": 0.42, "loss_percent": 0, "hostname": "gw.example.net"}],
 "total": 254, "reachable": 17, "truncated": false}
```

`hostname` is `null` when DNS is off, the lookup failed or timed out (DNS never fails the scan). `hosts` is
sorted by address. The step accepts at most 64 KiB per output value, so the list is cut when it would exceed
~60 KB and `truncated` is `true`; `total` and `reachable` always count the whole scan. By default only
reachable hosts are listed, which keeps even a /22 well inside the limit.

### How long does it take

fping starts one probe every 10 ms and sends the next round of probes after `timeout_ms`, so a scan takes
roughly `count × max(addresses × 10 ms, timeout_ms)` plus `timeout_ms`: a /24 with `count` 1 about 3 s,
a /20 about 45 s, 10 hosts with `count` 5 and the default timeout about 3 s. With `resolve_dns` add the
lookups: they share one budget of 15 s for the whole scan (hosts not resolved by then have no name), so DNS
can never make a scan overrun by more than that. The agent source's maximum timeout (default 60 s) and the
step's `timeout_seconds` must both be above the total; the call is cancelled (and fping killed) when time
runs out.

## Limits chosen by the operator of this agent

| Variable | Default | Meaning |
|---|---|---|
| `MANUS_AGENT_PING_MAX_HOSTS` | `4096` | most addresses per request (1-65536); larger requests fail before any packet is sent |
| `MANUS_AGENT_PING_ALLOWED_NETWORKS` | `10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` | comma separated IPv4 CIDRs; every address must lie inside them. Unset or empty means these private networks only; to scan public addresses say so explicitly (`0.0.0.0/0`) |

Whatever the list says, these are never pinged: `0.0.0.0/8`, loopback, link-local (`169.254.0.0/16`, includes
the cloud metadata address), multicast and the reserved block (`224.0.0.0/3`). A directed broadcast such as
`10.0.0.255` of a /24 cannot be recognised without the subnet mask: a CIDR range leaves its own broadcast
address out, but a dash range or a single address does not.

Both variables are checked when the agent starts: a bad value stops it (exit code 3, the reason on stderr)
instead of failing every request later.

The other variables (`MANUS_AGENT_ID`, `_SECRET`, `_HTTP_PORT`, `_REDIS_URL`, `_MAX_CONCURRENCY`, ...) are
those of `agent/example-agent`. The workflow author chooses the range; the **host operator** decides how far
it may reach.

## Development

```bash
cd agent/ping-range
pip install -r requirements-dev.txt
ruff check . && python -m pytest
```

`manus_agent/envelope.py` is a generated copy of `backend/services/agents/envelope.py`: never edit it here
(`backend/tests/unit/test_agent_envelope_sync.py`). The ping code is `manus_agent/ranges.py` (parsing),
`fping.py` (run and parse), `reverse_dns.py`, `ping.py` (the logic), `handlers/ping_range.py` (the wrapper).
