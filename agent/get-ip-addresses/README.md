# Auxilium Manus agent: get-ip-addresses

Answers one question for the *Route to Agent* step: **which IP addresses does this device have?**
At startup the agent pulls a git repository, reads the CSV files in it the way the *Get Git Devices*
step does (same `{source, target}` column mapping) and keeps the parsed content in memory. The
step sends a device name; the agent returns only the lines of that device. It is an independent
copy of `agent/example-agent`: it shares no code with it.

Example file (`;` separated, one line per interface):

```
name;interface_name;interface_address;is_primary;namespace
device-1;eth0;10.0.0.2/24;true;black
device-1;eth1;192.168.181.10/24;false;Global
```

The app sends **data, never code**: the step names a handler, and only handlers that exist in
this agent's `handlers/` directory can run.

## Security model

* Every message is one AES-256-GCM envelope, keyed (HKDF) by a secret that only the app and this
  agent know. Opening it proves who sent it and that it is untampered; the ids, direction and
  expiry are authenticated too. A response cannot be replayed as a request.
* A request is accepted once (its `command_id` is remembered until it expires) and only while
  it is valid. Keep the clocks of both hosts in sync (NTP).
* Over HTTP a bearer token derived from the secret lets the agent drop unauthenticated traffic
  early. Plain HTTP is fine inside a Docker network because the payload is encrypted;
  terminate TLS in front of the agent if it is reachable from elsewhere.
* Over Redis the agent uses its own Redis user, limited to its keys (see below), so a stolen
  agent host cannot touch the app's other Redis data or another agent's traffic.
* The agent never logs payloads. Handlers you write may see secrets that were selected as
  inputs: treat the handlers directory as trusted code.

## Run it

```bash
cd agent/get-ip-addresses
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env        # edit it; export the variables or use --env-file / EnvironmentFile
set -a; . ./.env; set +a
./venv/bin/python -m manus_agent
```

In the app: **Settings → Credentials**, add a *shared secret* credential (global, 32+ random
characters: `openssl rand -base64 32`). **Settings → Sources → Agents → Add agent**: Agent ID
and the credential must match `MANUS_AGENT_ID` and `MANUS_AGENT_SECRET`. Save, then use
**Test connection**.

| Variable | Default | Meaning |
|---|---|---|
| `MANUS_AGENT_ID` | required | Lowercase id; equals the source's Agent ID. |
| `MANUS_AGENT_SECRET` | required | Shared secret, at least 32 characters. |
| `MANUS_AGENT_HTTP_PORT` | - | Enables the HTTP transport on this port. |
| `MANUS_AGENT_HTTP_HOST` | `0.0.0.0` | Bind address for HTTP. |
| `MANUS_AGENT_REDIS_URL` | - | Enables the Redis transport (`redis://`, `rediss://`, `unix://`). |
| `MANUS_AGENT_HANDLERS_DIR` | `handlers` | Directory with the handler files. |
| `MANUS_AGENT_DATA_CONFIG` | `config.yaml` | The data source (git, files, mapping), see below. |
| `MANUS_AGENT_STATE_DIR` | `state` (`/data` in the image) | The only place the agent writes: the git checkout and the SSH `known_hosts`. Under systemd: `/var/lib/manus-agent`. |
| `MANUS_AGENT_ALLOW_FILE_URLS` | - | `1` allows a `file://` git URL (development and tests only). |
| `MANUS_AGENT_MAX_CONCURRENCY` | `4` | Handlers running at once. |
| `MANUS_AGENT_MAX_BODY_BYTES` | 16 MiB | Largest HTTP request accepted. |
| `MANUS_AGENT_MAX_RESPONSE_BYTES` | 16 MiB | Largest answer a handler may return; above it the device fails with `InvalidOutput`. |
| `MANUS_AGENT_LOGLEVEL` | `INFO` | Python log level. |

At least one of `MANUS_AGENT_HTTP_PORT` and `MANUS_AGENT_REDIS_URL` is required.

## The data source (`config.yaml`)

`config.example.yaml` documents every key. Summary:

| Section | Keys |
|---|---|
| `git` | `url`, `branch` (default `main`), `checkout_dir` (default `repo`, a path inside the state directory), `verify_ssl`, `auth` |
| `git.auth` | `type: none`, or `token` (`token_env` = environment variable holding the token, `username`), or `ssh` (`key_file`) |
| `source` | `directory` inside the repository, `filename_pattern` (default `*.csv`), `csv_delimiter` (`;` `,` `\t` `\|`) |
| `mapping` | `{source, target}` rows. Required: `name`, `interfaces.name`. Also `interfaces.ip_addresses.address`, `interfaces.ip_addresses.parent.namespace.name`, `interfaces.description/type/mac_address/mtu/status.name`, `_is_primary`, `_ignore` |

