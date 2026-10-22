# Security Notes — Accepted Risks

This file records security-adjacent findings from the 2026 security reviews that were reviewed and
intentionally left as-is, with the reasoning, so they aren't re-investigated from scratch later.
Entries are accepted for a trusted-operator deployment; each lists what you must provide.

## Development settings file override (`MANUS_ENV_FILE`)

`backend/.env` is read only for `ENV=development`. `MANUS_ENV_FILE` points a development run at another file (the
unit tests point it at `/dev/null` so a developer's own file is never picked up). A production image never reads
any file: with `ENV` unset or `production` neither variable has an effect.

## `verify_ssl=False` support (Nautobot, ISE, Catalyst Center, Mattermost clients)

Each client keeps a second, non-verifying `httpx.AsyncClient` pool because on-prem instances in
NetDevOps environments commonly present self-signed certificates. Every request made with
`verify_ssl=False` is logged at `WARNING` with the target host. **Mitigated, not accepted**: the opt-out
exists for development only. Outside `ENV=development`, `core.safe_urls.validate_source_transport`
refuses an `http://` URL and `verify_ssl=false`; it runs when a source is saved or tested
(`*_source_config_service.py`, `SettingsService` for Nautobot) **and on every request** in the
Nautobot, ISE, Catalyst Center and Mattermost clients (pyATS is exempt, see below), so a row saved before the check existed stops working until its CA is installed
(`INSTALL_CERTIFICATE_FILES`) or its URL is changed to https.

Git repositories follow the same rule: `verify_ssl=false` is refused outside development, both when
a repository is saved and when it is used. A private CA is installed with `INSTALL_CERTIFICATE_FILES`.
Batfish and pyATS have no TLS at all (see their entries).

A source also only accepts a **global** credential of the type it authenticates with
(`services/credentials/source_credentials.py::SOURCE_CREDENTIAL_TYPES`), so a device SSH password or a
Secret Manager credential cannot be sent to a source URL:

| Source | Credential type |
|---|---|
| Nautobot, Mattermost, pyATS | `token` |
| ISE, Catalyst Center | `generic` |

Granting `sources.<x>:write` / `sources.<x>:delete` is admin-only (policy P3), because a holder can
point a source at a URL of their choosing and have the bound credential sent there by test-connection.

## Netmiko: no SSH host-key verification

`services/network/netmiko/connection.py` builds `ConnectHandler(**device_params)` with no host-key
checking parameters; Netmiko's default behavior auto-accepts unknown host keys (equivalent to
`StrictHostKeyChecking=no`). **Accepted as-is**: standard practice for NetDevOps automation tooling
targeting a known device inventory, but worth stating explicitly here since it's a real MITM exposure if
the management network is ever untrusted. The template-editor preview endpoints
(`/netmiko/run-commands`, `/netmiko/get-configs`) deny SSH to arbitrary hosts outside development
unless `ALLOW_NETMIKO_ARBITRARY_HOSTS=true` (`core/safe_hosts.py`); this host-key-checking gap remains
accepted for whatever host the preview (or a workflow run) is allowed to reach. Git over ssh uses
`StrictHostKeyChecking=accept-new` (trust on first use). Telnet device types are accepted: Netmiko
offers 62 `*_telnet` `device_type` values and `network_driver_override` takes any of them, so
credentials can travel in cleartext. **You must provide** a trusted management network.



## pyATS shim: device credentials over plain HTTP

`backend/services/pyats/client.py` sends device SSH credentials to the `pyats-shim` container in the
`POST /v1/jobs` request body over plain HTTP. **Accepted as-is**, as an operator requirement: keep the
shim on a network only the workers share (the shipped compose gives it its own `manus-pyats` network
and publishes its port on `127.0.0.1` only), and use a 32+ character `PYATS_SHIM_TOKEN`. If the shim is
ever reachable from anywhere else, this must move to HTTPS first. See `doc/PYATS_INTEGRATION.md`. The
source transport policy above deliberately does **not** apply to the pyATS source, which keeps only the
SSRF/URL checks and the `token` credential-type rule.

## Git debug write endpoints (`test_write`/`test_delete`/`test_push`)

`services/git/debug_service.py`'s `test_write`, `test_delete`, and `test_push` perform real filesystem
writes and real pushes against configured git repositories. All three (plus a fourth, read-only,
diagnostic endpoint) are gated behind `require_permission("git.debug", "execute")` /
`require_permission("git.debug", "read")` in `routers/git/debug.py` — confirmed at the route-decorator
level for every endpoint in that file. **Accepted as-is**: the permission gate is correctly and
consistently applied; whether these debug endpoints should exist at all in a production build is a
product decision, not a code defect. The endpoints additionally sit behind `require_dev_tools`
(`core/dev_tools.py`, `ENABLE_DEV_TOOLS`), and the production guard refuses to start with
`ENABLE_DEV_TOOLS` set outside development.

