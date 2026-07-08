# Auxilium Manus - Technical Reference

## Overview
Auxilium Manus means "helping hand". The application is a NetDevOps workflow builder that lets users select network devices from an inventory, design simple or complex workflows in a visual canvas, and execute those workflows either manually or in the background.

Workflows consist of ordered and dependency-aware steps. The output of one step can become the input of another step. Runtime data must distinguish between metadata (status, timestamps, device identifiers, execution context) and content data (command output, configuration backups, generated artifacts).

## Tech Stack

**Frontend:** Next.js 16.2.6 (App Router), React 19, React Flow, TypeScript 5, Tailwind CSS 4, Shadcn UI, TanStack Query v5, Zustand, React Hook Form, Zod, Lucide Icons
**Backend:** FastAPI, Python 3.9+, PostgreSQL, SQLAlchemy, Redis, JWT auth, Hatchet, Netmiko, GitPython
**Integrations:** Nautobot API

## Architecture

### Core Principles
- **Complete separation**: Frontend (port 3000) ↔ Backend (port 8000)
- **API proxy pattern**: Frontend → Next.js `/api/proxy/*` → Backend (NEVER direct backend calls)
- **PostgreSQL single database** with 14 tables (9 domain tables + 5 RBAC tables, defined in `/backend/core/models/`)
- **Layered backend**: Model → Repository → Service → Router
- **Feature-based organization**: Group by domain, not by technical role
- **Server Components default**: Use `'use client'` only when necessary

### Workflow Builder Product Direction
- **Primary UI**: Keep the frontend simple: a top menu bar and a large React Flow canvas where users design workflows.
- **Device-first flow**: Users first select one or more inventory devices, then compose the workflow steps that should run against those devices.
- **Visual workflow model**: Use React Flow for canvas state, node rendering, edges, connection validation, custom nodes, and drag-and-drop editing.
- **Executable workflow model**: Store a backend-owned JSON workflow definition separate from React Flow UI state. The backend validates the graph and converts it into executable steps.
- **Run model**: Persist every workflow run separately from the workflow definition, including status, logs, step results, metadata, and content data.
- **Background execution**: Use Hatchet for long-running workflow orchestration, retries, step state, and background execution. Use Redis for caching, locks, and short-lived runtime coordination.
- **Network execution**: Start with Netmiko for SSH/CLI operations against network devices. Consider Nornir later for parallel multi-device execution, NAPALM for vendor-neutral abstractions, or scrapli as a modern alternative to Netmiko.
- **Optional editor**: Add Monaco Editor only when workflow steps need advanced command templates, expressions, or script-like configuration.

### Workflow Domain Model

Keep these concepts separate in both frontend and backend code:

- **Canvas model**: React Flow nodes, edges, positions, viewport, selection state, and editor-only UI metadata.
- **Workflow definition**: Persisted business definition with steps, dependencies, input/output mappings, validations, and device targeting rules.
- **Workflow run**: One concrete execution of a workflow with status, trigger source, user context, timestamps, logs, and step states.
- **Step result**: The result of one step, split into metadata and content data.
- **Artifact**: Durable content produced by a run, such as device configuration backups or generated reports.

### Recommended Workflow Libraries

**Frontend workflow editor:**
- React Flow for visual node/edge editing.
- Zustand for local editor state that is not server data.
- TanStack Query for inventory, workflow definitions, workflow runs, logs, and execution status.
- React Hook Form with Zod for node configuration forms and validation.
- Shadcn UI and Tailwind CSS for all controls, dialogs, menus, panels, and forms.
- Monaco Editor only for advanced templates or expressions.

**Backend workflow execution:**
- Hatchet for durable workflow orchestration, background execution, retries, and step lifecycle.
- PostgreSQL for workflow definitions, workflow versions, runs, step results, and artifacts metadata.
- Redis for cache, locks, transient state, and runtime coordination.
- Pydantic for strict validation of workflow definitions, step inputs, step outputs, and run payloads.
- Netmiko as the initial network device execution library.
- Nornir, NAPALM, or scrapli only when the use case justifies them.

## CRITICAL: Architectural Standards

**MANDATORY for all new features:**

