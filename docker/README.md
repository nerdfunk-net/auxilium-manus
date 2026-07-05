# Auxilium Manus Docker Deployment

Docker files for building and deploying Auxilium Manus in development and air-gapped production environments.

## Quick Start

### Development (with internet)

```bash
# Start Hatchet infrastructure from project root
docker compose up -d

# Start application stack
cd docker
cp .env.example .env   # edit HATCHET_CLIENT_TOKEN and secrets
./start-docker.sh
```

Access:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- Hatchet dashboard: http://localhost:8888

### Air-gap production

```bash
# On an internet-connected machine (from project root)
./docker/prepare-all-in-one.sh

# Transfer docker/airgap-artifacts/auxilium-manus-all-in-one.tar.gz
# On the air-gapped machine
./docker/deploy-all-in-one.sh
./docker/validate-all-in-one.sh
```

See [README-ALL-IN-ONE.md](./README-ALL-IN-ONE.md) for the full air-gap guide.

## Files

| File | Purpose |
|---|---|
| `Dockerfile.all-in-one` | Self-contained production image (air-gap) |
| `Dockerfile.basic` | Faster online development build |
| `Dockerfile.worker` | Standalone Hatchet worker (optional) |
| `docker-compose.yml` | App stack: postgres, redis, web, worker |
| `prepare-all-in-one.sh` | Build and export air-gap image |
| `deploy-all-in-one.sh` | Load and run image in air-gap environment |
| `validate-all-in-one.sh` | Post-deployment health checks |
| `build-with-proxy.sh` | Build with proxy env vars |
| `run-with-proxy.sh` | Run container with proxy env vars |

## Proxy support

Build scripts detect proxy environment variables automatically:

```bash
export HTTP_PROXY=http://proxy.company.com:8080
export HTTPS_PROXY=http://proxy.company.com:8080
export NO_PROXY=localhost,127.0.0.1,.local

./docker/prepare-all-in-one.sh
```

## Production ports

| Service | Port |
|---|---|
| Frontend | 3000 |
| Backend API | 8000 |

## Runtime dependencies

The all-in-one image bundles the application (frontend + backend). These services must still be available at runtime:

- **PostgreSQL** — application database
- **Redis** — device cache
- **Hatchet** — workflow orchestration (start via root `docker compose up -d`)

Pass connection settings via environment variables or mount a `.env` file. See `.env.example`.

## Troubleshooting

See [DOCKER.md](./DOCKER.md).
