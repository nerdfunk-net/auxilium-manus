# Docker Troubleshooting

## Build failures

### Proxy issues

If `apt-get` or `npm ci` fails behind a corporate proxy:

```bash
export HTTP_PROXY=http://proxy:8080
export HTTPS_PROXY=http://proxy:8080
export NO_PROXY=localhost,127.0.0.1
./docker/prepare-all-in-one.sh
```

Or use the helper:

```bash
./docker/build-with-proxy.sh
```

### Certificate errors (private CA)

Place `.crt` files in `docker/certs/` and rebuild with `Dockerfile.basic` or extend `Dockerfile.all-in-one`.

## Runtime failures

### `docker compose up` refuses to start (missing secret)

This is the normal, expected path — `docker-compose.yml` has no working
defaults for `SECRET_KEY`, `INITIAL_PASSWORD`, `CREDENTIAL_ENCRYPTION_KEY`,
`DATABASE_PASSWORD`, `MANUS_REDIS_PASSWORD`, or `HATCHET_CLIENT_TOKEN` on
purpose. Copy the template and fill it in:

```bash
cd docker
cp .env.example .env
# edit .env — SECRET_KEY and CREDENTIAL_ENCRYPTION_KEY: openssl rand -hex 32
docker compose up -d
```

For a local development stack (relaxed `ENV`, `/docs` enabled — secrets are
still required, just not the old hardcoded values):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

### Backend won't start outside Compose (`docker run` directly)

The same guards apply to a container started without Compose (`ENV=production`
requires non-default secrets, checked at startup in
`backend/core/production_guards.py`):

```bash
-e ENV=production \
-e SECRET_KEY=<at-least-32-chars, not the repo default> \
-e INITIAL_PASSWORD=<12+ chars, not "admin"> \
-e CREDENTIAL_ENCRYPTION_KEY=<different from SECRET_KEY> \
-e DATABASE_PASSWORD=<non-default> \
-e MANUS_REDIS_PASSWORD=<non-empty>
```

### Database connection refused

Verify PostgreSQL is reachable from the container and `DATABASE_HOST` points to the correct host (not `localhost` when Postgres runs in another container).

### Hatchet worker not processing workflows

1. Confirm Hatchet infrastructure is running (`docker compose up -d` from project root)
2. Create an API token at http://localhost:8888
3. Set `HATCHET_CLIENT_TOKEN` and `HATCHET_CLIENT_HOST_PORT` on the worker container
4. Check worker logs: `docker logs manus-worker`

### Frontend can't reach backend

Inside the container, the frontend proxy uses `BACKEND_URL=http://127.0.0.1:8000`. Do not change this unless you run backend on a different host inside the container.

## Health checks

```bash
curl http://localhost:8000/health          # Direct backend
curl http://localhost:3000/api/proxy/health  # Via frontend proxy
./docker/validate-all-in-one.sh
./docker/test-docker-deployment.sh
```

## Logs

```bash
docker logs -f auxilium-manus
docker logs -f manus-web
docker logs -f manus-worker
docker exec auxilium-manus cat /var/log/supervisor/frontend.err.log
```

## Clean rebuild

```bash
docker compose down -v
docker rmi auxilium-manus:all-in-one 2>/dev/null || true
./docker/prepare-all-in-one.sh
```