### Backend Layer Pattern
```
1. SQLAlchemy Model    → /backend/core/models/{domain}.py (tables, indexes, relationships)
2. Pydantic Models     → /backend/models/{domain}.py (request/response schemas)
3. Repository          → /backend/repositories/{domain}_repository.py (data access)
4. Service             → /backend/services/{domain}/{domain}_service.py (business logic)
5. Router              → /backend/routers/{domain}.py (HTTP endpoints)
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

/app/(dashboard)/{feature}/page.tsx  # Route pages — stubs only (see rule below)
```

### Route File Rule — Stubs Only

`/app/(dashboard)/*/page.tsx` files MUST be pure route stubs.

**CORRECT:**
```tsx
import { MyFeaturePage } from '@/components/features/domain/my-feature-page'

export default function MyFeatureRoute() {
  return <MyFeaturePage />
}
```

**Rules:**
- ❌ No logic, state, or hooks in route files
- ❌ No `'use client'` directive on route files (add it to the feature component instead)
- ❌ No `components/` or `dialogs/` subdirectories inside route directories
- ✅ Optional: `export const metadata: Metadata = { title: '...' }` is allowed
- ✅ Optional: `export const dynamic = 'force-dynamic'` and similar Next.js segment config is allowed
- ✅ All feature logic lives in `components/features/{domain}/`

### Naming Conventions
- **Database**: `snake_case` (tables: `job_templates`, columns: `created_at`)
- **Backend**: `snake_case` (files: `user_repository.py`, functions: `create_user()`)
- **Frontend**: `kebab-case` dirs and component files (`bulk-edit/`, `bulk-edit-dialog.tsx`)
- **Models**: `PascalCase` (`JobTemplate`, `UserProfile`)

### Database Requirements
- ✅ Define tables as SQLAlchemy models in `/backend/core/models/` (one file per domain)
- ✅ Export all models from `/backend/core/models/__init__.py`
- ✅ Add indexes, foreign keys, timestamps (`created_at`, `updated_at`)
- ✅ Use repository pattern (BaseRepository in `/backend/repositories/base.py`)
- ✅ Production database is PostgreSQL with SQLAlchemy ORM/Core (`./doc/MIGRATION_SYSTEM.md`). In-memory SQLite in **unit** tests is acceptable when queries do not rely on PostgreSQL-only features.
- ✅ Prefer SQLAlchemy ORM/Core for all runtime application data access. Repository-layer `sqlalchemy.text()` is allowed only under the rules in `doc/refactoring/REFACTORING_RAW_SQL.md` §3 (bound parameters, named constants for non-trivial SQL, no string composition of values, PostgreSQL integration coverage for dialect-specific behaviour). Health checks (`SELECT 1` in `core/database.py`) and migration/schema tooling are exempt.
- ❌ Never call `text()` from routers, services, or Celery tasks.
- ❌ Never compose runtime values into raw SQL via f-strings or string concatenation.
- ❌ NEVER bypass repository layer

## Key File Locations

**Backend Core:**
- `/backend/core/models/` - SQLAlchemy table definitions (one file per domain)
  - `base.py` - `Base` (declarative base)
  - `credentials.py` - `Credential`
  - `git.py` - `GitRepository`
  - `inventories.py` - `Inventory`
  - `rbac.py` - `Permission`, `Role`, `RolePermission`, `UserPermission`, `UserRole`
  - `runs.py` - `WorkflowRun`, `WorkflowStepResult`
  - `settings.py` - `Setting`
  - `templates.py` - `Template`
  - `users.py` - `User`
  - `workflows.py` - `Workflow`
  - `__init__.py` - Re-exports all models
- `/backend/core/database.py` - DB session, get_db() dependency
- `/backend/core/auth.py` - verify_token, get_current_user, require_permission, require_any_permission, require_all_permissions, require_role
- `/backend/main.py` - FastAPI app, router registration

**Frontend Core:**
- `/frontend/src/lib/auth-store.ts` - Zustand auth state
- `/frontend/src/lib/query-client.ts` - TanStack Query configuration
- `/frontend/src/lib/query-keys.ts` - Query key factory (hierarchical)
- `/frontend/src/hooks/use-api.ts` - API calling hook
- `/frontend/src/hooks/queries/*` - TanStack Query hooks
- `/frontend/src/app/api/proxy/[...path]/route.ts` - Backend proxy
- `/frontend/src/components/ui/*` - Shadcn UI primitives

