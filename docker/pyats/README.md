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
   curl -f http://localhost:8100/health
   curl -f http://localhost:8100/health/pyats
   ```

5. In the app, go to **Settings → Sources**, add a pyATS source. **Which URL
   to use depends on where the backend itself runs:**

   - **Backend running natively on the host** (the CLAUDE.md dev workflow —
     `python start.py` / `python scripts/run_worker_dev.py`, the common
     local setup — NOT itself in Docker):
     - URL: `http://localhost:8100` (the port published below)
     - The backend rejects loopback source URLs by default — set
       `ALLOW_LOOPBACK_SOURCE_URLS=true` in `backend/.env` for this
       local-lab case (see `backend/.env.example`), then restart the
       backend **and** the Hatchet worker.
   - **Backend also containerized** on the `backend` Docker network
     (`manus-web` / `manus-worker` from `docker/docker-compose.yml`):
     - URL: `http://pyats-shim:8100` (container DNS name)
   - Token (either case): the same value as `PYATS_SHIM_TOKEN`

   Click **Test connection** — it should report success along with the
   installed pyATS/Genie versions.

The published port is bound to `127.0.0.1` only (see `docker-compose.yml`) —
reachable from the same machine, not the LAN. Combined with the `backend`
Docker network (for a containerized backend), this keeps the same trust
boundary either way: only local processes on the app's own host can ever
reach the shim.

## Watching it work

Every `/v1/jobs` call and its underlying `pyats run job` subprocess are
logged at INFO:

```bash
docker logs -f pyats-shim
```

You should see, per workflow step call: `job request received operation=...
devices=[...]`, then `launching pyats run job ...`, then `pyats run job
finished exit_code=... elapsed=...s`, then `job request finished
operation=... success=N/M`. **If you see nothing at all** when running a
workflow, the request never reached the container — that's a connectivity
problem (wrong source URL, backend/worker running outside the network the
shim is reachable from, or the worker process not yet restarted after a
source URL change), not a pyATS/Genie problem. Check `docker ps` for the
container's healthy status and re-confirm the URL from **Quick start** step 5
above matches where your backend process actually runs.
