# Contributing

Thanks for helping. This file is the short version; `INSTALL.md` covers the development setup and
`CLAUDE.md` plus `doc/claude/` describe the architecture and the rules the code follows.

## Security issues

Do not open a public issue for a vulnerability. See [`SECURITY.md`](SECURITY.md).

## Setup

Follow [`INSTALL.md`](INSTALL.md): Hatchet in Docker, PostgreSQL and Redis, Python 3.14 in a
virtual environment at `.venv/`, Node.js 26. Do not commit `.env` files or secrets.

## Before you open a pull request

Run what CI runs. Backend, from `backend/` with the virtual environment active:

```bash
ruff check .
pyright
python scripts/check_asyncio_run.py
python scripts/check_http_500_leaks.py
python scripts/check_router_repositories.py
python scripts/check_text_sql.py
python scripts/check_flag_parsing.py
python -m pytest            # unit tests; coverage may not fall below the ratchet (81 %)
```

Frontend, from `frontend/`:

```bash
npm run lint
npx tsc --noEmit
npm run test:coverage      # whole suite; coverage may not fall below the thresholds in vitest.config.ts
npm test                   # same tests without coverage (faster); `npx vitest run <file>` for one file
```

How to write the tests and how to run a browser pass against an isolated stack:
`doc/HOWTO_TEST_THE_FRONTEND.md`.

If you changed `docker/`, run `docker/check-compose.sh` (and `docker/check-image.sh` for the
Dockerfile). If you touched the PostgreSQL integration tests, see
`backend/tests/integration/README.md`.

### Formatting

Format **only the files you changed**: `ruff format path/to/file.py`. Never run `ruff format .` or
pass a directory (or run Prettier on one): several existing files differ from the formatter, and a
repository-wide reformat buries the real change.

## Code rules

- **Tests first.** Write the failing test, then the fix. Bug fixes come with a test that failed
  before the change. Unit tests use in-memory SQLite and fakeredis; PostgreSQL-only behaviour goes
  into `tests/integration` with the `postgres` marker.
- **Backend layers:** model, repository, service, router. No business logic in routers, no
  `sqlalchemy.text()` outside the allow-list that `check_text_sql.py` enforces, no raw exception
  text in a 5xx response (`raise_internal_server_error`).
- **Frontend:** feature folders, Shadcn UI, TanStack Query for server data, API calls only through
  `/api/proxy/*`. Route files under `app/(dashboard)` stay stubs.
- **New workflow step:** read `doc/WORKFLOW-STEPS.md` and `doc/WORKFLOW-STEPS-STYLE_GUIDE.md` first.
- **No secrets** in code, logs or fixtures. Test values must be obviously fake; real-looking keys
  fail the secret scan (`.gitleaks.toml`).
- Keep files small and focused, and prefer new objects over mutating inputs.

## Dependencies

- **`paramiko` stays below 5.0 on purpose** (`backend/requirements.txt`: `paramiko>=4.0,<5.0`). Netmiko
  itself only asks for `>=3.5.1`, but paramiko 5.x has breaking changes, so the project runs on
  paramiko 4. Do not raise or drop the cap in a routine dependency update; moving to 5 is a
  deliberate change with its own tests. `netmiko` is pinned to an exact version (`==4.8.0`) for the same
  reason. A Dependabot pull request that bumps either one is not a drop-in update.
- The only known advisory in the backend dependencies, `PYSEC-2026-2858` (paramiko, no fixed release),
  is ignored in CI on purpose; remove the ignore in `backend-ci.yml` and `audit.yml` when a fix ships.

## Commits and pull requests

Commit messages follow `<type>: <description>` with the types `feat`, `fix`, `refactor`, `docs`,
`test`, `chore`, `perf`, `ci`. A pull request describes what changed and why, lists how you tested
it, and notes anything an operator must do on upgrade (that goes into `CHANGELOG.md`, "Upgrade notes").

## Releases

The version is in `backend/core/version.py` and `frontend/package.json`; change both, and add a
`## [x.y.z]` section to `CHANGELOG.md`. A unit test fails if they disagree. The maintainer tags the
release.
