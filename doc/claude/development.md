# Development Reference

## Environment Variables

**Backend** (`.env`):
```bash
SECRET_KEY=change-in-production  # JWT signing
BACKEND_SERVER_HOST=localhost
BACKEND_SERVER_PORT=8000
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=manus
DATABASE_USERNAME=postgres
DATABASE_PASSWORD=password
INITIAL_USERNAME=admin
INITIAL_PASSWORD=admin
ENABLE_DEV_TOOLS=true  # development-only; omit in production (OIDC test dashboard)
VAULT_ENABLED=false    # optional OpenBao secret storage; see doc/VAULT_INTEGRATION.md
```

**Frontend** (`.env.local`):
```bash
BACKEND_URL=http://localhost:8000  # Used by Next.js proxy
PORT=3000
ENABLE_DEV_TOOLS=true  # development-only; omit in production
```

## Development Workflow

```bash
# IMPORTANT: Always use the project virtual environment.
# The venv is at /.venv/ (project root, not backend/), using Python 3.14.
source ../.venv/bin/activate  # run once to activate

# Terminal 1 - Backend
cd backend && python start.py

# Terminal 2 - Hatchet worker (auto-restarts on .py changes)
cd backend && python scripts/run_worker_dev.py

# Terminal 3 - Frontend
cd frontend && npm run dev

# Default credentials: admin/admin
# Frontend: http://localhost:3001
# Backend:  http://localhost:8001

# Python linting (Ruff — run before larger backend changes)
# From backend/: scope to touched files only, never bare repo-wide `ruff format .`
ruff check .          # check
ruff check . --fix    # auto-fix where safe

# Dev test deps (once):
pip install -r requirements-dev.txt  # ruff, pip-audit, pyright

# Tests
python -m pytest
# or: python -m unittest discover -s tests

# CI checks (run locally before pushing):
pip-audit -r requirements.txt -r requirements-dev.txt --ignore-vuln PYSEC-2026-2858
pyright

# Integration tests (opt-in; real Nautobot / Gitea / Postgres / Cisco device)
# NOT part of default run or coverage ratchet — needs backend/.env.test (gitignored)
# See backend/tests/integration/README.md
python scripts/init_test_db.py                                  # once
python -m pytest tests/integration -m "not mutations" --no-cov
python -m pytest tests/integration -m mutations --no-cov --run-mutations

# Regression guards (run from backend/):
python scripts/check_asyncio_run.py
python scripts/check_http_500_leaks.py
python scripts/check_router_repositories.py
python scripts/check_text_sql.py
```

## Common Tasks

### Adding New Backend Endpoint
1. Define SQLAlchemy model in `/backend/core/models/{domain}.py` and export from `__init__.py`
2. Create Pydantic models in `/backend/models/{domain}.py`
3. Create repository in `/backend/repositories/{domain}_repository.py`
4. Create service in `/backend/services/{domain}/{domain}_service.py`
5. Create router in `/backend/routers/{domain}.py` (flat) or `/backend/routers/{domain}/`
   (package for complex domains), with auth dependencies
6. Register router in `/backend/main.py`

### Adding New Frontend Page
1. Create route stub in `/app/(dashboard)/{path}/page.tsx` (no logic, no `'use client'`)
2. Create feature page component in `/components/features/{domain}/`
3. Add query keys to `/lib/query-keys.ts`
4. Create TanStack Query hooks in `/hooks/queries/use-{domain}-query.ts`
5. Add sidebar link in `/components/layout/app-sidebar.tsx`
6. Use query hooks in components (NOT manual `useState + useEffect`)

Dashboard routes share `DashboardShell` with `AppSidebar`. Settings sections use
`/settings/[section]`. Workflow runs live at `/workflows/runs`. Timed runs live at
`/schedules` (see `doc/SCHEDULES.md`). Staged changes live at `/change-requests`
(see `doc/CICD_PIPELINE.md`).

AI collaboration: a seeded `ai-assistant` RBAC principal plus a per-workflow
`WorkflowAiSession` consent flag gate `backend/scripts/ai_workflow_apply.py`.
Read `doc/ai_collaboration/PROCESS.md` first.

### Adding New Permission
1. UI: `/settings/users` → Permissions tab lists the catalog; create from Roles tab's
   "Manage permissions" dialog (or `POST /api/rbac/permissions`), then grant to a role
2. Code: Use `require_permission("resource", "action")` in routers

### Adding a New Workflow Step

