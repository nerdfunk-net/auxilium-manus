# OpenBao setup for Auxilium Manus

OpenBao is **optional**. The app runs unchanged with `VAULT_ENABLED` unset — every
credential then stays Fernet-encrypted in PostgreSQL. Turn this on only if you want
a vault. Full architecture + production runbook:
[`doc/VAULT_INTEGRATION.md`](../../doc/VAULT_INTEGRATION.md).

There are **two independent consumers** of OpenBao. They use different mounts,
different policies and different AppRoles, and are configured in different places:

| | Credential vault | Secret Manager connection |
|---|---|---|
| Purpose | per-credential storage (`storage_backend=vault`) | workflow steps read/write/rotate secrets (e.g. TACACS) |
| Configured via | `VAULT_*` variables in `backend/.env` | a *Secret Manager connection* row in the UI + a global `generic` credential |
| KV mount | `manus` | `manus-network` (or whatever `backend_config.mount` says) |
| Policies | `manus-app` (read), `manus-manage` (write) | `manus-network-secrets` |
| AppRole(s) | `manus-app`, `manus-manage` | `manus-network` |
| Section | [2](#2-credential-vault-manus) + [3](#3-point-the-backend-at-openbao) | [4](#4-secret-manager-connection-manus-network) |

Do only the sections you need. A role can only do what its policies allow: logging
in successfully says nothing about whether it may read a given mount (see
[Debugging](#debugging)).

The CLI inside the container is `bao` (not `vault`). All `bao` commands below run
**inside the container**.

---

## 1. Start the container

`docker-compose.yaml` documents both modes in detail; the short version:

- **Dev mode (default)** — in-memory, auto-unsealed, fixed root token. Keep
  `./config` **unmounted**: the image always passes `-config=/openbao/config`, and
  a storage stanza collides with `-dev`.
- **Persistent mode** — follow "Persistent mode" in `docker-compose.yaml`, then
  `bao operator init` once and `bao operator unseal` (3 keys) after **every**
  restart. There is no `BAO_DEV_ROOT_TOKEN_ID` in this mode; use the root token
  printed by `init`.

```sh
cd docker/openbao
cp .env.example .env
# dev mode: put a random value in OPENBAO_DEV_ROOT_TOKEN, e.g. openssl rand -hex 16
docker compose up -d
docker compose exec openbao bao status        # Sealed: false
```

If you run this stack on its own (not alongside `docker/docker-compose.yml`),
create the shared network first: `docker network create backend`.

> **`./config` is parsed as server config.** In persistent mode the server loads
> `.hcl` / `.json` files in `/openbao/config` as *server* configuration. Policy
> files are not server config; keep them out of this directory (they may produce
> warnings or errors, and they get merged into the server's view of its config).
> This guide therefore feeds policies to `bao policy write`
> over stdin and needs no policy files at all. Keep `./config` for the single
> server config file only.

Open a shell in the container for the next steps. In **dev mode** the root token is
in `$BAO_DEV_ROOT_TOKEN_ID`; in **persistent mode** export the root token from
`bao operator init` yourself.

```sh
docker compose exec openbao sh

export BAO_ADDR=http://127.0.0.1:8200
export BAO_TOKEN="$BAO_DEV_ROOT_TOKEN_ID"      # persistent mode: the init root token
bao auth enable approle                         # once, shared by sections 2 and 4
```

---

## 2. Credential vault (`manus`)

Paste inside the container shell:

```sh
# --- KV v2 secret engine mounted at manus/ ---------------------------------
bao secrets enable -path=manus -version=2 kv

# --- Runtime policy: read-only on the credential secrets -------------------
bao policy write manus-app - <<'EOF'
path "manus/data/credentials/*" { capabilities = ["read"] }
EOF

# --- Management policy: credential-manager writes --------------------------
bao policy write manus-manage - <<'EOF'
path "manus/data/credentials/*"     { capabilities = ["create", "read", "update", "delete"] }
path "manus/delete/credentials/*"   { capabilities = ["update"] }
path "manus/metadata/credentials/*" { capabilities = ["read", "delete"] }
path "manus/destroy/credentials/*"  { capabilities = ["update"] }
EOF

# --- The two roles ---------------------------------------------------------
# Periodic tokens (token_period), unlimited SecretID uses so app restarts /
# redeploys never exhaust the SecretID.
bao write auth/approle/role/manus-app \
  token_policies=manus-app    token_period=3600 secret_id_num_uses=0 secret_id_ttl=0
bao write auth/approle/role/manus-manage \
  token_policies=manus-manage token_period=3600 secret_id_num_uses=0 secret_id_ttl=0

# --- Print RoleIDs + freshly generated SecretIDs ---------------------------
echo "VAULT_ROLE_ID=$(bao read -field=role_id auth/approle/role/manus-app/role-id)"
echo "VAULT_SECRET_ID=$(bao write -f -field=secret_id auth/approle/role/manus-app/secret-id)"
echo "VAULT_MANAGE_ROLE_ID=$(bao read -field=role_id auth/approle/role/manus-manage/role-id)"
echo "VAULT_MANAGE_SECRET_ID=$(bao write -f -field=secret_id auth/approle/role/manus-manage/secret-id)"
```

Copy the four `VAULT_*` lines — they go into `backend/.env` (section 3).

---

## 3. Point the backend at OpenBao

Edit `backend/.env`. Pick **one** auth method.

### Option A — AppRole (matches production)

```sh
VAULT_ENABLED=true
VAULT_ADDR=http://127.0.0.1:8200          # backend on host (python start.py)
# VAULT_ADDR=http://openbao:8200          # backend in a container on the `backend` network
VAULT_AUTH_METHOD=approle
VAULT_ROLE_ID=<from section 2>
VAULT_SECRET_ID=<from section 2>
VAULT_MANAGE_ROLE_ID=<from section 2>
VAULT_MANAGE_SECRET_ID=<from section 2>
```

### Option B — root token (fastest, dev only)

```sh
VAULT_ENABLED=true
VAULT_ADDR=http://127.0.0.1:8200
VAULT_AUTH_METHOD=token
VAULT_TOKEN=<the OPENBAO_DEV_ROOT_TOKEN from .env>
VAULT_MANAGE_TOKEN=<the OPENBAO_DEV_ROOT_TOKEN from .env>
```

`ENV=development` is required for Option B and for a plain `http://` address — the
production guards reject token auth and non-HTTPS otherwise.

These variables are read **once at process start**. After any change, restart the
backend **and every Hatchet worker** (`hatchet.worker` and `hatchet.dynamic_worker`).
The startup logs should show:

```
OpenBaoService manus-app started (addr=http://127.0.0.1:8200 mount=manus)
OpenBaoService manus-manage started (addr=http://127.0.0.1:8200 mount=manus)
```

### Verify end to end

```sh
docker compose exec openbao sh -c 'BAO_TOKEN=$BAO_DEV_ROOT_TOKEN_ID bao kv list manus/credentials'
```

That errors with "No value found" until you create a vault-backed credential — do
that in the app:

**Settings → Credential vault → Add credential → Storage backend: OpenBao vault.**

Then the secret is in the vault:

```sh
docker compose exec openbao sh -c 'BAO_TOKEN=$BAO_DEV_ROOT_TOKEN_ID bao kv get manus/credentials/<name>-<id>'
```

and the PostgreSQL row holds only the pointer (`vault_path`), not the secret.

Stop OpenBao (`docker compose stop openbao`) and re-run a workflow step that uses a
vault credential — it fails loudly; a `local` credential in the same run still
works. Start it again and retry — green.

---

## 4. Secret Manager connection (`manus-network`)

Used by workflow steps that read, write or rotate secrets in an external secret
manager. Unlike section 3 this needs **no `.env` change**: the connection and its
AppRole credentials live in the app.

Inside the container shell:

```sh
# --- Separate KV v2 mount for network secrets ------------------------------
bao secrets enable -path=manus-network -version=2 kv

# --- Policy ----------------------------------------------------------------
# Add "delete" here (and "delete"/"update" on manus-network/metadata/* and
# manus-network/destroy/*) only if your steps remove fields or versions.
bao policy write manus-network-secrets - <<'EOF'
path "manus-network/data/*"     { capabilities = ["create", "read", "update"] }
path "manus-network/metadata/*" { capabilities = ["read"] }
EOF

# --- Role ------------------------------------------------------------------
bao write auth/approle/role/manus-network \
  token_policies=manus-network-secrets token_period=3600 \
  secret_id_num_uses=0 secret_id_ttl=0

echo "role_id:   $(bao read -field=role_id auth/approle/role/manus-network/role-id)"
echo "secret_id: $(bao write -f -field=secret_id auth/approle/role/manus-network/secret-id)"
```

Then in the app:

1. Create a **global** credential of type **`generic`** — `username` = the role_id,
   `password` = the secret_id. Other credential types and private credentials are
   rejected for this purpose.
2. Create a Secret Manager connection: backend `openbao`, the address
   (`http://openbao:8200` from a container, `http://127.0.0.1:8200` from the host),
   `backend_config.mount` = `manus-network`, and select that credential.
3. Click **Test**. A green result proves **only that the AppRole login worked.** It
   does not prove the role may read the mount.

### Rotating the role_id / secret_id

1. `bao write -f -field=secret_id auth/approle/role/manus-network/secret-id`
2. Overwrite the credential's username/password in the app.
3. **Restart every Hatchet worker.** Each process caches its own OpenBao client and
   token per connection, keyed on the *connection row's* `updated_at`. Editing the
   credential does not change that row, and **Test** only refreshes the API
   process, so workers keep using the old login until restarted (or until the
   connection itself is saved).

---

## Debugging

Unsealed (`bao status`) and "Connected" (the app's **Test** button) only prove the
server is up and that an AppRole login worked. Neither proves the role may read the
mount you care about. Work through the steps below in order; each narrows the
problem down.

### Step 1 — What exists? (inside the container, root token)

```sh
export BAO_ADDR=http://127.0.0.1:8200
export BAO_TOKEN=<root token>

bao status                                  # Sealed: false
bao secrets list                            # mounts: manus/ and/or manus-network/, type kv, v2
bao auth list                               # approle/ must be listed
bao policy list                             # manus-app, manus-manage, manus-network-secrets
bao list auth/approle/role                  # the roles that exist
bao policy read manus-network-secrets       # what a policy actually allows
bao read auth/approle/role/manus-network    # token_policies, token_period, secret_id_num_uses
bao read -field=role_id auth/approle/role/manus-network/role-id
```

"No value found at …" means the thing does not exist yet — create it from the
matching section above. To find which role a role_id belongs to, print each role's
id and compare:

```sh
for r in $(bao list -format=json auth/approle/role | jq -r '.[]'); do
  echo "$r  $(bao read -field=role_id auth/approle/role/$r/role-id)"
done
```

### Step 2 — Log in and inspect the token (from the host, with curl)

This is exactly what the app does. Port 8200 is published on `127.0.0.1`.

```sh
export BAO=http://127.0.0.1:8200
ROLE_ID=<role_id>
SECRET_ID=<secret_id>

# Login. `policies` shows what the token can do.
curl -s -X POST $BAO/v1/auth/approle/login \
  -d "{\"role_id\":\"$ROLE_ID\",\"secret_id\":\"$SECRET_ID\"}" \
  | jq '{policies: .auth.policies, ttl: .auth.lease_duration, renewable: .auth.renewable}'

# Keep the token for the next calls
TOKEN=$(curl -s -X POST $BAO/v1/auth/approle/login \
  -d "{\"role_id\":\"$ROLE_ID\",\"secret_id\":\"$SECRET_ID\"}" | jq -r .auth.client_token)

# Policies and period of the token
curl -s -H "X-Vault-Token: $TOKEN" $BAO/v1/auth/token/lookup-self | jq '.data | {policies, period, ttl}'
```

### Step 3 — What may this token do on a path?

```sh
curl -s -H "X-Vault-Token: $TOKEN" -X POST $BAO/v1/sys/capabilities-self \
  -d '{"paths":["manus-network/data/test/foo","manus-network/metadata/test/foo"]}' | jq '.data'
```

`["deny"]` means the policy does not cover that path — this is the cause of a 403.
For the `manus-network` role you expect `["create","read","update"]` on `…/data/…`.

### Step 4 — Read and write a test secret

KV v2 API paths contain a `/data/` segment that the `bao kv` CLI hides.

```sh
curl -s -H "X-Vault-Token: $TOKEN" -X POST $BAO/v1/manus-network/data/test/foo \
  -d '{"data":{"password":"hello"}}' | jq
curl -s -H "X-Vault-Token: $TOKEN" $BAO/v1/manus-network/data/test/foo | jq '.data.data'
```

Or with the CLI inside the container:

```sh
TOKEN=$(bao write -field=token auth/approle/login role_id=<id> secret_id=<secret>)
BAO_TOKEN=$TOKEN bao kv put -mount=manus-network test/foo password=hello
BAO_TOKEN=$TOKEN bao kv get -mount=manus-network test/foo
```

### Reading the results

| What you see | Meaning | Fix |
|---|---|---|
| Login: `invalid role or secret ID` (400) | wrong role_id or secret_id, or the secret_id belongs to another role | Step 1 to find the right role; generate a new secret_id for it |
| Login works, `policies` lacks the expected policy | the role is not bound to it, or the role_id belongs to a different role (e.g. `manus-app` instead of `manus-network`) | `bao write auth/approle/role/<role> token_policies=<policy> token_period=3600 secret_id_num_uses=0 secret_id_ttl=0` |
| Capabilities `["deny"]` | policy path does not match the mount/path being read | `bao policy read <policy>`; fix the path, re-write the policy |
| 403 `permission denied` on read/write | same as above | same |
| 404 on read | authorised, but nothing stored at that path | write the secret, or check the path/mount in the connection config |
| `no handler for route` / mount not found | the KV mount does not exist | `bao secrets enable -path=<mount> -version=2 kv` |
| 5xx / connection refused | server down or sealed | `docker compose logs openbao`; `bao operator unseal` |

### Checklist: "Connected" but the workflow gets 403

1. The connection's credential holds the role_id of the **right role** (Step 1, role_id
   comparison) and a **current** secret_id (Step 2 login succeeds with those exact values).
2. The login's `policies` include the policy that covers the path (Step 2).
3. Capabilities on the path the workflow reads are not `deny` (Step 3). The mount and
   path must match the connection's `backend_config.mount` and the step's path.
4. A manual read with that token works (Step 4).
5. **Restart every Hatchet worker** (`hatchet.worker` and `hatchet.dynamic_worker`).
   Workers cache the client and token per connection, and **Test** refreshes only the
   API process. Editing the credential does not change the connection row, so
   workers keep the old login until restarted.

If steps 1–4 pass and the workflow still fails, the cause is on the app side, not in
OpenBao: look at the worker log for the exact path and connection it used.

> Anything you paste into a chat, ticket or log (role_id, secret_id, tokens) should be
> treated as exposed — generate a new secret_id afterwards.

---

## Notes

- **Dev mode is in-memory.** Every `docker compose restart openbao` wipes the
  mounts, policies and AppRoles — re-run sections 2 and/or 4 and issue **new**
  role/secret IDs. Use persistent mode to keep them.
- **Persistent mode starts sealed** after every restart — `bao operator unseal`.
- **Production hardening** (not covered here): terminate TLS in front of OpenBao
  and use `https://` in `VAULT_ADDR`; add `token_bound_cidrs` /
  `secret_id_bound_cidrs` to the roles; deliver the SecretIDs via
  `VAULT_SECRET_ID_FILE` / `VAULT_MANAGE_SECRET_ID_FILE` (a mounted file / Docker
  secret) and rotate them ~90 days and on compromise. See the **Ops runbook** in
  [`doc/VAULT_INTEGRATION.md`](../../doc/VAULT_INTEGRATION.md).
