# Security Notes — Accepted Risks

This file records security-adjacent findings from `doc/FABLE-ANALYSIS.md` §4.7 that were reviewed and
intentionally left as-is, with the reasoning, so they aren't re-investigated from scratch later.

## `verify_ssl=False` support (Nautobot, ISE clients)

`services/nautobot/client.py` and `services/ise/client.py` each keep a second, non-verifying
`httpx.AsyncClient` pool because on-prem Nautobot/ISE instances in NetDevOps environments commonly
present self-signed certificates. Every request made with `verify_ssl=False` is logged at `WARNING`
with the target host (`graphql_query`, `rest_request` in the Nautobot client; `ers_request` in the ISE
client — all three call sites confirmed present). **Accepted as-is**: there is currently no UI/RBAC gate
specifically preventing `verify_ssl=False` sources in a production configuration; adding one is worth
doing if this product is ever deployed against untrusted/adversarial networks rather than a managed
internal one.

## Netmiko: no SSH host-key verification

`services/network/netmiko/connection.py` builds `ConnectHandler(**device_params)` with no host-key
checking parameters; Netmiko's default behavior auto-accepts unknown host keys (equivalent to
`StrictHostKeyChecking=no`). **Accepted as-is**: standard practice for NetDevOps automation tooling
targeting a known device inventory, but worth stating explicitly here since it's a real MITM exposure if
the management network is ever untrusted. The template-editor preview endpoints
(`/netmiko/run-commands`, `/netmiko/get-configs`) deny SSH to arbitrary hosts outside development
unless `ALLOW_NETMIKO_ARBITRARY_HOSTS=true` (`core/safe_hosts.py`); this host-key-checking gap remains
accepted for whatever host the preview (or a workflow run) is allowed to reach.

## Git credentials visible in process argv

`services/sources/git/git_source_service.py` embeds HTTP basic-auth credentials into the remote URL
(`_build_auth_url`) and passes that URL directly in the `git clone`/`git push` argv
(`subprocess.run(cmd, ...)`), which is visible to other local users via `ps` on a shared host for the
duration of the subprocess call. Output (`stdout`/`stderr`) is correctly redacted before being returned
to the client or logged (`_redact_secrets`, called at both call sites) — only the argv-visibility window
is unaddressed. **Accepted as-is** for now; `GIT_ASKPASS` or a git credential-helper would close this
window if it's ever prioritized, since neither exposes the secret via argv.

## pyATS shim: device credentials over plain HTTP

`backend/services/pyats/client.py` sends device SSH credentials to the
`pyats-shim` container in the `POST /v1/jobs` request body over plain HTTP
(no TLS). **Accepted as-is**: the shim publishes no host port and is only
reachable from other containers on the internal `backend` Docker network
(`manus-web`/`manus-worker`), the same trust boundary already relied on for
`postgres`/`redis`. If the shim is ever exposed outside that network (a
published host port, a different/wider Docker network, a remote deployment),
this must move to HTTPS or an equivalent transport fix first — see
`doc/PYATS_INTEGRATION.md` for the full design.

## Git debug write endpoints (`test_write`/`test_delete`/`test_push`)

`services/git/debug_service.py`'s `test_write`, `test_delete`, and `test_push` perform real filesystem
writes and real pushes against configured git repositories. All three (plus a fourth, read-only,
diagnostic endpoint) are gated behind `require_permission("git.debug", "execute")` /
`require_permission("git.debug", "read")` in `routers/git/debug.py` — confirmed at the route-decorator
level for every endpoint in that file. **Accepted as-is**: the permission gate is correctly and
consistently applied; whether these debug endpoints should exist at all in a production build is a
product decision, not a code defect, and is out of scope for this plan.

## Credential encryption KDF salt is static

`core/crypto.py` derives the Fernet key for credentials-at-rest with PBKDF2-HMAC-SHA256 using a
**static** salt (`_KDF_SALT = b"auxilium-credential-encryption-v1"`). A per-value random salt is the
norm when the KDF input is a *user password*; here the input is `CREDENTIAL_ENCRYPTION_KEY` (or
`SECRET_KEY`), a high-entropy random value, so the KDF's role is key-stretching and domain separation
from `SECRET_KEY`, not defence against a low-entropy dictionary attack — a static salt is adequate for
that. The iteration count is `KDF_ITERATIONS` (default and enforced floor 100 000), read via
`Settings`, and the derived key is cached per process so PBKDF2 runs once rather than per credentials
request. **Accepted as-is**: rotating the salt would invalidate every stored ciphertext, so a salt
change must be treated as a deliberate migration that re-encrypts the `credentials` table, not a
config tweak.
