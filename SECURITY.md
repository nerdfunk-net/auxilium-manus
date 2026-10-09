# Security Policy

## Reporting a vulnerability

Please do not open a public issue. Report privately through GitHub's "Report a vulnerability"
button (Security → Advisories → Report a vulnerability) on this repository. Include the affected
version/commit, steps to reproduce and the impact. You will get an acknowledgement within 5 working
days.

## Supported versions

Only the latest commit on `main` is supported; fixes are not back-ported.

## Scope and deployment assumptions

Auxilium Manus is an internal NetDevOps tool. It assumes:

- the backend is reachable only through the bundled Next.js proxy (`/api/proxy/*`);
- a TLS-terminating reverse proxy sits in front of port 3000 and sets `X-Forwarded-For`
  (see `docker/DOCKER.md`, "Client IP and login rate limiting" and "Request body size");
- `ENV=production`, with the secrets required by `docker/.env.example` set.

## Accepted risks

Documented, with reasoning, in [`doc/SECURITY-NOTES.md`](doc/SECURITY-NOTES.md): the optional TLS
verification opt-out for development sources, Netmiko without SSH host-key checking, git
credentials visible in process argv for the duration of a clone/push, and raw device
configurations uploaded to the configured Batfish coordinator. Reports about these are welcome
but are known and by design.

## Hardening reference

`doc/analysis/FABLE_BACKEND_*.md` and `doc/analysis/FABLE_MERGE_20261009.md` record the audits
performed and what was fixed.
