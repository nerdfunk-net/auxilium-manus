# Auxilium Manus All-in-One Air-Gap Deployment

Deploy Auxilium Manus in an air-gapped environment using a single self-contained Docker image.

## Overview

The all-in-one image contains:

- Built Next.js frontend (production)
- FastAPI backend with all Python dependencies (wheelhouse)
- System packages (Node.js, supervisor, git, etc.)

Runtime dependencies (PostgreSQL, Redis, Hatchet) are **not** embedded — provide them separately in your air-gap environment.

## Phase 1: Build (internet-connected machine)

```bash
cd /path/to/auxilium-manus
./docker/prepare-all-in-one.sh
```

Output: `docker/airgap-artifacts/auxilium-manus-all-in-one.tar.gz`

### Proxy configuration

The build script automatically forwards these variables as Docker build args:

- `HTTP_PROXY`
- `HTTPS_PROXY`
- `NO_PROXY`

```bash
export HTTPS_PROXY=http://proxy.company.com:8080
./docker/prepare-all-in-one.sh
```

## Phase 2: Transfer

Copy `auxilium-manus-all-in-one.tar.gz` to the air-gapped environment via approved media.

## Phase 3: Deploy (air-gapped machine)

```bash
./docker/deploy-all-in-one.sh
./docker/validate-all-in-one.sh
```

Or manually:

```bash
gunzip auxilium-manus-all-in-one.tar.gz
docker load -i auxilium-manus-all-in-one.tar

docker run -d \
  --name auxilium-manus \
  --restart unless-stopped \
  -p 3000:3000 \
  -p 8000:8000 \
  -v auxilium-manus-data:/app/data \
  -e ENV=production \
  -e SECRET_KEY=<secure-random-key> \
  -e INITIAL_PASSWORD=<secure-password> \
  -e DATABASE_HOST=<postgres-host> \
  -e DATABASE_PASSWORD=<postgres-password> \
  -e MANUS_REDIS_HOST=<redis-host> \
  -e MANUS_REDIS_PASSWORD=<redis-password> \
  -e HATCHET_CLIENT_TOKEN=<hatchet-token> \
  -e HATCHET_CLIENT_HOST_PORT=<hatchet-host>:7077 \
  auxilium-manus:all-in-one
```

## Access URLs

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| Health check | http://localhost:8000/health |
| API docs (if enabled) | http://localhost:8000/docs |

## Hatchet workers

The image includes configuration for **two** Hatchet worker processes, each
run as its own container from the same image — see
`doc/ARCHITECTURAL_OVERVIEW.md` → "Background-tier workflows" for what the
split is for. The live worker (`supervisord-worker.conf`) handles every
workflow by default:

```bash
docker run -d \
  --name auxilium-manus-worker \
  -v auxilium-manus-data:/app/data \
  -e SUPERVISORD_CONF=/etc/supervisor/conf.d/supervisord-worker.conf \
  -e HATCHET_CLIENT_TOKEN=<token> \
  -e HATCHET_CLIENT_HOST_PORT=<hatchet-host>:7077 \
  -e DATABASE_HOST=<postgres-host> \
  auxilium-manus:all-in-one \
  /app/start.sh
```

The background worker (`supervisord-background-worker.conf`) only handles
workflows explicitly published to the background tier — run it as a second,
separate container with the same environment:

```bash
docker run -d \
  --name auxilium-manus-background-worker \
  -v auxilium-manus-data:/app/data \
  -e SUPERVISORD_CONF=/etc/supervisor/conf.d/supervisord-background-worker.conf \
  -e HATCHET_CLIENT_TOKEN=<token> \
  -e HATCHET_CLIENT_HOST_PORT=<hatchet-host>:7077 \
  -e DATABASE_HOST=<postgres-host> \
  auxilium-manus:all-in-one \
  /app/start.sh
```

Run both containers — the background worker is required alongside the live
worker (`docker-compose.yml` starts both unconditionally for exactly this
reason). It only executes workflows explicitly published to the background
tier, but needs to be up for that to work whenever you use it.

## Useful commands

```bash
docker logs -f auxilium-manus
docker exec -it auxilium-manus /bin/bash
docker restart auxilium-manus
docker stop auxilium-manus
```

## Backup data volume

```bash
docker run --rm \
  -v auxilium-manus-data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/manus-backup.tar.gz /data
```
