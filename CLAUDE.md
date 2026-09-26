# Auxilium Manus - Technical Reference

## Overview
Auxilium Manus means "helping hand". The application is a NetDevOps workflow builder that
lets users select network devices from an inventory, design simple or complex workflows in
a visual canvas, and execute those workflows either manually or in the background.

Workflows consist of ordered and dependency-aware steps. The output of one step can become
the input of another step. Runtime data must distinguish between metadata (status,
timestamps, device identifiers, execution context) and content data (command output,
configuration backups, generated artifacts).

## Tech Stack

**Frontend:** Next.js 16.2.12 (App Router), React 19, React Flow, TypeScript 5,
Tailwind CSS 4, Shadcn UI, TanStack Query v5, Zustand, React Hook Form, Zod, Lucide Icons

**Backend:** FastAPI, Python 3.14, PostgreSQL, SQLAlchemy, Redis, JWT auth, Hatchet,
Netmiko, GitPython

**Integrations:** Nautobot API

## Architecture

### Core Principles
- **Complete separation**: Frontend (port 3000) ↔ Backend (port 8000)
- **API proxy pattern**: Frontend → Next.js `/api/proxy/*` → Backend (NEVER direct backend calls)
- **PostgreSQL single database** with 15 tables (10 domain + 5 RBAC), defined in `/backend/core/models/`
- **Layered backend**: Model → Repository → Service → Router
- **Feature-based organization**: Group by domain, not by technical role
- **Server Components default**: Use `'use client'` only when necessary

### Workflow Builder Product Direction
- **Primary UI**: Top menu bar and a large React Flow canvas where users design workflows
- **Device-first flow**: Users select inventory devices, then compose workflow steps for those devices
- **Visual workflow model**: React Flow for canvas state, node rendering, edges, connection validation
- **Executable workflow model**: Backend-owned JSON workflow definition separate from React Flow UI state
- **Run model**: Persist every workflow run separately (status, logs, step results, metadata, content data)
- **Background execution**: Hatchet for long-running orchestration, retries, step state; Redis for caching
- **Network execution**: Netmiko for SSH/CLI operations; Nornir/NAPALM/scrapli only when justified

### Workflow Domain Model

Keep these concepts separate in both frontend and backend code:

- **Canvas model**: React Flow nodes, edges, positions, viewport, selection state
- **Workflow definition**: Persisted business definition with steps, dependencies, input/output mappings
- **Workflow run**: One concrete execution with status, trigger source, user context, timestamps, logs
- **Step result**: Result of one step, split into metadata and content data
- **Artifact**: Durable content produced by a run (device config backups, reports)

### Recommended Libraries

**Frontend:** React Flow, Zustand (editor state), TanStack Query (server data), React Hook Form
+ Zod (forms), Shadcn UI + Tailwind, Monaco Editor (advanced templates only)

**Backend:** Hatchet (orchestration), PostgreSQL (definitions/runs/artifacts), Redis (cache/locks),
Pydantic (validation), Netmiko (network execution)

## CRITICAL: Architectural Standards

### Backend Layer Pattern
```
1. SQLAlchemy Model    → /backend/core/models/{domain}.py
2. Pydantic Models     → /backend/models/{domain}.py
3. Repository          → /backend/repositories/{domain}_repository.py
4. Service             → /backend/services/{domain}/{domain}_service.py
5. Router              → /backend/routers/{domain}.py
6. Register in main.py → app.include_router({domain}_router)
```

### Frontend Structure
```
/components/features/{domain}/
  ├── components/     # Feature-specific components
  ├── constants/      # Constants (if any)
  ├── hooks/          # Custom hooks (use-{name}.ts)
  ├── dialogs/        # Modal dialogs
  ├── tabs/           # Tab components
  ├── types/          # TypeScript types
  └── utils/          # Utility functions

/app/(dashboard)/{feature}/page.tsx  # Route stubs only
```

### Route File Rule — Stubs Only

`/app/(dashboard)/*/page.tsx` files MUST be pure route stubs:

```tsx
// CORRECT
import { MyFeaturePage } from '@/components/features/domain/my-feature-page'
export default function MyFeatureRoute() {
  return <MyFeaturePage />
}
```
- ❌ No logic, state, or hooks in route files
- ❌ No `'use client'` directive (add it to the feature component)
- ❌ No `components/` or `dialogs/` subdirectories inside route directories
- ✅ `export const metadata: Metadata` and Next.js segment config are allowed

### Naming Conventions
- **Database**: `snake_case` (tables: `job_templates`, columns: `created_at`)
- **Backend**: `snake_case` (files: `user_repository.py`, functions: `create_user()`)
- **Frontend**: `kebab-case` dirs and component files (`bulk-edit/`, `bulk-edit-dialog.tsx`)
- **Models**: `PascalCase` (`JobTemplate`, `UserProfile`)

### Database Requirements
- ✅ SQLAlchemy models in `/backend/core/models/` (one file per domain), all exported from `__init__.py`
- ✅ Indexes, foreign keys, timestamps (`created_at`, `updated_at`)
- ✅ Repository pattern (`BaseRepository` in `/backend/repositories/base.py`)
- ✅ Use the full migration framework for schema changes: `doc/MIGRATION_SYSTEM.md`
- ✅ `AutoSchemaMigration` (startup schema sync) runs under a `pg_advisory_xact_lock` — safety net only
- ✅ Prefer SQLAlchemy ORM/Core for all runtime data access
- ✅ Repository-layer `sqlalchemy.text()` only as documented in `doc/refactoring/REFACTORING_RAW_SQL.md` §3
- ❌ Never call `text()` from routers, services, or Hatchet workers
- ❌ Never compose runtime values into SQL via f-strings or string concatenation
- ❌ Never bypass repository layer

## Key File Locations

**Backend Core:**
- `/backend/core/models/` — SQLAlchemy table definitions (one file per domain)
- `/backend/core/database.py` — DB session, `get_db()` dependency
- `/backend/core/auth.py` — `verify_token`, `get_current_user`, `require_permission`,
  `require_any_permission`, `require_all_permissions`, `require_role`
- `/backend/main.py` — FastAPI app, router registration

**Frontend Core:**
- `/frontend/src/lib/auth-store.ts` — Zustand auth state
- `/frontend/src/lib/query-client.ts` — TanStack Query configuration
- `/frontend/src/lib/query-keys.ts` — Query key factory (hierarchical)
- `/frontend/src/hooks/use-api.ts` — API calling hook
- `/frontend/src/hooks/queries/*` — TanStack Query hooks
- `/frontend/src/app/api/proxy/[...path]/route.ts` — Backend proxy
- `/frontend/src/components/ui/*` — Shadcn UI primitives

---

@doc/claude/auth.md
@doc/claude/database.md
@doc/claude/frontend.md
@doc/claude/backend.md
@doc/claude/development.md
