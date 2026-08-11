# pyATS Shim (optional)

Runs Cisco pyATS/Genie in its own container behind a thin HTTP shim
(`/pyats-shim` at the repo root). Optional — only needed if you're using
pyATS-backed workflow steps or want to register a pyATS source under
Settings → Sources.

Full design: `doc/PYATS_INTEGRATION.md` at the repo root.

## Quick start

1. The app stack's `backend` network must exist already (it's created the
   first time `docker/docker-compose.yml` is brought up — see `docker/README.md`).
2. Copy `.env.example` to `.env` and set `PYATS_SHIM_TOKEN` to a random
   secret (this is the value you'll paste into the pyATS source's token
   field later):

   ```bash
   cd docker/pyats
   cp .env.example .env
   # edit .env, e.g.: echo "PYATS_SHIM_TOKEN=$(openssl rand -hex 32)" > .env
   ```
3. Build and start:

   ```bash
   docker compose up -d --build
   ```

4. Confirm it's healthy:

   ```bash
   docker exec pyats-shim curl -f http://localhost:8100/health
   docker exec pyats-shim curl -f http://localhost:8100/health/pyats
   ```

5. In the app, go to **Settings → Sources**, add a pyATS source:
   - URL: `http://pyats-shim:8100` (container DNS name on the `backend` network)
   - Token: the same value as `PYATS_SHIM_TOKEN`

   Click **Test connection** — it should report success along with the
   installed pyATS/Genie versions.

No host port is published; `pyats-shim` is only reachable from other
containers on the `backend` network (`manus-web` / `manus-worker`), the same
trust model already used for `postgres`/`redis`.
