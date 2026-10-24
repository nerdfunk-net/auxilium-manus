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
installed at container startup, no rebuild needed.

If the **build** fails (pip, npm, git behind a TLS-inspecting proxy), put the company root
certificates in `docker/certs/` (PEM text, `*.crt` or `*.pem`, any number) and rebuild. They are
used at `docker build` time by `Dockerfile.all-in-one` and `Dockerfile.basic`: trusted for `apt`,
`pip` and the frontend build (`NODE_EXTRA_CA_CERTS`, added to Node's built-in roots). With no
certificates nothing changes.
This combines freely with `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` (`prepare-all-in-one.sh`
and `build-with-proxy.sh` forward them as build args), e.g.:

```bash
HTTPS_PROXY=http://proxy.corp:3128 ./docker/prepare-all-in-one.sh   # certs in docker/certs are used too
```

`Dockerfile.all-in-one` leaves no company certificate in the final image (the certs are mounted, not
copied, and the build stages that trust them are discarded), so it contains no trace of them and still
trusts only the default CAs at runtime. `Dockerfile.basic` still bakes them into the image. The
all-in-one build needs BuildKit (the default in current Docker).

`docker/start.sh` installs the certs as root before dropping to the
unprivileged `manus` user; the app then logs "N certificate(s) already
installed, nothing to do" rather than re-copying them.

## Runtime failures

### `docker compose up` refuses to start (missing secret)

This is the normal, expected path — `docker-compose.yml` has no working
defaults for `SECRET_KEY`, `INITIAL_PASSWORD`, `CREDENTIAL_ENCRYPTION_KEY`,
`DATABASE_PASSWORD`, `POSTGRES_PASSWORD`, `MANUS_REDIS_PASSWORD`, or `HATCHET_CLIENT_TOKEN` on
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

### Redis: agent users, and why the ACL file is generated

`manus-redis` starts through `redis/start.sh`, which writes `/data/users.acl` on every start: the `default`
user with the password from `MANUS_REDIS_PASSWORD` (stored as a SHA-256 hash), then the `user` lines of
`redis/agents.acl` if you created it from `redis/agents.acl.example` (Route to Agent agents on the Redis
transport, `../doc/AGENT_INTEGRATION.md`). Restart `manus-redis` after editing `agents.acl`.

It is generated rather than a plain `--aclfile` because loading an ACL file replaces the `default` user, and a
file without a `default` line leaves it **without a password**: the compose file's `--requirepass` would be
silently dropped. A `user default` line in `agents.acl` is ignored on purpose, and an invalid line makes Redis
refuse to start and name the line in `docker compose logs manus-redis`. The notice "Unknown file './users.acl'
found in data dir" in that log is harmless. Check the result without exposing the password:
`docker exec -e REDISCLI_AUTH="$MANUS_REDIS_PASSWORD" manus-redis redis-cli ACL LIST`.

### Database connection refused

Verify PostgreSQL is reachable from the container and `DATABASE_HOST` points to the correct host (not `localhost` when Postgres runs in another container).

### Hatchet worker not processing workflows

1. Confirm Hatchet infrastructure is running (`docker compose ps` in `docker/hatchet`)
2. Create an API token with `docker/hatchet/create-token.sh` (or at http://localhost:8888)
3. Set `HATCHET_CLIENT_TOKEN` in `docker/.env` (`HATCHET_CLIENT_HOST_PORT` is set by the compose file)
4. Check worker logs: `docker logs manus-worker`

### Creating a schedule fails with "An internal error occurred"

Schedules use Hatchet's REST API, not gRPC. The token embeds the address the Hatchet stack was configured
with (`http://localhost:8080`), which inside a container is the container itself. The compose file sets
`HATCHET_CLIENT_SERVER_URL=http://hatchet-dashboard:8080` for all application containers; if you changed
the Hatchet stack's service name or network, set `HATCHET_CLIENT_SERVER_URL` in `docker/.env` to the address
the containers can reach. `docker logs manus-web` then shows `Connection refused` on the failed call.

### Frontend can't reach backend

Inside the container, the frontend proxy uses `BACKEND_URL=http://127.0.0.1:8000`. Do not change this unless you run backend on a different host inside the container.

## Client IP and login rate limiting

`POST /auth/login` is rate-limited on two independent dimensions of *failed*
attempts: 20 failures/60s per client IP, and 100
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

## Request body size

The backend answers `413` when a request declares a `Content-Length` above
`MAX_REQUEST_BODY_BYTES` (default 25 MiB, `0` disables). This does **not** cover chunked
uploads without a `Content-Length`, so also limit the body in the reverse proxy in front
of the frontend (port 3000), e.g. nginx `client_max_body_size 25m;` or Traefik's
`buffering` middleware `maxRequestBodyBytes`. Certificate uploads are separately capped at
64 KiB. Raise `MAX_REQUEST_BODY_BYTES` (and the proxy limit) if a legitimate CSV, inventory
or template import is larger.

## AI assistant (streaming and local models)

The assistant streams its answer as Server-Sent Events (`POST /api/proxy/ai/chat`, content type
`text/event-stream`). A reverse proxy in front of the frontend must not buffer or compress that
response, or the answer appears all at once. The backend sends `X-Accel-Buffering: no` (nginx honours
it); for other proxies disable response buffering for that path. This has been verified through the
Next.js dev server only, **not** behind a production ingress.

A local model server (Ollama, LM Studio, ...) configured under Settings -> AI Assistant is subject to
the outbound URL policy: a host on the LAN works, a server on the backend's own machine (or the
Docker host's loopback) needs `ALLOW_LOOPBACK_SOURCE_URLS=true`. Outside development an API key is only
sent to an `https` URL.

## Reverse proxy

Terminate TLS in front of port 3000 with a reverse proxy of your choice (Traefik, nginx, Caddy, a
cloud load balancer). The proxy must (1) set or append `X-Forwarded-For` with the real client
address and must not trust client-supplied values from outside its own trust boundary (for Traefik:
do not widen `forwardedHeaders.trustedIPs`), (2) limit request bodies (25 MB matches
`MAX_REQUEST_BODY_BYTES`), (3) not buffer `/api/proxy/ai/chat` (a buffering middleware on that route
stops the answer from streaming; exclude it), and (4) forward `X-Forwarded-Proto: https`.
`X-Accel-Buffering: no` is an nginx header and has no effect on other proxies. Test streaming and
login after any proxy change.

## Image builds and cloud hosts

Images are built by the operator from their own working tree. Build from a clean checkout: `.env`
files are excluded from the build context, other local files are not.

On a cloud VM the outbound URL policy does not block the AWS IPv6 metadata address `fd00:ec2::254`
or `100.100.100.200`: restrict egress to metadata services at the network level.

## Health checks

```bash
docker exec manus-web curl -fs http://127.0.0.1:8000/health   # Direct backend (port 8000 is not published)
# There is no health route through the frontend proxy (it forwards /api/* only).
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
