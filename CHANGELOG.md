# Changelog

All notable changes to Auxilium Manus. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/) once 1.0 is reached. Until then a minor
version may contain breaking changes, which are listed under "Upgrade notes".

The version is defined in `backend/core/version.py` and `frontend/package.json`; a unit test fails
when they differ or when this file has no entry for the current version.

## [0.1.0] - unreleased

First public version: a visual NetDevOps workflow builder (React Flow canvas, Hatchet execution,
Netmiko, Nautobot, Cisco Catalyst Center, ISE, Batfish and pyATS integrations, reports, schedules,
change requests, optional AI assistant). See `README.md` for the feature overview.

### Upgrade notes

Notes for databases and setups created before this version. A fresh installation needs none of them.

- **`workflow_runs.run_mode` column.** Databases created before the debug-mode removal still have
  this column as `NOT NULL` without a default, so every workflow trigger fails with a
  not-null violation. The automatic schema sync never drops columns. Once, after a `pg_dump`:
  `cd backend && python scripts/database/sync.py --migrate --drop-columns --table workflow_runs`
  (preview first with `python scripts/database/sync.py --table workflow_runs`).
- **Ports.** The code defaults are now 3000 (frontend) and 8000 (backend). A `backend/.env` without
  `BACKEND_PORT` therefore starts on 8000; set `BACKEND_PORT` (and `BACKEND_URL` in
  `frontend/.env.local`) if you rely on other ports.
- **Hatchet stack.** `docker/hatchet/.env` needs `HATCHET_ADMIN_EMAIL` and `HATCHET_ADMIN_PASSWORD`
  (8-64 characters with an upper-case letter, a lower-case letter and a digit). Existing Hatchet
  volumes keep their current account. The engine's gRPC port is no longer published; use
  `docker-compose.dev.yml` for a backend on the host. Create tokens with
  `docker/hatchet/create-token.sh`.
- **Run retention is on by default.** `RUN_RETENTION_ENABLED` now defaults to `true`: finished runs
  and their artifacts older than `RUN_RETENTION_DAYS` (90) are deleted. Set it to `false` to keep
  everything. Deleting a workflow now also removes the files of its runs.
- **Redis outage.** Login and token-refresh rate limits fall back to in-process counters instead of
  blocking logins. Set `RATE_LIMIT_FAIL_CLOSED=true` to refuse those requests instead.
- **Workers drain for up to 10 minutes** on `docker compose stop` (`stop_grace_period: 10m`).
- **Node.js 26** is the runtime of the image and the CI.
- **Credentials in use cannot be deleted** any more: `DELETE /credentials/{id}` answers `409` with
  the list of workflows, repositories, sources and templates that use it; `?force=true` overrides.
- **Key rotation.** There is no re-encryption tool for `CREDENTIAL_ENCRYPTION_KEY`; see
  `SECURITY.md`, "Rotating `CREDENTIAL_ENCRYPTION_KEY`".
