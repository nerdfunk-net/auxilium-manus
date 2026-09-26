# Backend Architecture

## Nautobot Services Architecture

**IMPORTANT:** Nautobot services wrap an **external API client** (not local database),
so the traditional Repository pattern doesn't apply. Use a modular service layer with
dependency injection.

### Directory Structure
```
backend/services/nautobot/
├── client.py                  # NautobotService API client (GraphQL + REST)
├── common/                    # Pure functions (no dependencies)
│   ├── validators.py          # is_valid_uuid, validate_ip_address, etc.
│   ├── utils.py               # flatten_nested_fields, normalize_tags, etc.
│   └── exceptions.py          # Custom exception hierarchy
├── resolvers/                 # ID/UUID resolution (read-only)
│   ├── base_resolver.py       # Shared GraphQL query logic
│   ├── device_resolver.py     # Device & device-type resolution
│   ├── metadata_resolver.py   # Status, role, platform, location
│   └── network_resolver.py    # IP, interface, namespace, prefix
├── managers/                  # Resource lifecycle (create/update)
│   ├── ip_manager.py
│   ├── interface_manager.py
│   ├── prefix_manager.py
│   └── device_manager.py
└── devices/
    ├── common.py              # Unified facade (recommended for device operations)
    ├── query.py
    ├── attribute_bag.py
    ├── types.py
    ├── creation.py
    ├── update.py
    └── interface_workflow.py
```

### Usage Pattern

**✅ RECOMMENDED — Use Facade for Device Operations:**
```python
from services.nautobot import NautobotService
from services.nautobot.devices.common import DeviceCommonService

class MyDeviceService:
    def __init__(self, nautobot_service: NautobotService):
        self.nautobot = nautobot_service
        self.common = DeviceCommonService(nautobot_service)

    async def my_operation(self):
        device_id = await self.common.resolve_device_by_name("router1")
        status_id = await self.common.resolve_status_id("active")
        ip_id = await self.common.ensure_ip_address_exists(
            ip_address="10.0.0.1/24", namespace_id="...", status_name="active"
        )
```

**✅ ALTERNATIVE — Direct Injection (when you only need 1–2 specific components):**
```python
from services.nautobot.resolvers import DeviceResolver, MetadataResolver

class MySpecializedService:
    def __init__(self, nautobot_service: NautobotService):
        self.device_resolver = DeviceResolver(nautobot_service)
        self.metadata_resolver = MetadataResolver(nautobot_service)
```

### Nautobot DO / DON'T
- ✅ Use `DeviceCommonService` facade for device operations
- ✅ Use pure functions from `common/` for validation/transformation
- ✅ Follow Single Responsibility Principle in resolvers/managers
- ✅ Use `BaseResolver` for common GraphQL patterns
- ✅ All manager constructors use the `TYPE_CHECKING` pattern
- ❌ Put business logic in resolvers (read-only only)
- ❌ Bypass managers for create/update operations
- ❌ Create monolithic service classes
- ❌ Mix validation logic with API calls

### When to Create New Nautobot Services
1. Add to existing resolver for simple ID/name lookups
2. Add to existing manager for CRUD on an existing resource type
3. Create new resolver for a new domain of lookups (e.g., `VLANResolver`)
4. Create new manager for lifecycle management of a new resource type
5. Update `devices/common.py` to expose new methods through the facade

---

## Git Repository Architecture

**IMPORTANT:** There is exactly **one** git configuration system: the `GitRepository` DB
model. A Settings-KV-backed system (`sources.git.*`) was removed 2026-08-28 — never re-add
a KV-based or ad-hoc-string git config path. Any feature that needs a git remote creates
or uses a `GitRepository` row.

### Core Pieces

| Component | Purpose |
|-----------|---------|
| `backend/core/models/git.py` | `GitRepository` SQLAlchemy model: `name`, `category`, `url`, `branch`, `auth_type`, `credential_name`, `path`, `verify_ssl`, `git_author_name/email`, `is_active`, `sync_status` |
| `backend/models/git_repositories.py` | Pydantic models; `GitCategory` enum (`device_configs`, `cockpit_configs`, `templates`, `agent`, `csv_imports`, `csv_exports`, `workflows`, `workflow_steps`, `cicd_pipeline`, `batfish`); `GitAuthType` enum |
| `backend/services/git/repository_service.py` | `GitRepositoryService`: CRUD for `git_repositories` table; `_to_dict()` is the canonical shape every git operation consumes |
| `backend/services/git/service.py` | `GitService` (via `service_factory.build_git_service()`): clone/pull/push/commit/fetch. Takes a plain `repository: dict`, not an ORM object |
| `backend/services/git/auth.py` | `GitAuthenticationService`: resolves `credential_name` → username/token/ssh_key from `Credential` table. **Only `visibility="global"` credentials resolve in background jobs** |
| `backend/services/git/sync.py` | `clone_or_pull` / `remove_and_clone`: "ensure local working tree exists" helpers |
| `backend/services/git/repo_lock.py` | `git_repo_lock(git_repository_id)` — per-repository Redis advisory lock **every git-mutating step must hold** across its `GitService` calls |
| `backend/workflow_steps/common/git_repository_loader.py` | `load_git_repository(repository_id: int)` — the **one** resolver every workflow step uses to turn a `git_repository_id` config value into a `GitService`-ready dict |

### Workflow Steps and Git
Every git-consuming step stores `git_repository_id: int` in its plugin config — never a
string source id. Resolve it via `workflow_steps.common.git_repository_loader.load_git_repository`.

`git-clone` / `git-pull` also accept `use_change_request_branch: bool` — when the run was
dispatched by a change-request approval, the step targets `manus/cr-{id}`. See `doc/CICD_PIPELINE.md`.

### Frontend
Settings → **Git Repositories**
(`frontend/src/components/features/settings/components/git-repositories-settings-canvas.tsx`)
is the only UI for creating/editing repositories.
`workflow-steps/shared/git-repository-select-dialog.tsx` (`GitRepositorySelectDialog`) is
the only picker workflow steps use.

### Git Repository DO / DON'T
- ✅ Add a `GitRepository` row for any new git-backed feature; reuse an existing `GitCategory` or extend the enum
- ✅ Reuse `GitService` / `GitRepositoryService` / `git_repository_loader`
- ✅ Hold `repo_lock.py`'s per-repository lock across any sequence of mutating `GitService` calls
- ✅ Reference credentials by name via `credential_name` on the `GitRepository` row
- ❌ Add a `sources.<type>.*`-style Settings KV entry for git configuration
- ❌ Store a git source as a bare string id/URL in workflow step config — always `git_repository_id: int`
- ❌ Write a second "resolve git config" helper — extend `git_repository_loader.py` instead

---

## Backend INCORRECT Practices

- ❌ Creating SQLite databases for production (unit test in-memory SQLite is OK when not using PG-only features)
- ❌ Calling `sqlalchemy.text()` from routers, services, or Hatchet workers
- ❌ Composing runtime values into SQL via f-strings or string concatenation
- ❌ Bypassing repository layer for local database access
- ❌ Business logic in routers
- ❌ Creating monolithic God Object services
- ❌ Mixing validation/transformation logic with API calls
- ❌ Using f-strings in logging calls
- ❌ Embedding raw exception text (`str(e)`, `{exc}`, etc.) in `HTTPException(detail=…)` for 5xx responses — use `core.safe_http_errors.raise_internal_server_error`
- ❌ Creating a second git-configuration storage path (Settings KV, ad-hoc string ids) instead of a `GitRepository` row