## Authentication & Authorization

### JWT Token Structure
```python
{
  "sub": "username",
  "user_id": 123,
  "exp": 1234567890
}
```
Permissions are **not** embedded in the JWT. Authorization is evaluated per-request
against the database via `RBACService.has_permission(user_id, resource, action)` — there
is no caching and no JWT permission claim to keep in sync.

### RBAC Data Model
Five tables in `/backend/core/models/rbac.py`: `roles`, `permissions`, `role_permissions`,
`user_roles`, `user_permissions`. `user_permissions` holds per-user overrides (an explicit
allow or deny for one `resource:action`) that sit above role-derived grants.

Precedence: **user-level override (allow or deny) > role-derived grant > default-deny.**
See `backend/services/auth/rbac_service.py::RBACService.has_permission`.

### Permission Pattern
Format: `{resource}:{action}` (e.g., `users:read`, `settings:write`, `credentials:delete`)

### Backend Auth Dependencies
```python
from core.auth import verify_token, require_permission, require_role

# Basic auth
@router.get("/data")
async def get_data(user: dict = Depends(verify_token)):
    pass

# Permission required (format: "resource" or "resource.subresource", action)
@router.post("/users", dependencies=[Depends(require_permission("users", "write"))])
async def create_user():
    pass

@router.get("/workflows", dependencies=[Depends(require_permission("workflows", "read"))])
async def get_workflows():
    pass

# Role required
@router.delete("/critical")
async def delete_critical(user: dict = Depends(require_role("admin"))):
    pass
```

### Frontend Auth
```typescript
import { useAuthStore } from '@/lib/auth-store'
const user = useAuthStore(state => state.user)

// API calls always go through the Next.js proxy on the same origin.
fetch('/api/proxy/users')
```

**Proxy-only auth rule:** Browsers must never call the FastAPI backend directly
and the backend must not rely on CORS for frontend access. Frontend requests go
to `/api/proxy/*`; the Next.js server forwards them to `BACKEND_URL` and attaches
the HTTP-only auth cookie as a backend `Authorization` header.

## Database Schema (Key Tables)

**Domain tables:** `users`, `credentials`, `git_repositories`, `inventories`, `settings`, `templates`, `workflows`, `workflow_runs`, `workflow_step_results`
**RBAC tables:** `roles`, `permissions`, `role_permissions`, `user_roles`, `user_permissions`

## UI/UX Standards

### MUST Use Shadcn UI
```bash
npx shadcn@latest add {component}  # button, dialog, table, form, etc.
```

**DO:**
- ✅ Use Shadcn components for ALL UI primitives
- ✅ Use Tailwind utility classes (`bg-background`, `text-foreground`, NOT `bg-blue-500`)
- ✅ Use Lucide React icons (`import { Check, X } from "lucide-react"`)
- ✅ Forms with react-hook-form + zod validation
- ✅ Toast notifications (`useToast()` hook)
- ✅ Mobile-first responsive design
- ✅ Proper ARIA labels and accessibility

**DON'T:**
- ❌ Build UI from scratch when Shadcn exists
- ❌ Use arbitrary colors or inline styles
- ❌ Mix other UI libraries
- ❌ Use `alert()` or `confirm()` (use Dialog/AlertDialog)

### Common Patterns
```typescript
// Button variants
<Button variant="default|secondary|destructive|outline|ghost|link">

// Dialog
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"

// Form
import { Form, FormField, FormItem, FormLabel, FormControl } from "@/components/ui/form"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"

// Toast
import { useToast } from "@/hooks/use-toast"
const { toast } = useToast()
toast({ title: "Success", description: "Done!" })
```

## GraphQL Integration

**Always use centralized service:** `/frontend/src/services/nautobot-graphql.ts`

```typescript
// Add to service file
export const MY_QUERY = `query { ... }`
export interface GraphQLMyData { ... }
export async function fetchMyData(apiCall) { ... }

// Use in component
import { fetchMyData } from '@/services/nautobot-graphql'
const result = await fetchMyData(apiCall)
```

❌ DON'T create inline GraphQL queries or dedicated backend endpoints for each query

## TanStack Query (Data Fetching & Caching)

**MANDATORY for all data fetching:** Use TanStack Query instead of manual state management

