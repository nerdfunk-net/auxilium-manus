# OpenBao setup for Auxilium Manus

OpenBao is **optional**. The app runs unchanged with `VAULT_ENABLED` unset — every
credential then stays Fernet-encrypted in PostgreSQL. Turn this on only if you want
per-credential secret storage in a vault. Full architecture + production runbook:
[`doc/VAULT_INTEGRATION.md`](../../doc/VAULT_INTEGRATION.md).

This guide gets a **local dev** vault running in the `openbao` container (dev mode,
in-memory, fixed root token) and configures the `manus` KV mount, the two policies,
and the two AppRoles the backend expects.

The CLI inside the container is `bao` (not `vault`). All `bao` commands below run
**inside the container**.

---

## 1. Start the container

```sh
cd docker/openbao
cp .env.example .env
# put a random value in OPENBAO_DEV_ROOT_TOKEN, e.g.:
#   openssl rand -hex 16
docker compose up -d
docker compose exec openbao bao status        # Sealed: false
```

If you run this repo's `docker/openbao` stack on its own (not alongside
`docker/docker-compose.yml`), create the shared network first:
`docker network create backend`.

---

## 2. Configure the vault

Open a shell in the container:

```sh
docker compose exec openbao sh
```

Then paste this whole block into that shell:

```sh
cd /tmp
export BAO_ADDR=http://127.0.0.1:8200
export BAO_TOKEN="$BAO_DEV_ROOT_TOKEN_ID"

# --- KV v2 secret engine mounted at manus/ ---------------------------------
bao secrets enable -path=manus -version=2 kv

# --- Runtime policy: read-only on the credential secrets -------------------
echo 'path "manus/data/credentials/*" { capabilities = ["read"] }' > manus-app.hcl
bao policy write manus-app manus-app.hcl

# --- Management policy: credential-manager writes -------------------------
echo 'path "manus/data/credentials/*"     { capabilities = ["create", "read", "update", "delete"] }'  > manus-manage.hcl
echo 'path "manus/delete/credentials/*"   { capabilities = ["update"] }'                             >> manus-manage.hcl
echo 'path "manus/metadata/credentials/*" { capabilities = ["read", "delete"] }'                     >> manus-manage.hcl
echo 'path "manus/destroy/credentials/*"  { capabilities = ["update"] }'                             >> manus-manage.hcl
bao policy write manus-manage manus-manage.hcl

# --- AppRole auth + the two roles ----------------------------------------
# Periodic tokens (token_period), unlimited SecretID uses so app restarts /
# redeploys never exhaust the SecretID.
bao auth enable approle
bao write auth/approle/role/manus-app \
  token_policies=manus-app    token_period=3600 secret_id_num_uses=0 secret_id_ttl=0
bao write auth/approle/role/manus-manage \
  token_policies=manus-manage token_period=3600 secret_id_num_uses=0 secret_id_ttl=0

# --- Print RoleIDs + freshly generated SecretIDs ------------------------
echo "VAULT_ROLE_ID=$(bao read -field=role_id auth/approle/role/manus-app/role-id)"
echo "VAULT_SECRET_ID=$(bao write -f -field=secret_id auth/approle/role/manus-app/secret-id)"
echo "VAULT_MANAGE_ROLE_ID=$(bao read -field=role_id auth/approle/role/manus-manage/role-id)"
echo "VAULT_MANAGE_SECRET_ID=$(bao write -f -field=secret_id auth/approle/role/manus-manage/secret-id)"

exit
```

Copy the four `VAULT_*` lines it prints — they go into `backend/.env`.

---

## 3. Point the backend at OpenBao

Edit `backend/.env`. Pick **one** auth method.

### Option A — AppRole (matches production)

```sh
VAULT_ENABLED=true
VAULT_ADDR=http://127.0.0.1:8200          # backend on host (python start.py)
# VAULT_ADDR=http://openbao:8200          # backend in a container on the `backend` network
VAULT_AUTH_METHOD=approle
VAULT_ROLE_ID=<from step 2>
VAULT_SECRET_ID=<from step 2>
VAULT_MANAGE_ROLE_ID=<from step 2>
VAULT_MANAGE_SECRET_ID=<from step 2>
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

Restart the backend and the Hatchet worker. The startup logs should show:

```
OpenBaoService manus-app started (addr=http://127.0.0.1:8200 mount=manus)
OpenBaoService manus-manage started (addr=http://127.0.0.1:8200 mount=manus)
```

---

## 4. Verify end to end

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

## Notes

- **Dev mode is in-memory.** Every `docker compose restart openbao` wipes the
  `manus` mount, the policies, and the AppRoles — re-run step 2. Switch to
  persistent (file storage) mode as described in `docker-compose.yaml` to keep
  them.
- **Production hardening** (not covered here): terminate TLS in front of OpenBao
  and use `https://` in `VAULT_ADDR`; add `token_bound_cidrs` /
  `secret_id_bound_cidrs` to both roles; deliver the SecretIDs via
  `VAULT_SECRET_ID_FILE` / `VAULT_MANAGE_SECRET_ID_FILE` (a mounted file / Docker
  secret) and rotate them ~90 days and on compromise. See the **Ops runbook** in
  [`doc/VAULT_INTEGRATION.md`](../../doc/VAULT_INTEGRATION.md).