On every start the agent clones the repository (or fetches and hard-resets the existing checkout
to the branch tip), reads all matching files and builds the index. **If any of that fails the agent
exits with code 4 and does not start**; it never serves an empty or stale cache. Warnings (ragged
lines, devices with two primary interfaces) are logged with the device name and a problem code only (the details, such as addresses, are in the handler's `problems`). To load new data
restart the agent. The startup reads at most 128 MiB and 1,000,000 lines in total; more makes the agent exit with code 4. Only `https://` remotes may use a token; `git.url` must not carry credentials. Credentials are never written to the config file, to the git command line or to
the log.

Lines with the same device name (in one or several files) are merged. A line flagged
`_is_primary` makes its address (and namespace) the device's `primary_ip4`; two different primaries
or an unreadable flag give a problem and no `primary_ip4`. Device names are compared exactly; a request that differs only in case still finds the device when exactly one name matches. Two names that differ only in case stay two devices (a startup warning says so).

## The handler `get_ip_addresses`

Route to Agent step setup:

| Field | Value |
|---|---|
| Handler | `get_ip_addresses` |
| Input paths | `name` (the device name; to use another attribute set `{"name_attribute": "<path>"}` as params) |
| Output keys | `found`, `interfaces`, `primary_ip4`, `problems` |
| Allow missing outputs | on (`primary_ip4` is left out when the device has none) |
| Destination | for example `agent.ip` |

Answer for `device-1` of the example file:

```json
{
  "found": true,
  "device": "device-1",
  "interfaces": [
    {"name": "eth0", "ip_addresses": [{"address": "10.0.0.2/24", "parent": {"namespace": {"name": "black"}}}]},
    {"name": "eth1", "ip_addresses": [{"address": "192.168.181.10/24", "parent": {"namespace": {"name": "Global"}}}]}
  ],
  "primary_ip4": {"address": "10.0.0.2/24", "parent": {"namespace": {"name": "black"}}},
  "problems": []
}
```

A device that is not in the files gets `{"found": false, "device": "...", "interfaces": [], "problems": []}`;
this is an answer, not an error. `echo` is built in and is what *Test connection* calls.

## HTTP transport

`POST /v1/invoke` with the envelope as the JSON body and `Authorization: Bearer <token>`.
`GET /healthz` answers `{"status": "ok"}` without authentication. Status codes: 401 bad token,
403 message failed authentication, 409 replayed, 400 malformed, 413 too large.

## Redis transport

The agent connects to the **app's Redis** and uses these keys (`<id>` is the agent id):

| Key | Type | Use |
|---|---|---|
| `manus-agent:<id>:req` | list | the app pushes requests, the agent pops them |
| `manus-agent:<id>:resp:<command>` | list | the agent pushes the answer (expires after 2 minutes) |
| `manus-agent:<id>:hb` | hash | heartbeat: status, version, handlers, last_heartbeat (expires after 90 s) |

Create a Redis user for the agent that can only do that (the dialog in the app shows the same
command for your agent id; use an ACL file so it survives restarts). `ACL SETUSER` only *adds*
rules to an existing user, so the command starts with `reset`: running it again replaces any
key patterns, commands and passwords the user had before. The app needs **Redis 7 or newer**
(`EXPIRE ... NX/GT`).

```
ACL SETUSER agent-<id> reset on ><redis-password> ~manus-agent:<id>:* +blpop +rpush +hset +expire +del +ping
```

The agent only pulls a request when it has capacity, so surplus work waits in Redis. If the
secret or Agent ID differs, the agent cannot verify a message and ignores it, so the app sees a
timeout rather than an error: check both when *Test connection* times out.

## Docker

```bash
docker build -t manus-ip-agent .
docker run --rm --env-file .env -p 8080:8080 \
  -v "$PWD/config.yaml:/app/config.yaml:ro" manus-ip-agent
```

The image contains git and a copy of `config.example.yaml`; mount your own `config.yaml` over it. The state directory is `/data` (checkout in `/data/repo`, SSH host keys in `/data/known_hosts`); mount a volume on `/data` only if you want to keep it across container re-creation, otherwise the repository is cloned again. The entrypoint starts as root, makes `/data` writable for the `agent` user and drops privileges, so a fresh volume works. On the app's Docker network use `http://<container-name>:8080` as the agent URL.

### Company root certificates (TLS-inspecting proxy / private PKI)

If your network re-signs TLS traffic with a company CA, `pip install` fails during the build with
certificate errors. Put the root (and any intermediate) certificates into `certs/` **before** building:

- PEM text files named `*.crt` or `*.pem` (convert DER/`.cer` files with
  `openssl x509 -inform der -in x.cer -out x.crt`). Several files are fine.
- At build time they are added to the system trust store and `pip` is pointed at the resulting bundle
  (`/etc/pip.conf`).
- At run time `entrypoint.sh` exports `REQUESTS_CA_BUNDLE` and `SSL_CERT_FILE` for the same bundle, so
  Python HTTP clients trust the company CA too.
- With no certificates in `certs/` (only `.gitkeep`), none of this is applied and the image is unchanged.

The certificates end up in the image; do not push an image built with them to a public registry.
Changing `certs/` invalidates the build cache from that point on, so a rebuild is needed.

## systemd

See `manus-agent.service` (user `manus-agent`, code in `/opt/manus-agent`, variables in
`/etc/manus-agent/agent.env`, mode 0600).

## Tests

```bash
pip install -r requirements-dev.txt && pytest
```

`manus_agent/envelope.py` is a standalone copy of `backend/services/agents/envelope.py`
(the agent must not import the backend). `backend/tests/unit/test_agent_envelope_sync.py` fails if
they drift apart, and `backend/tests/unit/test_agent_interop.py` runs the app's client against
this agent over HTTP and Redis.