### Core Principles
- **Declarative data fetching**: Query hooks replace manual useState/useEffect
- **Automatic caching**: Data persists across navigation, reduces API calls
- **Background refetch**: Fresh data on window focus/reconnect
- **Centralized keys**: Use query key factory for type-safe invalidation
- **Smart polling**: Auto-start/stop based on data state

### Query Hook Pattern

```typescript
// 1. Add query keys to /frontend/src/lib/query-keys.ts
export const queryKeys = {
  myFeature: {
    all: ['myFeature'] as const,
    list: (filters?: { status?: string }) =>
      filters
        ? ([...queryKeys.myFeature.all, 'list', filters] as const)
        : ([...queryKeys.myFeature.all, 'list'] as const),
    detail: (id: string) => [...queryKeys.myFeature.all, 'detail', id] as const,
  },
}

// 2. Create hook in /frontend/src/hooks/queries/use-my-feature-query.ts
import { useQuery } from '@tanstack/react-query'
import { useApi } from '@/hooks/use-api'
import { queryKeys } from '@/lib/query-keys'

interface UseMyFeatureQueryOptions {
  filters?: { status?: string }
  enabled?: boolean
}

const DEFAULT_OPTIONS: UseMyFeatureQueryOptions = {}

export function useMyFeatureQuery(options: UseMyFeatureQueryOptions = DEFAULT_OPTIONS) {
  const { apiCall } = useApi()
  const { filters, enabled = true } = options

  return useQuery({
    queryKey: queryKeys.myFeature.list(filters),
    queryFn: async () => apiCall('my-feature', { method: 'GET' }),
    enabled,
    staleTime: 30 * 1000,  // Cache for 30s
  })
}

// 3. Use in component
const { data, isLoading, error, refetch } = useMyFeatureQuery({
  filters: { status: 'active' }
})
const items = data?.items || []
```

### Mutation Hook Pattern

```typescript
// Create mutations in /frontend/src/hooks/queries/use-my-feature-mutations.ts
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useApi } from '@/hooks/use-api'
import { queryKeys } from '@/lib/query-keys'
import { useToast } from '@/hooks/use-toast'

export function useMyFeatureMutations() {
  const { apiCall } = useApi()
  const queryClient = useQueryClient()
  const { toast } = useToast()

  const createItem = useMutation({
    mutationFn: async (data: CreateItemInput) => {
      return apiCall('my-feature', {
        method: 'POST',
        body: JSON.stringify(data)
      })
    },
    onSuccess: () => {
      // Automatic cache invalidation → triggers refetch
      queryClient.invalidateQueries({ queryKey: queryKeys.myFeature.list() })
      toast({
        title: 'Success',
        description: 'Item created!',
      })
    },
    onError: (error: Error) => {
      toast({
        title: 'Error',
        description: error.message,
        variant: 'destructive'
      })
    }
  })

  return { createItem, updateItem, deleteItem }
}
```

### Polling Pattern (Jobs/Tasks)

```typescript
export function useJobQuery(taskId: string) {
  return useQuery({
    queryKey: queryKeys.jobs.detail(taskId),
    queryFn: () => fetchJob(taskId),
    enabled: !!taskId,
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data) return 2000  // Keep polling

      // Auto-stop when job completes
      if (['SUCCESS', 'FAILURE', 'REVOKED'].includes(data.status)) {
        return false
      }

      return 2000  // Continue polling every 2s
    },
    staleTime: 0,  // Always fetch fresh
  })
}
```

### Optimistic Updates (Instant UI Feedback)

```typescript
const syncRepository = useMutation({
  mutationFn: async (id) => apiCall(`git/${id}/sync`, { method: 'POST' }),

  // Run BEFORE API call
  onMutate: async (id) => {
    await queryClient.cancelQueries({ queryKey: queryKeys.git.repositories() })
    const previous = queryClient.getQueryData(queryKeys.git.repositories())

    // Update UI immediately
    queryClient.setQueryData(queryKeys.git.repositories(), (old) => ({
      ...old,
      repositories: old.repositories.map((r) =>
        r.id === id ? { ...r, sync_status: 'syncing' } : r
      )
    }))

    return { previous }  // For rollback
  },

  // Rollback on error
  onError: (err, id, context) => {
    queryClient.setQueryData(queryKeys.git.repositories(), context?.previous)
  },

  onSettled: () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.git.repositories() })
  }
})
```

