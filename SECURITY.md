# Security Policy

## Reporting a vulnerability

Please do not open a public issue. Report privately through GitHub's "Report a vulnerability"
button (Security → Advisories → Report a vulnerability) on this repository. Include the affected
version/commit, steps to reproduce and the impact. You will get an acknowledgement within 5 working
days.

## Supported versions

Only the latest commit on `main` is supported; fixes are not back-ported.

## Trust model

Auxilium Manus is built for teams that trust their users. A user with `workflows:write` and
`workflows:execute` is equivalent to a user with `credentials:reveal` for every global credential of
type `ssh`, `generic` and `shared_secret`, and can run arbitrary commands on every device of an
inventory with those credentials. Source tokens, git tokens and SSH keys are not reachable that way.
Collaborators who can push to a repository that Manus clones are trusted; a `viewer` can read files
inside a repository, never outside it. Grant `workflows:write` and `workflows:execute` as you would
grant device access. People who can write templates (`templates:write`) are trusted at the worker level too:
`render-jinja-template` runs their template in a sandbox on the worker and the render is not bounded in time
or memory (the AI assistant's renders are isolated, see `doc/OPEN_TODOS.md`).

## What you must provide

- TLS in front of port 3000. The session cookie is `Secure`; without TLS login only works on
  `localhost`.
- A reverse proxy that sets or appends `X-Forwarded-For`, does not trust arbitrary client addresses,
  limits request bodies and does not buffer `/api/proxy/ai/chat` (server-sent events). See
  [`docker/DOCKER.md`](docker/DOCKER.md), "Reverse proxy".
- No published backend port. The shipped compose publishes 3000 on loopback only and never 8000.
- `ENV=production` (the default) and every secret from `docker/.env.example`, at the documented
  length. The application starts only with them.
- A private network for each optional service (Hatchet, pyATS shim, Batfish, OpenBao, LiteLLM,
  Mattermost): their internal links are plain HTTP and the compose files are examples.
- A changed Hatchet admin password and no published Hatchet dashboard or gRPC port.
- A clean checkout for image builds (`.env` files are excluded, other local files are not).

## Accepted risks

Netmiko and git-over-ssh do not verify device host keys (Netmiko accepts every key, git trusts on
first use); telnet device types are accepted; data from Nautobot, CSV, git and run inputs is
untrusted input to device command lines (line breaks and every other line separator that
`str.splitlines()` knows — VT, FF, FS/GS/RS, NEL, LS, PS — in rendered values are rejected unless a
step allows them); the credential store derives its key with a static salt from
`CREDENTIAL_ENCRYPTION_KEY`, which must be a random value of at least 32 characters (enforced at
startup); local SSH keys are stored as files under `data/ssh_keys/`; Batfish receives raw device
configurations over unauthenticated HTTP; artifacts, run results and run history may contain secrets
and are readable by everyone with `workflow_runs:read`; there is no audit log of credential changes
beyond application log lines; logout ends every session of the user (an idle timeout ends only the
browser's cookie); DNS names are resolved once by the URL policy and again by the client
(administrator-set source and repository URLs only); refresh tokens are not single-use; templates,
report definitions, global inventories and global credentials have no per-object owner check:
whoever holds the write or delete permission can change another user's item.

## Rotating `CREDENTIAL_ENCRYPTION_KEY`

There is no rotation or re-encryption tool. The key encrypts the secrets stored in the database:
local credentials (passwords, SSH keys, passphrases), git webhook secrets, users' AI assistant API
keys, and sealed values in run results. A different key makes all of them undecryptable; the
application does not fall back to the old key. Credentials kept in OpenBao are not affected.

After a suspected key leak, or to change the key on purpose:

1. Put the new `CREDENTIAL_ENCRYPTION_KEY` (`openssl rand -hex 32`, different from `SECRET_KEY`) in
   `docker/.env` and restart the web and worker containers.
2. Enter every local credential, git webhook secret and AI assistant key again. Delete or re-save
   them; the old ciphertext stays in the database until you do. Sealed values in earlier run results
   stay unreadable; run the workflows again if you need them.
3. Rotate the secrets themselves (device passwords, SSH keys, tokens) as well: whoever held the old
   key can decrypt any copy of the database or a backup made before the change.

Keep the key with every backup of the database (see "Backup and restore" in
[`docker/README.md`](docker/README.md)): a restore without the matching key restores unreadable
credentials.

## AI features

The assistant is off unless an operator enables it (`AI_ASSISTANT_ENABLED`, `AI_ALLOWED_PROVIDERS`,
`AI_ALLOWED_DATA`) and a user adds a key. What a user shares with a third-party model is their
choice and is redacted on a best-effort basis; the redactor misses some vendor forms and values
under 8 characters are never tracked. The `ai-assistant` account must stay inactive unless you use
AI collaboration; its role grants are not evaluated on the AI write path.

Details and reasoning: [`doc/SECURITY-NOTES.md`](doc/SECURITY-NOTES.md).
