# Batfish (optional)

Runs [Batfish](https://github.com/batfish/batfish) — offline network config
analysis (routing tables, path/reachability tracing, ACL checks, BGP/OSPF
session validation) — in its own container via the official `batfish/allinone`
image. Optional — only needed for Batfish-backed workflow steps / a Batfish
source once those are implemented.

## Quick start

1. The app stack's `backend` network must exist already (created the first
   time `docker/docker-compose.yml` is brought up — see `docker/README.md`).
2. Optional: copy `.env.example` to `.env` to pin the image tag instead of
   floating on `latest`. Nothing needs to be set — the OSS coordinator has no
   auth token.
3. Start:

   ```bash
   cd docker/batfish
   docker compose up -d
   ```

4. Confirm it's healthy:

   ```bash
   docker compose ps     # STATUS should read "healthy" within ~30s
   ```

   `docker compose logs` will most likely stay empty — this image logs
   almost nothing at the default `-loglevel warn`, so that's not a sign
   anything is wrong. To actually confirm the process is up:

   ```bash
   docker compose exec batfish ps aux                                      # java process, no jupyter
   docker compose exec batfish bash -c 'exec 3<>/dev/tcp/localhost/9996'   # exit 0 = port open
   ```

   The upstream image normally also starts a bundled Jupyter notebook server
   on port 8888 (for interactive `pybatfish` tutorials); `command:` in
   `docker-compose.yaml` intentionally skips it — we talk to Batfish via
   `pybatfish` from backend code, not the notebook — so `ps aux` above
   should show only the `java` process, and there's no port 8888 to collide
   with the Hatchet dashboard.

5. Reachability depends on where the backend itself runs:
   - **Backend running natively on the host** (the CLAUDE.md dev workflow):
     `host=127.0.0.1`, ports `9996`/`9997` (published below).
   - **Backend also containerized** on the `backend` Docker network:
     `host=batfish`, ports `9996`/`9997` (container DNS name).

There is no HTTP endpoint to `curl` — Batfish's client protocol is
Java-RPC-like and only `pybatfish` (or the Batfish Java client) speaks it. The
backend integration will use `pybatfish`'s `Session` pointed at the host/ports
above.

The published ports are bound to `127.0.0.1` only, because the OSS coordinator
has **no authentication** — anyone who can reach 9996/9997 can create, read,
or delete any network/snapshot. Never publish these ports to the LAN.

## Storage

Snapshots and network metadata live in the `batfish_data` named volume
(`/data` inside the container, Batfish's `-storagebase`), so they survive
restarts. To wipe everything: `docker compose down -v`.