### DO:
- ✅ Use centralized query key factory (`queryKeys`)
- ✅ Create dedicated hooks for each resource
- ✅ Use `DEFAULT_OPTIONS = {}` constant for default params
- ✅ Invalidate affected queries after mutations
- ✅ Match `staleTime` to data volatility (5min for static, 30s for semi-static, 0 for polling)
- ✅ Use `useMemo` for derived state (not `useState`)
- ✅ Enable `refetchOnWindowFocus` for network monitoring

### DON'T:
- ❌ Use manual `useState + useEffect` for server data
- ❌ Use inline query keys (always use `queryKeys` factory)
- ❌ Store query data in `useState` (use `useMemo` for derived state)
- ❌ Forget to invalidate cache after mutations
- ❌ Use inline object literals as default params (`= {}` creates new object every render)

### Documentation:
- **Best Practices**: `/frontend/src/hooks/queries/BEST_PRACTICES.md`
- **Optimistic Updates**: `/frontend/src/hooks/queries/OPTIMISTIC_UPDATES.md`

## React Best Practices (CRITICAL - Prevents Infinite Loops)

### MUST Follow to Prevent Re-render Loops

**1. Default Parameters - Use Constants**
```typescript
// ❌ WRONG - Creates new array every render
function Component({ items = [] }) { }

// ✅ CORRECT
const EMPTY_ARRAY: string[] = []
function Component({ items = EMPTY_ARRAY }) { }
```

**2. Custom Hooks - Memoize Returns**
```typescript
// ❌ WRONG - New object every render
export function useMyHook() {
  const [state, setState] = useState()
  return { state, setState }  // New object!
}

// ✅ CORRECT
export function useMyHook() {
  const [state, setState] = useState()
  return useMemo(() => ({ state, setState }), [state])
}
```

**3. useEffect Dependencies - MUST Be Stable**
```typescript
// ❌ WRONG
const config = { key: 'value' }
useEffect(() => doSomething(config), [config])  // Runs every render!

// ✅ CORRECT
const DEFAULT_CONFIG = { key: 'value' }  // Outside component
useEffect(() => doSomething(DEFAULT_CONFIG), [])

// OR for dynamic values
const config = useMemo(() => ({ key: someValue }), [someValue])
useEffect(() => doSomething(config), [config])
```

**4. Callbacks to Hooks - ALWAYS useCallback**
```typescript
// ❌ WRONG
const { data } = useMyHook({
  onChange: () => doSomething()  // New function every render!
})

// ✅ CORRECT
const handleChange = useCallback(() => doSomething(), [])
const { data } = useMyHook({ onChange: handleChange })
```

**5. Exhaustive Dependencies - ALWAYS Include All**
```typescript
// ❌ WRONG
useEffect(() => {
  if (isReady) loadData(userId)
}, [])  // Missing dependencies!

// ✅ CORRECT
useEffect(() => {
  if (isReady) loadData(userId)
}, [isReady, userId, loadData])
```