> **Read BOTH documents before implementing or changing any step:**
> - `doc/WORKFLOW-STEPS.md` — full spec: contracts, registry, execution path, fan-out
>   behaviour, branch-level concurrency
> - `doc/WORKFLOW-STEPS-STYLE_GUIDE.md` — frontend styling: shared canvas node,
>   `ConfigPanel` rules, fan-out config block

Each workflow step is a self-contained Python package under
`backend/workflow_steps/{step_id}/`. Execution path:
`StepRunner → STEP_REGISTRY → workflow_steps/{step}/executor.py`

**Backend (5 files/entries):**
1. `backend/workflow_steps/{step_id}/__init__.py` — empty
2. `backend/workflow_steps/{step_id}/executor.py` — business logic:
   ```python
   async def execute(*, config: dict, context: WorkflowContext, run: WorkflowRun,
                     artifact_service, node_id, device_sessions) -> list[StepOutcome]: ...
   ```
   `device_sessions` is a run-segment-scoped `DeviceSessionPool`; non-SSH steps accept it
   but never use it (import `DeviceSessionPool` under `TYPE_CHECKING`).
3. `backend/workflow_steps/{step_id}/config.py` — `def get_config() -> dict` (if step has config)
4. `backend/services/execution/step_registry.py` — add one import + one dict entry
5. `backend/workflow_steps/registry.yaml` — add registry entry

**Frontend (2–3 files):**
6. `frontend/src/components/features/workflow-steps/{step-id}/index.tsx` — `ConfigPanel` only
7. `frontend/src/lib/plugin-ui-registry.ts` — add entry to `PLUGIN_UI_REGISTRY`
8. (Optional) `workflow-node.tsx` — one `nodeIconsByKind` entry if the default icon is wrong

**Rules:**
- ❌ No business logic in `step_registry.py` — dispatch table only
- ❌ No custom canvas render branch per step in `workflow-node.tsx`
- ❌ External code must never import `workflow_steps` packages directly
- ✅ Raise `ValueError` for config/input errors, `RuntimeError` for execution failures
- ✅ If the step needs git: store `git_repository_id: int` in config, resolve via
  `workflow_steps.common.git_repository_loader.load_git_repository`
- ✅ If the step writes to `device.parsed`: use
  `services.workflow_context.node_result.set_node_result(device.parsed, node_id, key, value)`
  — never a flat `f"{node_id}.{key}"` string key (dots are nesting separators in
  `resolve_device_attribute`/`resolve_device_value`)

## Security Checklist
- ✅ Change `SECRET_KEY` and default admin password before production
- ✅ All backend endpoints use JWT auth
- ✅ Frontend always uses `/api/proxy/*` (never direct backend)
- ✅ Validate inputs with Pydantic models
- ✅ Check permissions with `require_permission()`
- ✅ Use HTTPS in production
- ✅ Never commit `.env` files
- ✅ **5xx errors:** Never put raw exception text in `HTTPException(detail=…)`. Use
  `core.safe_http_errors.raise_internal_server_error` so clients only see
  `{message, error_id}`; correlate via logs.

## Key Patterns Summary

**Backend:**
- Repository pattern for local PostgreSQL access
- Resolver + Manager pattern for external APIs (Nautobot, CheckMK)
- Service layer for business logic; thin routers delegate to services
- Dependency injection for auth/permissions
- SQLAlchemy ORM/Core for runtime data access

**Frontend:**
- Feature-based organization (`components/features/{domain}/`)
- Server Components by default; `'use client'` only when necessary
- API calls via `/api/proxy/*` only
- TanStack Query for server state; Zustand for client-only state
- Shadcn UI for all components; react-hook-form + zod for forms

**Database:**
- Single PostgreSQL database
- Use the full migration framework (`doc/MIGRATION_SYSTEM.md`)
- Models split by domain in `/backend/core/models/`

**Authentication:**
- JWT tokens in HTTP-only cookies
- Permission format: `resource:action`
- Backend: `Depends(require_permission("resource", "action"))`
- Frontend: `hasPermission(user, "resource", "action")` from `lib/permissions.ts`

## Python Conventions

For Hatchet workflows and workers: add inline documentation comments when modifying
queue configurations, workflow decorators, or worker settings.

## Task Completion

When removing features or debugging issues, always complete the full cycle:
1. Remove all related code
2. Update configuration files
3. Clean up imports/dependencies
4. Verify no references remain with grep