## Credential encryption KDF salt is static

`core/crypto.py` derives the key for credentials-at-rest with PBKDF2-HMAC-SHA256 using a **static**,
domain-separated salt. A per-value random salt is the norm when the KDF input is a *user password*;
here the input is `CREDENTIAL_ENCRYPTION_KEY`, which must be a random value of at least 32 characters
(enforced at startup, with a denylist of repository defaults), so the KDF's role is key-stretching and
domain separation from `SECRET_KEY`, not defence against a dictionary attack. The iteration count
(`KDF_ITERATIONS`, floor 600 000) is stored in each value (`AMS2.<iterations>.<token>`), so changing the
setting does not break existing values. Passphrase-encrypted attributes use a random salt per value.
**Accepted as-is.**

## Local SSH keys are exported permanently

`CredentialsService.get_ssh_key_path` writes a `local`-backend `ssh_key` credential's decrypted
private key to a permanent file under `data/ssh_keys/` (mode 0600 in a 0700 directory), named
`<owner>_<credential id>`, and deletes it with the credential. Back the directory up like the
database. A `vault`-backend `ssh_key` credential does **not** have this exposure
(V2, 2026-09-12): it is written to an ephemeral file under `data/ssh_keys/tmp/` for the duration of
one git operation and discarded in a `finally` (see `doc/VAULT_INTEGRATION.md` "SSH keys"). The
asymmetry is deliberate, not an oversight: a `local` row's plaintext already lives in the same
Postgres database as the rest of the app on the same host, so a permanent on-disk export does not
change the storage guarantee the credential was given; a `vault` row's whole purpose is to *keep*
the plaintext out of this host except when actually in use, so it gets the stronger, ephemeral
treatment. **Accepted as-is**: making `local` keys ephemeral too is a larger change (every git
caller would need the same discard-in-`finally` discipline it already has for `vault` keys) and is
not required to close the OpenBao-specific gap V2 targeted.

## Batfish: raw device configurations are uploaded to the coordinator

`batfish-init-snapshot` writes every device's running-config (live mode) or
every matched file of a git repository (git mode) into a temp directory and
uploads it as a snapshot to the configured Batfish coordinator, which stores
it in its `/data` volume. Configs may contain enable secrets, SNMP
communities, or pre-shared keys if the collecting step did not scrub them.
**Accepted as-is**: this is the same trust boundary as the git-mirrored config
backups. The coordinator is unauthenticated plain HTTP, so it needs a private network (the shipped
compose gives it `manus-batfish`) — which is why
(a) `docker/batfish/docker-compose.yaml` binds its ports to `127.0.0.1` only,
and (b) a source's `host`/`port` must pass `validate_outbound_http_url`
(`services/batfish/source_config_service.py::_validate_target`), so a
`sources.batfish:write` holder cannot point the upload at an arbitrary host.
Ad-hoc query results (routing tables, ACL verdicts, extracted facts) are gated
by the separate `sources.batfish:query` permission, which the read-only
`viewer` role does not hold.

## Secret Manager connections send their own auth material to a configured URL

A Secret Manager connection's `credential_name` (AppRole `role_id`/`secret_id`)
is POSTed to the connection's `addr` on every login. **Mitigated, not accepted**: the URL must
pass `validate_outbound_http_url`, must be `https` with `verify_ssl=true`
outside development, the credential must be of type `generic` (an `ssh`
device credential is rejected). Anyone who may use a connection in a workflow can read and write
every path the connection's AppRole policy allows, and the AppRole secret is itself a `generic`
credential that workflow authors may use (see the author boundary in `SECURITY.md`); bound the damage
with the OpenBao policy. Creating or changing connections is admin-only (P3). See
`doc/SECRET_MANAGER_INTEGRATION.md` → "Transport policy".

## AI collaboration: the `ai-assistant` account

While an admin has activated the seeded `ai-assistant` user (Settings → Users), it is a
valid principal that can write workflow canvases, workflow notes and templates through
`backend/scripts/ai_workflow_apply.py` / `ai_template_apply.py`. **Mitigated, not
accepted**: the checks live in the services, not the scripts —
`WorkflowService.update_workflow_for_ai_session` / `update_notes_for_ai_session` call
`AiWriteGate` (caller must be the active `ai-assistant`, the workflow needs an unexpired
owner-granted `workflow_ai_sessions` row, and a canvas write is refused while the
workflow has an unattended trigger: an enabled schedule, the background tier, or being the deploy
workflow of an open change request); `AiTemplateService` confines the AI to templates whose name
carries the required `[AI Draft] ` prefix and that it created itself. The seeded role grants of the
account are not evaluated on this path and it has no usable password; leave it inactive unless you use
AI collaboration. Deactivating the account is the global kill-switch.
See `doc/ai_collaboration/PROCESS.md`.

## Hatchet dashboard and gRPC port