**Enforcement:** ESLint rules + pre-commit hooks block non-compliant code

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
```

**Frontend** (`.env.local`):
```bash
BACKEND_URL=http://localhost:8000  # Used by Next.js proxy
PORT=3000
```

## Common Tasks

### Adding New Backend Endpoint
1. Define SQLAlchemy model in `/backend/core/models/{domain}.py` and export it from `/backend/core/models/__init__.py`
2. Create Pydantic models in `/backend/models/{domain}.py`
3. Create repository in `/backend/repositories/{domain}_repository.py`
4. Create service in `/backend/services/{domain}/{domain}_service.py`
5. Create router in `/backend/routers/{domain}.py` (flat, for simple domains) or as a
   `/backend/routers/{domain}/` package (for domains with multiple route groups, e.g.
   `routers/git/`, `routers/rbac/`), with auth dependencies
6. Register router in `/backend/main.py`

### Adding New Frontend Page
1. Create route stub in `/app/(dashboard)/{path}/page.tsx` (no logic, no `'use client'`)
2. Create feature page component in `/components/features/{domain}/`
3. Add query keys to `/lib/query-keys.ts`
4. Create TanStack Query hooks in `/hooks/queries/use-{domain}-query.ts`
5. Add sidebar link in `/components/layout/app-sidebar.tsx`
6. Use query hooks in components (NOT manual `useState + useEffect`)

Dashboard routes share `DashboardShell` (`/components/layout/dashboard-shell.tsx`) with `AppSidebar` for navigation. Settings sections use `/settings/[section]` (e.g. `/settings/sources`). Workflow runs live at `/workflows/runs`.

### Adding New Permission
1. UI: `/settings/users` → Permissions tab lists the catalog; create a permission from
   the Roles tab's "Manage permissions" dialog (or `POST /api/rbac/permissions`), then
   grant it to a role
2. Code: Use `require_permission("resource", "action")` in routers

### Adding a New Workflow Step

> **Read BOTH documents before implementing or changing any step/artifact:**
> - `doc/WORKFLOW-STEPS.md` — full specification: contracts, registry, execution path,
>   and **fan-out** behaviour (per-device child workflows; git/filesystem sinks are not
>   automatically fan-out-safe).
> - `doc/WORKFLOW-STEPS-STYLE_GUIDE.md` — frontend styling: shared **canvas node**
>   (`w-80` × `h-32`, full title, light-gray input handle, green/red output handles),
>   `ConfigPanel`/dialog rules (teal palette, card anatomy, fan-out config block).

Each workflow step is a self-contained Python package under `backend/workflow_steps/{step_id}/`.
The execution path is: `StepRunner → STEP_REGISTRY → workflow_steps/{step}/executor.py`.

**Backend (5 files/entries):**
1. `backend/workflow_steps/{step_id}/__init__.py` — empty
2. `backend/workflow_steps/{step_id}/executor.py` — business logic:
   ```python
   async def execute(*, config: dict, context: WorkflowContext, run: WorkflowRun, artifact_service, node_id) -> list[StepOutcome]: ...
   ```
3. `backend/workflow_steps/{step_id}/config.py` — `def get_config() -> dict` (if step has config)
4. `backend/services/execution/step_registry.py` — add one import + one dict entry
5. `backend/workflow_steps/registry.yaml` — add registry entry

**Frontend (2–3 files):**
6. `frontend/src/components/features/workflow-steps/{step-id}/index.tsx` — `ConfigPanel` only (`PluginUIComponent`); canvas rendering is shared in `workflow-node.tsx`
7. `frontend/src/lib/plugin-ui-registry.ts` — add entry to `PLUGIN_UI_REGISTRY`
8. (Optional) `workflow-node.tsx` — one `nodeIconsByKind` entry if the default icon is wrong; never add a custom node render branch

**Rules:**
- ❌ No business logic in `step_registry.py` — dispatch table only
- ❌ No custom canvas render branch per step in `workflow-node.tsx` — equal size, registry-driven title/description, standard outcome colours
- ❌ External code must never import `workflow_steps` packages directly; only `StepRunner` calls executors
- ✅ Raise `ValueError` for config/input errors, `RuntimeError` for execution failures

## Security Checklist
- ✅ Change `SECRET_KEY` and default admin password
- ✅ All backend endpoints use JWT auth
- ✅ Frontend always uses `/api/proxy/*` (never direct backend)
- ✅ Validate inputs with Pydantic models
- ✅ Check permissions with `require_permission()`
- ✅ Use HTTPS in production
- ✅ Never commit `.env` files
- ✅ **5xx errors:** Never put raw exception text (`str(e)`, `{exc}`, etc.) in `HTTPException(detail=…)` for server errors. Use `core.safe_http_errors.raise_internal_server_error` (and optional `status_code` for sanitized non-500 5xx such as 502) so clients only see `{message, error_id}`; correlate via logs.

## Development Workflow
```bash
# IMPORTANT: Always use the project virtual environment for Python commands.
# The venv is at /.venv/ (project root, not backend/), using Python 3.14.
# Wrong: python start.py  →  Right: ../.venv/bin/python start.py  (or activate first)
source ../.venv/bin/activate  # run once to activate, then use `python` normally

# Terminal 1 - Backend
cd backend && python start.py

# Terminal 2 - Frontend
cd frontend && npm run dev

# Default credentials: admin/admin
# Frontend: http://localhost:3000
# Backend: http://localhost:8000

# Ruff (Python lint/format rules in backend/pyproject.toml) — run from time to time
# or before larger backend changes; from backend/: `ruff check .` (optionally `--fix`)
ruff check .
```

Router/repository-boundary and raw-SQL/asyncio-leak regression guard scripts are not yet
ported into this repo's `backend/scripts/` (only `purge_retention.py` exists there); see
`doc/BACKEND-ANALYSIS.md` §3.3 if reintroducing them.

When implementing configuration changes, include verification steps that confirm the change works (e.g., run a quick test, check logs, or validate config loads)

## Nautobot Services Architecture

**IMPORTANT:** Nautobot services follow a specialized pattern for external API integration.

### Architecture Overview
Nautobot services wrap an **external API client** (not local database), so the traditional Repository pattern doesn't apply. Instead, use a modular service layer with dependency injection.

### Directory Structure
```
backend/services/nautobot/
├── client.py                  # NautobotService API client (GraphQL + REST)
├── common/                    # Pure functions (no dependencies)
│   ├── validators.py          # is_valid_uuid, validate_ip_address, etc.
│   ├── utils.py               # flatten_nested_fields, normalize_tags, etc.
│   └── exceptions.py          # Custom exception hierarchy
│
├── resolvers/                 # ID/UUID resolution (read-only)
│   ├── base_resolver.py       # Shared GraphQL query logic
│   ├── device_resolver.py     # Device & device-type resolution
│   ├── metadata_resolver.py   # Status, role, platform, location
│   └── network_resolver.py    # IP, interface, namespace, prefix
│
├── managers/                  # Resource lifecycle (create/update)
│   ├── ip_manager.py          # IP address operations
│   ├── interface_manager.py   # Interface operations
│   ├── prefix_manager.py      # Prefix operations
│   └── device_manager.py      # Device-specific operations
│
└── devices/
    ├── common.py              # Unified facade (recommended for device operations)
    ├── creation.py            # Device creation workflows
    ├── update.py              # Device update workflows
    └── import_service.py      # Bulk device import
```

### Usage Pattern

**✅ RECOMMENDED - Use Facade for Device Operations:**
```python
from services.nautobot import NautobotService
from services.nautobot.devices.common import DeviceCommonService

class MyDeviceService:
    def __init__(self, nautobot_service: NautobotService):
        self.nautobot = nautobot_service
        self.common = DeviceCommonService(nautobot_service)

    async def my_operation(self):
        # All device operations available through facade
        device_id = await self.common.resolve_device_by_name("router1")
        status_id = await self.common.resolve_status_id("active")

        ip_id = await self.common.ensure_ip_address_exists(
            ip_address="10.0.0.1/24",
            namespace_id="...",
            status_name="active"
        )
```

**✅ ALTERNATIVE - Direct Injection (for specialized use cases):**

Use this when you only need specific components or want fine-grained control:

```python
from services.nautobot import NautobotService
from services.nautobot.resolvers import DeviceResolver, MetadataResolver
from services.nautobot.managers import IPManager

class MySpecializedService:
    def __init__(self, nautobot_service: NautobotService):
        self.nautobot = nautobot_service
        # Only inject what you need
        self.device_resolver = DeviceResolver(nautobot_service)
        self.metadata_resolver = MetadataResolver(nautobot_service)
```

### Pure Functions vs. Services

**Pure Functions** (no dependencies, stateless):
```python
from services.nautobot.common import is_valid_uuid, validate_ip_address, normalize_tags

# Can be called directly - no service instance needed
if is_valid_uuid(some_id):
    tags = normalize_tags("tag1,tag2,tag3")
```

**Resolvers** (read-only, injected with NautobotService):
```python
from services.nautobot.resolvers import DeviceResolver

resolver = DeviceResolver(nautobot_service)
device_id = await resolver.resolve_device_by_name("router1")
```

**Managers** (create/update, injected with dependencies):
```python
from services.nautobot.managers import IPManager
from services.nautobot.resolvers import NetworkResolver, MetadataResolver

network_resolver = NetworkResolver(nautobot_service)
metadata_resolver = MetadataResolver(nautobot_service)

ip_manager = IPManager(nautobot_service, network_resolver, metadata_resolver)
ip_id = await ip_manager.ensure_ip_address_exists(...)
```

### When to Create New Nautobot Services

1. **Add to existing resolver** if it's a simple ID/name lookup
2. **Add to existing manager** if it's CRUD for an existing resource type
3. **Create new resolver** if you need a new domain of lookups (e.g., `VLANResolver`)
4. **Create new manager** if you need lifecycle management for a new resource type
5. **Update `devices/common.py`** to expose new resolver/manager methods through the facade

### DO:
- ✅ Use `DeviceCommonService` facade for device operations (simplifies dependency management)
- ✅ Use pure functions from `common/` for validation/transformation
- ✅ Follow Single Responsibility Principle in resolvers/managers
- ✅ Use BaseResolver for common GraphQL patterns
- ✅ Add type hints to all functions
- ✅ Use direct injection when you need only 1-2 specific components
- ✅ Always use type hints in constructor; All manager constructors use the `TYPE_CHECKING` pattern:

### DON'T:
- ❌ Put business logic in resolvers (read-only only)
- ❌ Bypass managers for create/update operations
- ❌ Create monolithic service classes
- ❌ Mix validation logic with API calls

## Key Patterns Summary

**Backend:**
- Repository pattern for data access (local PostgreSQL)
- Resolver + Manager pattern for external APIs (Nautobot, CheckMK)
- Service layer for business logic
- Thin routers that delegate to services
- Dependency injection for auth/permissions
- SQLAlchemy ORM/Core for runtime data access; repository `text()` only as documented in `doc/refactoring/REFACTORING_RAW_SQL.md` §3

**Frontend:**
- Feature-based organization
- Server Components by default
- API calls via `/api/proxy/*`
- TanStack Query for server state (data fetching, caching, mutations)
- Zustand for client-only state (UI state, preferences)
- Shadcn UI for all components
- react-hook-form + zod for forms

**Database:**
- Single PostgreSQL database
- use complete migration framework to migrate database (./doc/MIGRATION_SYSTEM.md)
- Models split by domain in `/backend/core/models/` (all exported from `__init__.py`)
- Connection pooling + health checks

**Authentication:**
- JWT tokens in cookies
- Permission format: `resource:action`
- Backend: `Depends(require_permission("resource", "action"))`
- Frontend: Check `hasPermission(user, "resource", "action")` from `lib/permissions.ts`

## INCORRECT Practices (NEVER DO)

**Backend:**
- ❌ Creating SQLite databases for **production** (in-memory SQLite in unit tests is allowed; see Database Requirements above)
- ❌ Calling `sqlalchemy.text()` from routers, services, or tasks, or composing runtime values into SQL via string concatenation / f-strings (repository policy: `doc/refactoring/REFACTORING_RAW_SQL.md` §3)
- ❌ Bypassing repository pattern for local database access
- ❌ Business logic in routers
- ❌ Creating monolithic God Object services (note: DeviceCommonService is a facade, not a God Object)
- ❌ Mixing validation/transformation logic with API calls
- ❌ using f-string in Logging
- ❌ Embedding raw exception text (`str(e)`, `{exc}`, f-strings interpolating exceptions, etc.) in `HTTPException(detail=…)` for any **5xx** response. Use `core.safe_http_errors.raise_internal_server_error` and let the client see only `{message, error_id}` (optionally pass `status_code` for sanitized 502/503 responses).

**Frontend:**
- ❌ Placing components at `/components/` root without feature grouping
- ❌ Direct backend API calls from frontend
- ❌ Inline GraphQL queries in components
- ❌ Building UI from scratch instead of using Shadcn
- ❌ Using inline array/object literals in default params
- ❌ Custom hooks without memoized returns
- ❌ Missing or incomplete useEffect dependencies
- ❌ Manual `useState + useEffect` for server data (use TanStack Query)
- ❌ Inline query keys (always use `queryKeys` factory)
- ❌ Storing query data in `useState` (use `useMemo` for derived state)
- ❌ Forgetting to invalidate cache after mutations

## Suggested CLAUDE.md Additions

## Task Completion

When removing features or debugging issues, always complete the full removal/fix cycle including: 1) Remove all related code, 2) Update configuration files, 3) Clean up imports/dependencies, 4) Verify no references remain with grep

## Python Conventions

For Python/Celery projects: Always add inline documentation comments when modifying queue configurations, task decorators, or worker settings


