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

For the `docker compose` / all-in-one stack, drop `.crt` files in repo-root
`config/certs/` and set `INSTALL_CERTIFICATE_FILES=true` in `docker/.env` — that
directory is bind-mounted into every service (`../config:/app/config`) and
installed at container startup, no rebuild needed. `docker/certs/` is only for
a build-time `Dockerfile.basic` image (baked into the image at `docker build`
time, not bind-mounted); it does nothing for `Dockerfile.all-in-one`.

`docker/start.sh` installs the certs as root before dropping to the
unprivileged `manus` user; the app then logs "N certificate(s) already
installed, nothing to do" rather than re-copying them.

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

## Client IP and login rate limiting

`POST /auth/login` is rate-limited on two independent dimensions of *failed*
attempts (see `doc/analysis/FABLE_BACKEND_20260912.md` §4.2 T1 and
`doc/plans/FABLE_20260912.md` §1): 20 failures/60s per client IP, and 100
failures/15min per username (a successful login clears the username bucket
only). The client IP comes from `backend/core/client_ip.py::resolve_client_host`:
it trusts `X-Forwarded-For` only when the direct peer is inside
`TRUSTED_PROXY_IPS` (IPs or CIDRs), and picks the **rightmost** entry that is
not itself a trusted proxy.

`TRUSTED_PROXY_IPS` is **required outside development** — `production_guards`
refuses to start without it, because an empty list makes every request look
like it comes from the proxy and the per-IP dimension collapses to one shared
bucket. The all-in-one image runs Next.js and the backend in one container, so
compose defaults it to `127.0.0.1`.

If you put a reverse proxy (nginx, Traefik, a cloud load balancer) in front of
the Next.js server, it must **set or append** `X-Forwarded-For` itself — do not
just pass through what the browser sent:

```nginx
# nginx
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

Traefik does this by default. Add the ingress's address (or the subnet it
connects from) to `TRUSTED_PROXY_IPS` alongside the Next.js host/CIDR, so the
backend walks past both trusted hops and lands on the real client address.
Without such an ingress, a browser can supply its own `X-Forwarded-For` value
(Next.js only fills it in when the browser didn't) — the per-IP budget is then
best-effort, and the per-username budget is the control that cannot be spoofed.

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