The shipped Hatchet file publishes the dashboard and the gRPC port on `127.0.0.1` only. A production
deployment exposes the dashboard through the operator's proxy, changes the admin password before
creating the API token, sets the secure cookie and cookie domain, and keeps gRPC on a private network.

## Internal links are plain HTTP

Hatchet gRPC, Postgres, Redis, the pyATS shim, Batfish and LiteLLM talk plain HTTP (or the native
protocol) on a Docker network. The compose files are examples with one network per concern
(`data`, `hatchet`, `ingress`, `egress` and one private network per optional stack); network isolation
is the operator's responsibility.

## Images are built by the operator

Images are built from the operator's own working tree. Build from a clean checkout: `.env` files are
excluded from the build context, other local files are not.

## Artifacts, results and run history may contain secrets

Artifacts, run results and run inputs may contain secrets and are readable by every holder of
`workflow_runs:read`. Only the Netmiko session log is scrubbed of secrets the run unwrapped
(`services/artifacts/scrub.py`). `command_output`, `running_config` and `startup_config` stay verbatim
on purpose: a configuration backup that replaced a deployed key with `***REDACTED***` could not be
restored. This is a deliberate narrowing of finding S3-05. Credential changes are logged as application log lines, not as an audit trail.
Logout (explicit) ends every session of the user; an idle timeout ends only the browser's cookie.

## Workflow authors hold the cleartext of global credentials

`workflows:write` + `workflows:execute` is equivalent to `credentials:reveal` for every global
credential of type `ssh`, `generic` and `shared_secret` (a workflow can change the device address a
step connects to, so the password can be sent to a host the author controls). Not reachable that way:
`token` and `ssh_key` credentials. A workflow author can also render any credential they can use into a
stored artifact; rendering a generated secret into a file is an operator choice. There is no allow- or
deny-list for device commands: such a user can run any exec or config command on every device of an
inventory, and data from Nautobot, CSV, git and run inputs is untrusted input to device command lines
(line breaks in rendered values are rejected unless a step allows them). Templates, report definitions,
global inventories and global credentials have no per-object owner check: whoever holds the write or
delete permission can change another user's item.

## Repository collaborators are trusted

Collaborators who can push to a repository that Manus clones are trusted. Symlinks in such a repository
are not followed by readers or writers (defence in depth); a `viewer` reads files inside a repository,
never outside it.

## AI data sharing is a per-user choice

Sharing device or run content with a third-party model is a per-user choice with best-effort
redaction. The redactor misses some vendor forms and bare values; values under 8 characters are never
tracked. The operator can switch the assistant off or limit providers and data classes
(`AI_ASSISTANT_ENABLED`, `AI_ALLOWED_PROVIDERS`, `AI_ALLOWED_DATA`); a user's own switches can only
narrow those limits.

## Route to Agent: what an agent sees, and the limits of its protocol

The step sends the attributes and content an author selects to an external agent. Messages are one
AES-256-GCM envelope keyed (HKDF, per direction) by a per-agent secret of at least 32 characters, so they are
confidential, authenticated and bound to the agent, command and direction. The step refuses secrets
(`SECRET_BAG_PATHS`, the config-context subtrees, parents that carry them, secret-looking path segments and
keys). **Accepted as-is**, all documented in `doc/AGENT_INTEGRATION.md`:

- The agent host and its handlers are trusted: they hold the secret and see everything that is sent. Handler
  exception messages (200 characters) are stored on the device and shown in the run view.
- Replay protection is in the agent's memory; a restart inside a request's validity window forgets it, so
  handlers must be idempotent. A persistent store was rejected because it would drop legitimately queued
  requests.
- Plain `http://` to an agent is allowed (the payload is encrypted); metadata such as agent id, sizes and timing
  is visible. Terminate TLS in front of an agent that is reachable from outside the Docker network.
- The agent URL is validated without DNS on the worker (like every source), see the next entry.
- A remote agent needs the app's Redis over a private network or VPN with TLS. The per-agent ACL user limits
  what a stolen agent host can touch (`manus-agent:<id>:*`, six commands); it is no substitute for network
  controls. `docker/redis/start.sh` writes the ACL file at every start because loading one resets the
  `default` user to `nopass`: a bare `--aclfile` would drop the password of the app's Redis.
- No secret rotation overlap yet: change the credential and the agent's `MANUS_AGENT_SECRET` together.

## DNS rebinding between the URL policy and the client

The URL policy resolves a host name and the client resolves it again; a name that answers differently
(DNS rebinding) can reach an internal address. Source, git repository and AI base URLs are
administrator-only settings. On a cloud VM the policy does not block the AWS IPv6 metadata address
`fd00:ec2::254` or `100.100.100.200`: restrict egress to metadata services at the network level.

## Refresh tokens are not single-use

A refresh token is not single-use: a stolen token can be refreshed in parallel with its owner until
logout or the 12 h session cap. Refresh is rate limited.
