# Refactoring Plan — FABLE-ANALYSIS Prioritized Recommendations

> Based on: `doc/FABLE-ANALYSIS.md` §8 ("Prioritized Recommendations"), which references §§3–7 for full detail.
> Date: 2026-08-02
> Status: Steps 1–11 DONE (implemented, tests + regression guards green). Step 12 (testing debt) and
> Step 13 (function decomposition) are sustained/opportunistic work, intentionally not done in this pass.

This plan expands each of the 9 items in `FABLE-ANALYSIS.md` §8 into a concrete, self-contained diff. Every "Code before" block was read from the file at the stated lines during the analysis; every "Code after" block is the exact intended replacement. No further source investigation should be needed to execute steps 1–11. Steps 12–13 (testing debt, function decomposition) are inherently open-ended — they get a precise target list and a worked pattern instead of a line-for-line diff, and are explicitly the last, lowest-priority, "opportunistic" work.

---

## Implementation Order

Grouped by risk and dependency; each group is independently deployable.

| # | Step | Analysis ref | Risk |
|---|---|---|---|
| 1 | Delete confirmed-dead Nautobot modules | §6 / Rec. 4 | none — zero callers verified |
| 2 | Fix CLAUDE.md documentation drift | §3.5 / Rec. 8 | none — docs only |
| 3 | Replace deprecated `asyncio.get_event_loop()` / `datetime.utcnow()` / naive `datetime.now()` | §5.1 / Rec. 6 | none — behavior-preserving on 3.10+ |
| 4 | Add `is_active` check to `require_permission`/`require_any_permission`/`require_all_permissions`/`require_role` | §4.3 / Rec. 3 | low |
| 5 | Validate `artifact_id` as UUID in the run-artifact endpoint | §4.4 / Rec. 3 | low |
| 6 | Bound the refresh-token window | §4.1 / Rec. 1 | low — new config default is permissive (24h) |
| 7 | Extract `services/execution/graph.py`; add cycle detection to `StepRunner` **and** `WorkflowService` | §4.2, §5.3 / Rec. 2, 9 | medium — touches the execution engine |
| 8 | `SettingsService` domain exception for the worker path; drop `fastapi` import from `get_from_config` executor | §3.1 / Rec. 5 | low |
| 9 | Move `workflow_steps/common/{attribute_path,attribute_regex,cisco_config_parsing}.py` into `services/` | §3.2 / Rec. 5 | medium — 22 files touched, purely mechanical |
| 10 | Replace module-level service singletons in `routers/git/files.py` and `routers/oidc.py` with `Depends()` | §3.3 | low |
| 11 | Fix `RunService.get_run_artifact` inline construction / function-local imports | §3.4 | low |
| 12 | Testing debt: git write path, Nautobot mutation path, integration suite | §7 / Rec. 7 | n/a — sustained effort, not a single patch |
| 13 | Decompose the largest `execute()` / service functions | §5.2 / Rec. 9 | n/a — opportunistic, do last |

Run the full test suite and all four regression guards after **every** step:

```bash
cd backend
source ../.venv/bin/activate
ruff check .
python -m pytest -q
python scripts/check_asyncio_run.py
python scripts/check_http_500_leaks.py
python scripts/check_router_repositories.py
python scripts/check_text_sql.py
```

---

## Step 1: Delete Confirmed-Dead Nautobot Modules (Rec. 4, §6)

**What:** Remove five dead items with zero callers outside their own definition/re-export (verified via AST import-graph scan; corroborated by 0–10% test coverage on all of them).

**Why:** CLAUDE.md's task-completion rule requires full removal (code + re-exports + a final grep), not just marking things unused.

**Files removed:**
- `backend/services/nautobot/managers/vm_manager.py` (466 lines, `VirtualMachineManager`)
- `backend/services/nautobot/managers/cluster_manager.py` (`ClusterManager`)
- `backend/services/nautobot/resolvers/cluster_resolver.py` (`ClusterResolver`)
- `backend/services/nautobot/common/interface_types.py` (`normalize_interface_type`, `VALID_INTERFACE_TYPES`)
- `backend/services/validation/` (empty directory — contains only `__pycache__`)

**Files edited:** the three re-exporting `__init__.py` files.

### Code before — `backend/services/nautobot/managers/__init__.py`

```python
"""
Nautobot managers for resource lifecycle management.

This package contains manager classes for creating, updating, and managing
Nautobot resources (IPs, Interfaces, Prefixes, Devices).
"""

from .cluster_manager import ClusterManager
from .device_manager import DeviceManager
from .interface_manager import InterfaceManager
from .ip_manager import IPManager
from .prefix_manager import PrefixManager
from .vm_manager import VirtualMachineManager

__all__ = [
    "IPManager",
    "InterfaceManager",
    "PrefixManager",
    "DeviceManager",
    "VirtualMachineManager",
    "ClusterManager",
]
```

### Code after — `backend/services/nautobot/managers/__init__.py`

```python
"""
Nautobot managers for resource lifecycle management.

This package contains manager classes for creating, updating, and managing
Nautobot resources (IPs, Interfaces, Prefixes, Devices).
"""

from .device_manager import DeviceManager
from .interface_manager import InterfaceManager
from .ip_manager import IPManager
from .prefix_manager import PrefixManager

__all__ = [
    "IPManager",
    "InterfaceManager",
    "PrefixManager",
    "DeviceManager",
]
```

### Code before — `backend/services/nautobot/resolvers/__init__.py`

```python
"""
Nautobot resolvers for ID/UUID resolution.

This package contains resolver classes for looking up UUIDs from names
and other identifiers.
"""

from .base_resolver import BaseResolver
from .cluster_resolver import ClusterResolver
from .device_resolver import DeviceResolver
from .metadata_resolver import MetadataResolver
from .network_resolver import NetworkResolver

__all__ = [
    "BaseResolver",
    "DeviceResolver",
    "MetadataResolver",
    "NetworkResolver",
    "ClusterResolver",
]
```

### Code after — `backend/services/nautobot/resolvers/__init__.py`

```python
"""
Nautobot resolvers for ID/UUID resolution.

This package contains resolver classes for looking up UUIDs from names
and other identifiers.
"""

from .base_resolver import BaseResolver
from .device_resolver import DeviceResolver
from .metadata_resolver import MetadataResolver
from .network_resolver import NetworkResolver

__all__ = [
    "BaseResolver",
    "DeviceResolver",
    "MetadataResolver",
    "NetworkResolver",
]
```

### Code before — `backend/services/nautobot/common/__init__.py`

```python
"""
Common utilities for Nautobot operations.

This package contains pure functions and exception classes used across
Nautobot service modules.
"""

from .exceptions import (
    NautobotAPIError,
    NautobotDuplicateResourceError,
    NautobotError,
    NautobotResourceNotFoundError,
    NautobotValidationError,
    handle_already_exists_error,
    is_duplicate_error,
)
from .interface_types import (
    VALID_INTERFACE_TYPES,
    normalize_interface_type,
)
from .utils import (
    extract_id_from_url,
    extract_nested_value,
    flatten_nested_fields,
    normalize_tags,
    prepare_update_data,
)
from .validators import (
    is_valid_uuid,
    validate_cidr,
    validate_ip_address,
    validate_mac_address,
    validate_required_fields,
)

__all__ = [
    # Validators
    "is_valid_uuid",
    "validate_ip_address",
    "validate_mac_address",
    "validate_cidr",
    "validate_required_fields",
    # Utils
    "flatten_nested_fields",
    "extract_nested_value",
    "normalize_tags",
    "prepare_update_data",
    "extract_id_from_url",
    # Exceptions
    "NautobotError",
    "NautobotValidationError",
    "NautobotResourceNotFoundError",
    "NautobotDuplicateResourceError",
    "NautobotAPIError",
    "is_duplicate_error",
    "handle_already_exists_error",
    # Interface types
    "VALID_INTERFACE_TYPES",
    "normalize_interface_type",
]
```

### Code after — `backend/services/nautobot/common/__init__.py`

```python
"""
Common utilities for Nautobot operations.

This package contains pure functions and exception classes used across
Nautobot service modules.
"""

from .exceptions import (
    NautobotAPIError,
    NautobotDuplicateResourceError,
    NautobotError,
    NautobotResourceNotFoundError,
    NautobotValidationError,
    handle_already_exists_error,
    is_duplicate_error,
)
from .utils import (
    extract_id_from_url,
    extract_nested_value,
    flatten_nested_fields,
    normalize_tags,
    prepare_update_data,
)
from .validators import (
    is_valid_uuid,
    validate_cidr,
    validate_ip_address,
    validate_mac_address,
    validate_required_fields,
)

__all__ = [
    # Validators
    "is_valid_uuid",
    "validate_ip_address",
    "validate_mac_address",
    "validate_cidr",
    "validate_required_fields",
    # Utils
    "flatten_nested_fields",
    "extract_nested_value",
    "normalize_tags",
    "prepare_update_data",
    "extract_id_from_url",
    # Exceptions
    "NautobotError",
    "NautobotValidationError",
    "NautobotResourceNotFoundError",
    "NautobotDuplicateResourceError",
    "NautobotAPIError",
    "is_duplicate_error",
    "handle_already_exists_error",
]
```

### Commands

```bash
cd backend
git rm services/nautobot/managers/vm_manager.py
git rm services/nautobot/managers/cluster_manager.py
git rm services/nautobot/resolvers/cluster_resolver.py
git rm services/nautobot/common/interface_types.py
git rm -r services/validation
```

Then apply the three `__init__.py` edits above.

### Verification

```bash
# Confirm nothing still references the removed names (should print nothing):
grep -rn "VirtualMachineManager\|ClusterManager\|ClusterResolver\|normalize_interface_type\|VALID_INTERFACE_TYPES" \
  --include="*.py" --exclude-dir=__pycache__ backend/

python -m pytest -q   # 641 tests must still pass — none reference these symbols
ruff check .
```

---

## Step 2: Fix CLAUDE.md Documentation Drift (Rec. 8, §3.5)

**What:** Three inaccuracies in `/Users/mp/programming/auxilium-manus/CLAUDE.md`.

**Why:** CLAUDE.md is checked into the repo and treated as authoritative instructions; stale claims about Python version and file layout will mislead future work.

### Code before — CLAUDE.md, Tech Stack section

```markdown
**Backend:** FastAPI, Python 3.9+, PostgreSQL, SQLAlchemy, Redis, JWT auth, Hatchet, Netmiko, GitPython
```

### Code after

```markdown
**Backend:** FastAPI, Python 3.12+, PostgreSQL, SQLAlchemy, Redis, JWT auth, Hatchet, Netmiko, GitPython
```

Evidence: `backend/repositories/base.py:13` uses PEP 695 generic class syntax (`class BaseRepository[T]:`), which requires Python ≥3.12; the project venv runs Python 3.14; `datetime.UTC` (3.11+) is used throughout.

### Code before — CLAUDE.md, Nautobot Services Architecture → Directory Structure

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

### Code after

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
    ├── query.py               # Device query/lookup workflows
    ├── attribute_bag.py        # Device attribute-bag assembly
    ├── types.py                # Shared request/result dataclasses
    ├── creation.py             # Device creation workflows
    ├── update.py               # Device update workflows
    └── interface_workflow.py   # Interface create/update workflows
```

> Note: this listing assumes Step 1 has already removed `managers/vm_manager.py`, `managers/cluster_manager.py`, and `resolvers/cluster_resolver.py` — if applying Step 2 before Step 1, omit those from the directory tree above but do not add them back to CLAUDE.md.

### Verification

No code executes; review by reading the updated section back.

---

## Step 3: Modernize Deprecated APIs (Rec. 6, §5.1)

**What:** Replace `asyncio.get_event_loop()` (deprecated since 3.10; emits `DeprecationWarning`/misbehaves when there is no running loop) with `asyncio.get_running_loop()`, and replace `datetime.utcnow()` / naive `datetime.now()` with `datetime.now(UTC)`.

**Why:** All call sites are already inside a running coroutine (an `async def`), so `get_running_loop()` is a pure drop-in — same returned object, same `.run_in_executor()` usage. `utcnow()` is deprecated in 3.12 and returns a naive datetime, which is inconsistent with the rest of the codebase's `datetime.now(UTC)` convention.

### 3a. `asyncio.get_event_loop()` → `asyncio.get_running_loop()`

**Files and exact lines (8 occurrences, all structurally identical):**

| File | Line |
|---|---|
| `backend/routers/sources/git/ops.py` | 86 |
| `backend/routers/sources/git/ops.py` | 131 |
| `backend/routers/sources/git/ops.py` | 172 |
| `backend/routers/sources/git/ops.py` | 231 |
| `backend/routers/sources/git/ops.py` | 253 |
| `backend/workflow_steps/set_default_attributes/executor.py` | 108 |
| `backend/workflow_steps/get_git_devices/executor.py` | 67 |
| `backend/workflow_steps/get_from_config/executor.py` | 68 |

### Code before (representative — `backend/routers/sources/git/ops.py:86`)

```python
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
```

### Code after

```python
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
```

The other 7 occurrences follow the identical `loop = asyncio.get_event_loop()` → `loop = asyncio.get_running_loop()` substitution (two of them are inlined as `await asyncio.get_event_loop().run_in_executor(...)` → `await asyncio.get_running_loop().run_in_executor(...)`, same rule, no other change). Apply as a literal string replacement across all 8 lines:

```bash
grep -rl 'asyncio\.get_event_loop()' --include='*.py' backend/routers backend/workflow_steps \
  | xargs sed -i '' 's/asyncio\.get_event_loop()/asyncio.get_running_loop()/g'
```

(On Linux, drop the empty `''` after `-i`.)

### 3b. `datetime.utcnow()` → `datetime.now(UTC)`

**File:** `backend/routers/sources/nautobot/crud.py:168`, with import at line 6.

### Code before

```python
# backend/routers/sources/nautobot/crud.py:6
from datetime import datetime
```
```python
# backend/routers/sources/nautobot/crud.py:168
                "exportedAt": datetime.utcnow().isoformat() + "Z",
```

### Code after

```python
# backend/routers/sources/nautobot/crud.py:6
from datetime import UTC, datetime
```
```python
# backend/routers/sources/nautobot/crud.py:168
                "exportedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
```

> `datetime.now(UTC).isoformat()` produces `...+00:00`, not a bare `Z` suffix like the naive-`utcnow()` version did — the `.replace(...)` keeps the emitted string format (`...Z`) byte-for-byte identical to today's output, so this is a behavior-preserving fix, not just a type change.

### 3c. Naive `datetime.now()` → `datetime.now(UTC)`

**File:** `backend/services/git/debug_service.py`, import at line 8, naive calls at lines 90, 298, 318.

### Code before

```python
# backend/services/git/debug_service.py:8
from datetime import datetime
```
```python
# line 90
            f"Timestamp: {datetime.now().isoformat()}\n"
```
```python
# line 298
                f"Timestamp: {datetime.now().isoformat()}\n"
```
```python
# line 318
                commit_message = f"Debug push test - {datetime.now().isoformat()}"
```

### Code after

```python
# backend/services/git/debug_service.py:8
from datetime import UTC, datetime
```
```python
# line 90
            f"Timestamp: {datetime.now(UTC).isoformat()}\n"
```
```python
# line 298
                f"Timestamp: {datetime.now(UTC).isoformat()}\n"
```
```python
# line 318
                commit_message = f"Debug push test - {datetime.now(UTC).isoformat()}"
```

These three are debug-file content strings only (not comparisons or persisted timestamps), so no downstream consumer depends on the naive-vs-aware distinction.

### Verification

```bash
cd backend
ruff check .
python -m pytest -q tests/unit -k "git_debug or sources_git or set_default_attributes or get_git_devices or get_from_config or nautobot"
python -m pytest -q   # full suite, must still be 641 passed
```

---

## Step 4: `is_active` Check in Permission/Role Dependencies (Rec. 3, §4.3)

**What:** `require_permission`, `require_any_permission`, `require_all_permissions`, and `require_role` in `core/auth.py` resolve permissions via `RBACService`, which never checks `User.is_active`. `get_current_user` does check it, but any route protected *only* by a `require_permission(...)`-style dependency (not also `get_current_user`) authorizes a deactivated user until their JWT naturally expires.

**Why:** Deactivating a user must take effect immediately at the permission-check layer, not just at the `get_current_user` layer — routes that use `require_permission` as their sole auth dependency (the common pattern for `dependencies=[Depends(require_permission(...))]` at the router level) currently don't re-check activity status at all.

**File:** `backend/core/auth.py`

### Code before

```python
def _require_user_id(token_payload: dict[str, Any]) -> int:
    user_id = token_payload.get("user_id")

    if not isinstance(user_id, int):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers=AUTHENTICATE_HEADER,
        )

    return user_id


def require_permission(resource: str, action: str):
    def permission_checker(
        token_payload: dict[str, Any] = Depends(verify_token),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        user_id = _require_user_id(token_payload)

        if not RBACService(db).has_permission(user_id, resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {resource}:{action} required",
            )

        return token_payload

    return permission_checker


def require_any_permission(checks: list[tuple[str, str]]):
    def permission_checker(
        token_payload: dict[str, Any] = Depends(verify_token),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        user_id = _require_user_id(token_payload)

        if not RBACService(db).check_any_permission(user_id, checks):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: none of the required permissions are granted",
            )

        return token_payload

    return permission_checker


def require_all_permissions(checks: list[tuple[str, str]]):
    def permission_checker(
        token_payload: dict[str, Any] = Depends(verify_token),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        user_id = _require_user_id(token_payload)

        if not RBACService(db).check_all_permissions(user_id, checks):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: not all required permissions are granted",
            )

        return token_payload

    return permission_checker


def require_role(role_name: str):
    def role_checker(
        token_payload: dict[str, Any] = Depends(verify_token),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        user_id = _require_user_id(token_payload)

        if not RBACService(db).has_role(user_id, role_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role denied: {role_name} required",
            )

        return token_payload

    return role_checker
```

### Code after

```python
def _require_user_id(token_payload: dict[str, Any]) -> int:
    user_id = token_payload.get("user_id")

    if not isinstance(user_id, int):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers=AUTHENTICATE_HEADER,
        )

    return user_id


def _require_active_user_id(token_payload: dict[str, Any], db: Session) -> int:
    """Like ``_require_user_id``, but also rejects deactivated users.

    ``get_current_user`` already does this check, but permission/role
    dependencies are frequently used on their own (e.g. router-level
    ``dependencies=[Depends(require_permission(...))]``) without
    ``get_current_user`` in the chain, so deactivating a user must be
    enforced here too — otherwise a still-valid JWT keeps working for a
    deactivated account until it naturally expires.
    """
    user_id = _require_user_id(token_payload)
    user = UserRepository(db).get_by_id(user_id)

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers=AUTHENTICATE_HEADER,
        )

    return user_id


def require_permission(resource: str, action: str):
    def permission_checker(
        token_payload: dict[str, Any] = Depends(verify_token),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        user_id = _require_active_user_id(token_payload, db)

        if not RBACService(db).has_permission(user_id, resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {resource}:{action} required",
            )

        return token_payload

    return permission_checker


def require_any_permission(checks: list[tuple[str, str]]):
    def permission_checker(
        token_payload: dict[str, Any] = Depends(verify_token),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        user_id = _require_active_user_id(token_payload, db)

        if not RBACService(db).check_any_permission(user_id, checks):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: none of the required permissions are granted",
            )

        return token_payload

    return permission_checker


def require_all_permissions(checks: list[tuple[str, str]]):
    def permission_checker(
        token_payload: dict[str, Any] = Depends(verify_token),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        user_id = _require_active_user_id(token_payload, db)

        if not RBACService(db).check_all_permissions(user_id, checks):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: not all required permissions are granted",
            )

        return token_payload

    return permission_checker


def require_role(role_name: str):
    def role_checker(
        token_payload: dict[str, Any] = Depends(verify_token),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        user_id = _require_active_user_id(token_payload, db)

        if not RBACService(db).has_role(user_id, role_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role denied: {role_name} required",
            )

        return token_payload

    return role_checker
```

`UserRepository` is already imported at the top of `core/auth.py` (line 14: `from repositories.user_repository import UserRepository`) — no new import needed. `_require_user_id` is kept (unchanged) because it is not dead: nothing else references it currently, but keeping the narrower helper makes the diff minimal and documents the distinction; if preferred, it can be inlined into `_require_active_user_id` instead — functionally equivalent, slightly less diff-friendly.

This adds one `SELECT` per permission check (previously zero — `RBACService` already does 2–3 queries per check, so this is a proportionally small increase, not a new query pattern).

### New test — `backend/tests/unit/test_require_permission_inactive_user.py`

```python
"""require_permission (and its siblings) must reject deactivated users even
when get_current_user is not in the dependency chain — see FABLE-ANALYSIS.md §4.3."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from core.auth import require_all_permissions, require_any_permission, require_permission, require_role
from core.models.users import User


def _user(is_active: bool) -> User:
    user = User(username="alice", password_hash="hash", is_active=is_active)
    user.id = 1
    return user


@pytest.mark.parametrize(
    "checker_factory",
    [
        lambda: require_permission("workflows", "read"),
        lambda: require_any_permission([("workflows", "read")]),
        lambda: require_all_permissions([("workflows", "read")]),
        lambda: require_role("admin"),
    ],
)
def test_rejects_deactivated_user_even_with_valid_permission(monkeypatch, checker_factory) -> None:
    monkeypatch.setattr("core.auth.RBACService.has_permission", lambda self, *a: True)
    monkeypatch.setattr("core.auth.RBACService.check_any_permission", lambda self, *a: True)
    monkeypatch.setattr("core.auth.RBACService.check_all_permissions", lambda self, *a: True)
    monkeypatch.setattr("core.auth.RBACService.has_role", lambda self, *a: True)
    monkeypatch.setattr(
        "core.auth.UserRepository.get_by_id",
        lambda self, user_id: _user(is_active=False),
    )

    checker = checker_factory()
    with pytest.raises(HTTPException) as exc_info:
        checker({"user_id": 1}, MagicMock())

    assert exc_info.value.status_code == 401
```

### Verification

```bash
cd backend
python -m pytest -q tests/unit/test_require_permission_inactive_user.py
python -m pytest -q   # full suite — confirm no existing test assumed require_permission never touches the DB for is_active
python scripts/check_router_repositories.py   # core/auth.py is not under routers/, so unaffected
```

---

## Step 5: Validate `artifact_id` as UUID (Rec. 3, §4.4)

**What:** `GET /workflows/runs/{run_id}/artifacts/{artifact_id}` accepts `artifact_id` as a raw `str`, which is then interpolated into a filesystem path (`FilesystemArtifactService._content_path`). Artifact IDs are always `uuid4()` at creation time — enforce that shape at the boundary instead of relying on incidental protections (routing can't pass `/`, and `get_for_run` requires a `run_id` match in the metadata file).

**Why:** "Validate at system boundaries" (CLAUDE.md, `common/coding-style.md`). This is currently accidental safety, not designed safety.

**Files:** `backend/routers/workflow_runs.py`, `backend/services/execution/run_service.py`

### Code before — `backend/routers/workflow_runs.py`

```python
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from models.artifacts import ArtifactContentResponse
from models.runs import WorkflowRunCreate, WorkflowRunListResponse, WorkflowRunResponse
from services.execution.run_service import RunService
```

```python
@router.get(
    "/runs/{run_id}/artifacts/{artifact_id}",
    response_model=ArtifactContentResponse,
    dependencies=[Depends(require_permission("workflow_runs", "read"))],
)
async def get_run_artifact(
    run_id: int,
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    service: RunService = Depends(_service),
) -> ArtifactContentResponse:
    return service.get_run_artifact(
        run_id=run_id,
        artifact_id=artifact_id,
        user_id=current_user.id,
    )
```

### Code after — `backend/routers/workflow_runs.py`

```python
from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from models.artifacts import ArtifactContentResponse
from models.runs import WorkflowRunCreate, WorkflowRunListResponse, WorkflowRunResponse
from services.execution.run_service import RunService
```

```python
@router.get(
    "/runs/{run_id}/artifacts/{artifact_id}",
    response_model=ArtifactContentResponse,
    dependencies=[Depends(require_permission("workflow_runs", "read"))],
)
async def get_run_artifact(
    run_id: int,
    artifact_id: UUID,
    current_user: User = Depends(get_current_user),
    service: RunService = Depends(_service),
) -> ArtifactContentResponse:
    return service.get_run_artifact(
        run_id=run_id,
        artifact_id=str(artifact_id),
        user_id=current_user.id,
    )
```

FastAPI validates the path parameter against `UUID` automatically and returns `422 Unprocessable Entity` for a malformed value before the handler body even runs — no manual validation code needed. `run_service.get_run_artifact`'s signature (`artifact_id: str`) and `FilesystemArtifactService.get_for_run` are unchanged; the router converts back to `str` at the call boundary.

### Verification

```bash
cd backend
python -m pytest -q tests/unit -k "artifact or run_service or workflow_runs"
python -m pytest -q
```

Manual check (server running): `GET /api/workflows/runs/1/artifacts/not-a-uuid` should now return `422` instead of reaching `FilesystemArtifactService` at all.

---

## Step 6: Bound the Refresh-Token Window (Rec. 1, §4.1 — HIGH)

**What:** `AuthService.refresh_access_token` decodes with `options={"verify_exp": False}` and has no limit on how long ago the token expired. Add a `REFRESH_TOKEN_MAX_AGE_HOURS` setting (default 24h) and reject refresh attempts on tokens whose `exp` claim is older than that window.

**Why:** Without this, a leaked/stolen access token is a permanent credential as long as the user account stays active — `ACCESS_TOKEN_EXPIRE_MINUTES` provides no real security boundary today, only a keepalive cadence. See `FABLE-ANALYSIS.md` §4.1 for full reasoning.

**Files:** `backend/core/config.py`, `backend/services/auth/auth_service.py`

### Code before — `backend/core/config.py` (attribute declarations, lines 24–25)

```python
    secret_key: str
    access_token_expire_minutes: int
```

### Code after

```python
    secret_key: str
    access_token_expire_minutes: int
    refresh_token_max_age_hours: int
```

### Code before — `backend/core/config.py` (`__init__`, lines 64–65)

```python
        self.secret_key = self._get_secret_key()
        self.access_token_expire_minutes = self._get_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60)
```

### Code after

```python
        self.secret_key = self._get_secret_key()
        self.access_token_expire_minutes = self._get_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60)
        self.refresh_token_max_age_hours = self._get_int("REFRESH_TOKEN_MAX_AGE_HOURS", 24)
        self._validate_refresh_token_max_age()
```

### Code before — `backend/core/config.py` (validation methods, lines 108–112)

```python
    def _validate_run_retention(self) -> None:
        if self.run_retention_days < 1:
            raise RuntimeError("RUN_RETENTION_DAYS must be at least 1")
        if self.run_retention_batch_size < 1:
            raise RuntimeError("RUN_RETENTION_BATCH_SIZE must be at least 1")
```

### Code after (new method added alongside the existing one)

```python
    def _validate_run_retention(self) -> None:
        if self.run_retention_days < 1:
            raise RuntimeError("RUN_RETENTION_DAYS must be at least 1")
        if self.run_retention_batch_size < 1:
            raise RuntimeError("RUN_RETENTION_BATCH_SIZE must be at least 1")

    def _validate_refresh_token_max_age(self) -> None:
        if self.refresh_token_max_age_hours < 1:
            raise RuntimeError("REFRESH_TOKEN_MAX_AGE_HOURS must be at least 1")
```

### Code before — `backend/services/auth/auth_service.py`

```python
    def refresh_access_token(self, token: str) -> tuple[User, str, int]:
        """Re-issue an access token from a signed JWT, allowing expired tokens."""
        try:
            payload = jwt.decode(
                token,
                settings.secret_key,
                algorithms=["HS256"],
                options={"verify_exp": False},
            )
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError("Invalid authentication token") from exc

        user_id = payload.get("user_id")
        username = payload.get("sub")
        if not isinstance(user_id, int) or not isinstance(username, str) or not username:
            raise AuthenticationError("Invalid authentication token")

        user = self.users.get_by_id(user_id)
        if user is None or not user.is_active or user.username != username:
            raise AuthenticationError("Invalid authentication token")

        access_token, expires_in = self.create_access_token(user)
        return user, access_token, expires_in
```

### Code after

```python
    def refresh_access_token(self, token: str) -> tuple[User, str, int]:
        """Re-issue an access token from a signed JWT, allowing expired tokens.

        Still rejects tokens whose ``exp`` claim is older than
        ``settings.refresh_token_max_age_hours`` — otherwise a leaked access
        token could be exchanged for a fresh one indefinitely, making
        ACCESS_TOKEN_EXPIRE_MINUTES a no-op security boundary (see
        doc/FABLE-ANALYSIS.md §4.1).
        """
        try:
            payload = jwt.decode(
                token,
                settings.secret_key,
                algorithms=["HS256"],
                options={"verify_exp": False},
            )
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError("Invalid authentication token") from exc

        user_id = payload.get("user_id")
        username = payload.get("sub")
        expires_at_ts = payload.get("exp")
        if (
            not isinstance(user_id, int)
            or not isinstance(username, str)
            or not username
            or not isinstance(expires_at_ts, int | float)
        ):
            raise AuthenticationError("Invalid authentication token")

        expired_since = datetime.now(UTC) - datetime.fromtimestamp(expires_at_ts, UTC)
        if expired_since > timedelta(hours=settings.refresh_token_max_age_hours):
            raise AuthenticationError("Invalid authentication token")

        user = self.users.get_by_id(user_id)
        if user is None or not user.is_active or user.username != username:
            raise AuthenticationError("Invalid authentication token")

        access_token, expires_in = self.create_access_token(user)
        return user, access_token, expires_in
```

`datetime`, `timedelta`, and `UTC` are already imported at the top of `auth_service.py` (`from datetime import UTC, datetime, timedelta`) — no new import needed.

Add the new variable to `backend/.env`-style documentation in CLAUDE.md's Environment Variables section (optional, cosmetic):

```bash
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_MAX_AGE_HOURS=24  # max time since expiry a token can still be refreshed
```

### New test — add to `backend/tests/unit/test_auth_refresh.py`

The existing `_make_expired_token` helper uses `timedelta(minutes=5)`, well inside the new 24h default, so **no existing test changes** — all 5 existing `TestAuthServiceRefresh` cases and all 4 endpoint tests keep passing unmodified. Add:

```python
    def test_refresh_rejects_token_expired_beyond_max_age(self) -> None:
        user = _make_user()
        service = AuthService(MagicMock())
        service.users = MagicMock()
        service.users.get_by_id.return_value = user

        payload = {
            "sub": user.username,
            "user_id": user.id,
            "exp": datetime.now(UTC) - timedelta(hours=settings.refresh_token_max_age_hours, minutes=1),
        }
        stale_token = jwt.encode(payload, settings.secret_key, algorithm="HS256")

        with pytest.raises(AuthenticationError):
            service.refresh_access_token(stale_token)
```

Place it inside `class TestAuthServiceRefresh` (the imports it needs — `settings`, `datetime`, `UTC`, `timedelta`, `jwt`, `pytest`, `AuthenticationError`, `AuthService`, `MagicMock` — are all already imported at the top of the file).

### Verification

```bash
cd backend
python -m pytest -q tests/unit/test_auth_refresh.py -v
python -m pytest -q
```

---

## Step 7: Cycle Detection — `services/execution/graph.py` + `StepRunner` + `WorkflowService` (Rec. 2 & 9, §4.2, §5.3)

**What:** `StepRunner._topological_sort` (Kahn's algorithm) silently drops nodes stuck in a cycle — they never reach in-degree 0, so they're absent from the execution plan, get no `WorkflowStepResult` row, and `execute_all` can return `True` ("success") while part of the graph never ran. There is also no cycle validation anywhere in the workflow save path (`WorkflowService.create_workflow` / `update_workflow`), even though CLAUDE.md claims "the backend validates the graph."

This step also serves §5.3 (`step_runner.py` is 813 lines, 13 over the 800 limit): the graph utilities being extracted are the natural, self-contained unit to pull out, and doing so gives cycle detection one home instead of two copies.

**Why:** One-line-cheap correctness bug with a silent-data-loss failure mode; fixing it in exactly one place (the new `graph.py`) and reusing it from both the runtime engine and the definition-save path closes the gap CLAUDE.md already claims is closed.

**New file:** `backend/services/execution/graph.py`

```python
"""Pure graph utilities shared by StepRunner (execution) and WorkflowService
(definition validation) — topological ordering and downstream-reachability
over the canvas node/edge shape (``{"id": ...}`` nodes, ``{"source", "target"}``
edges).

Extracted from ``services/execution/step_runner.py`` so cycle detection has a
single implementation instead of being duplicated at both call sites — see
doc/FABLE-ANALYSIS.md §4.2 and §5.3.
"""

from __future__ import annotations

from collections import deque
from typing import Any


class GraphCycleError(ValueError):
    """Raised when canvas nodes/edges contain a cycle.

    Subclasses ValueError so both a workflow-step executor (which must raise
    ValueError for configuration problems) and a FastAPI service (which
    translates ValueError-family exceptions to 400s at the router) can handle
    it without a bespoke except clause.
    """


def topological_order(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return *nodes* in dependency order via Kahn's algorithm.

    Raises ``GraphCycleError`` if any node is unreachable by the sort — i.e.
    it (or an ancestor) sits in a cycle. Callers that need canvas-decoration
    filtering (e.g. StepRunner, which excludes non-executable nodes first)
    must do that before calling this function; it treats every entry in
    *nodes* as a node to order.
    """
    node_map = {n["id"]: n for n in nodes if "id" in n}
    in_degree: dict[str, int] = dict.fromkeys(node_map, 0)
    dependents: dict[str, list[str]] = {nid: [] for nid in node_map}

    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src in in_degree and tgt in in_degree:
            in_degree[tgt] += 1
            dependents[src].append(tgt)

    queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
    result: list[dict[str, Any]] = []

    while queue:
        nid = queue.popleft()
        result.append(node_map[nid])
        for dep in dependents[nid]:
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)

    if len(result) != len(node_map):
        cyclic_ids = sorted(set(node_map) - {n["id"] for n in result})
        raise GraphCycleError(
            f"Workflow graph contains a cycle involving node(s): {', '.join(cyclic_ids)}"
        )

    return result


def downstream_node_ids(
    start_node_id: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> set[str]:
    """Return all node IDs reachable downstream of start_node_id (excluding it)."""
    adjacency: dict[str, list[str]] = {n["id"]: [] for n in nodes if "id" in n}
    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src in adjacency and tgt in adjacency:
            adjacency[src].append(tgt)

    visited: set[str] = set()
    queue: deque[str] = deque(adjacency.get(start_node_id, []))
    while queue:
        nid = queue.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        queue.extend(adjacency.get(nid, []))
    return visited


def find_join_node_id(
    inventory_node_id: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> str | None:
    """Return the first fan-in node downstream of the inventory step, if any.

    v1 supports at most one fan-in node per fanned-out branch; the match is
    deterministic by node list order.
    """
    downstream = downstream_node_ids(inventory_node_id, nodes, edges)
    for node in nodes:
        node_id = node.get("id", "")
        if node_id in downstream and (node.get("data", {}) or {}).get("kind") == "fan-in":
            return node_id
    return None


def child_node_ids(
    inventory_node_id: str,
    join_node_id: str | None,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> set[str]:
    """Nodes a fan-out child should execute.

    That is everything downstream of the inventory step, minus the fan-in
    node and everything downstream of it (which the parent runs once after
    the children rejoin). When no fan-in node exists, children run the whole
    downstream subgraph (legacy behaviour).
    """
    downstream = downstream_node_ids(inventory_node_id, nodes, edges)
    if join_node_id is None:
        return downstream
    post_join = {join_node_id} | downstream_node_ids(join_node_id, nodes, edges)
    return downstream - post_join
```

### Code before — `backend/services/execution/step_runner.py` (imports, lines 9–38)

```python
from __future__ import annotations

import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session

from core.config import settings
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.workflows import Workflow
from models.workflow_context import Capability, StepOutcome, WorkflowContext
from repositories.plugin_repository import PluginRepository
from repositories.run_repository import RunRepository
from services.artifacts import FilesystemArtifactService
from services.execution.step_result_status import derive_step_result_status
from services.network.netmiko.session_pool import DeviceSessionPool
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from services.workflow_context.guards import (
    effective_produces,
    post_step_guard,
    pre_step_guard,
)
from services.workflow_context.merge import merge_workflow_contexts
from services.workflow_context.registry import capability_spec_from_plugin
from services.workflow_context.secret_fields import redact_secrets_in_data
```

### Code after

```python
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session

from core.config import settings
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.workflows import Workflow
from models.workflow_context import Capability, StepOutcome, WorkflowContext
from repositories.plugin_repository import PluginRepository
from repositories.run_repository import RunRepository
from services.artifacts import FilesystemArtifactService
from services.execution.graph import (
    child_node_ids,
    downstream_node_ids,
    find_join_node_id,
    topological_order,
)
from services.execution.step_result_status import derive_step_result_status
from services.network.netmiko.session_pool import DeviceSessionPool
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from services.workflow_context.guards import (
    effective_produces,
    post_step_guard,
    pre_step_guard,
)
from services.workflow_context.merge import merge_workflow_contexts
from services.workflow_context.registry import capability_spec_from_plugin
from services.workflow_context.secret_fields import redact_secrets_in_data
```

`collections.deque` is no longer used directly in `step_runner.py` after this extraction — drop the import (it moves into `graph.py`).

### Code before — `backend/services/execution/step_runner.py` (the four static methods being removed, lines 639–699, plus the `_topological_sort` body, lines 787–813)

```python
    @staticmethod
    def _downstream_node_ids(
        start_node_id: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> set[str]:
        """Return all node IDs reachable downstream of start_node_id (excluding it)."""
        adjacency: dict[str, list[str]] = {n["id"]: [] for n in nodes if "id" in n}
        for edge in edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            if src in adjacency and tgt in adjacency:
                adjacency[src].append(tgt)

        visited: set[str] = set()
        queue: deque[str] = deque(adjacency.get(start_node_id, []))
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            queue.extend(adjacency.get(nid, []))
        return visited

    @staticmethod
    def _find_join_node_id(
        inventory_node_id: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> str | None:
        """Return the first fan-in node downstream of the inventory step, if any.

        v1 supports at most one fan-in node per fanned-out branch; the match is
        deterministic by node list order.
        """
        downstream = StepRunner._downstream_node_ids(inventory_node_id, nodes, edges)
        for node in nodes:
            node_id = node.get("id", "")
            if node_id in downstream and (node.get("data", {}) or {}).get("kind") == "fan-in":
                return node_id
        return None

    @staticmethod
    def _child_node_ids(
        inventory_node_id: str,
        join_node_id: str | None,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> set[str]:
        """Nodes a fan-out child should execute.

        That is everything downstream of the inventory step, minus the fan-in
        node and everything downstream of it (which the parent runs once after
        the children rejoin). When no fan-in node exists, children run the whole
        downstream subgraph (legacy behaviour).
        """
        downstream = StepRunner._downstream_node_ids(inventory_node_id, nodes, edges)
        if join_node_id is None:
            return downstream
        post_join = {join_node_id} | StepRunner._downstream_node_ids(join_node_id, nodes, edges)
        return downstream - post_join
```

```python
    def _topological_sort(
        self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        nodes, edges = self._filter_executable_graph(nodes, edges)
        node_map = {n["id"]: n for n in nodes if "id" in n}
        in_degree: dict[str, int] = {nid: 0 for nid in node_map}
        dependents: dict[str, list[str]] = {nid: [] for nid in node_map}

        for edge in edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            if src in in_degree and tgt in in_degree:
                in_degree[tgt] += 1
                dependents[src].append(tgt)

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result: list[dict[str, Any]] = []

        while queue:
            nid = queue.pop(0)
            result.append(node_map[nid])
            for dep in dependents[nid]:
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        return result
```

### Code after — replace both blocks above with

```python
    def _topological_sort(
        self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Executable-node-filtered topological order.

        Raises ``GraphCycleError`` (a ``ValueError``) if the graph contains a
        cycle — see ``services.execution.graph.topological_order``. Workflow
        definitions are also validated for cycles at save time
        (``WorkflowService``), but this is defense in depth: canvas data can
        change between save and run (e.g. direct DB edits, older saved
        workflows from before that validation existed).
        """
        executable_nodes, executable_edges = self._filter_executable_graph(nodes, edges)
        return topological_order(executable_nodes, executable_edges)
```

Every other reference to the four removed static methods becomes a call to the module-level function:

| Old call (inside `StepRunner`) | New call |
|---|---|
| `self._downstream_node_ids(join_node_id, nodes, edges)` (line 476) | `downstream_node_ids(join_node_id, nodes, edges)` |
| `self._find_join_node_id(node_id, nodes, edges)` (line 168, inside `execute_all`) | `find_join_node_id(node_id, nodes, edges)` |

`_downstream_node_ids`, `_find_join_node_id`, and `_child_node_ids` are **also called externally** as `StepRunner.<method>(...)` static-method access (verified via `grep -rn "_find_join_node_id\|_child_node_ids\|_downstream_node_ids" backend --include="*.py"`, which is the authoritative check — do not skip it if re-deriving this step, since these are easy to miss from `step_runner.py` alone). Every one of these external call sites must be updated too:

| File | Line(s) | Change |
|---|---|---|
| `backend/hatchet/workflows/workflow_run.py` | import at line 85 (`from services.execution.step_runner import FanOutSignal, StepRunner`), call at line 158 (`StepRunner._find_join_node_id(node_id, canvas_nodes, canvas_edges)`), inside `_run_steps_until_fan_out_or_done` (starts line 63) | `StepRunner` is used **only** for this one call inside this function (verified: `FanOutSignal` is separately constructed at line 104, but `StepRunner` itself has no other reference in the function body) — change the import to `from services.execution.step_runner import FanOutSignal` (drop `StepRunner`) and add `from services.execution.graph import find_join_node_id`; change the call to `find_join_node_id(node_id, canvas_nodes, canvas_edges)` |
| `backend/hatchet/workflows/workflow_run.py` | import at line 620 (`from services.execution.step_runner import StepRunner`), call at line 627 (`StepRunner._child_node_ids(signal.inventory_node_id, signal.join_node_id, canvas_nodes, canvas_edges)`), inside `_aggregate_and_persist` (starts line 597) | `StepRunner` is used **only** for this one call inside `_aggregate_and_persist` (verified: no other `StepRunner` reference in that function body) — replace the import at line 620 outright with `from services.execution.graph import child_node_ids` and change the call to `child_node_ids(signal.inventory_node_id, signal.join_node_id, canvas_nodes, canvas_edges)` |
| `backend/hatchet/workflows/device_group_execution.py` | import at line 50 (`from services.execution.step_runner import StepRunner`), call at line 72 (`StepRunner._child_node_ids(input.start_node_id, input.join_node_id, nodes, edges)`) | Add `from services.execution.graph import child_node_ids`; keep the `StepRunner` import (it's also used for `StepRunner(db)` at line 75 in the same function); change the call to `child_node_ids(input.start_node_id, input.join_node_id, nodes, edges)` |

### Code before — `backend/tests/unit/test_fan_in.py` (lines 1–16, 45–77)

```python
"""Tests for the fan-in node: boundary helpers and the pass-through executor."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.execution.step_runner import StepRunner
from workflow_steps.fan_in.executor import execute as fan_in_execute
```

```python
class FanInBoundaryHelperTests(unittest.TestCase):
    def test_find_join_node_id_returns_fan_in_node(self) -> None:
        self.assertEqual(
            StepRunner._find_join_node_id("inv", _NODES, _EDGES),
            "join",
        )

    def test_find_join_node_id_none_when_absent(self) -> None:
        nodes = [n for n in _NODES if n["id"] != "join"]
        edges = [
            _edge("inv", "a"),
            _edge("inv", "b"),
            _edge("a", "store"),
        ]
        self.assertIsNone(StepRunner._find_join_node_id("inv", nodes, edges))

    def test_child_node_ids_excludes_join_and_descendants(self) -> None:
        self.assertEqual(
            StepRunner._child_node_ids("inv", "join", _NODES, _EDGES),
            {"a", "b"},
        )

    def test_child_node_ids_equals_full_downstream_without_join(self) -> None:
        self.assertEqual(
            StepRunner._child_node_ids("inv", None, _NODES, _EDGES),
            {"a", "b", "join", "store"},
        )

    def test_downstream_of_join_is_post_join_set(self) -> None:
        self.assertEqual(
            StepRunner._downstream_node_ids("join", _NODES, _EDGES),
            {"store"},
        )
```

### Code after — `backend/tests/unit/test_fan_in.py`

```python
"""Tests for the fan-in node: boundary helpers and the pass-through executor."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.execution.graph import child_node_ids, downstream_node_ids, find_join_node_id
from workflow_steps.fan_in.executor import execute as fan_in_execute
```

```python
class FanInBoundaryHelperTests(unittest.TestCase):
    def test_find_join_node_id_returns_fan_in_node(self) -> None:
        self.assertEqual(
            find_join_node_id("inv", _NODES, _EDGES),
            "join",
        )

    def test_find_join_node_id_none_when_absent(self) -> None:
        nodes = [n for n in _NODES if n["id"] != "join"]
        edges = [
            _edge("inv", "a"),
            _edge("inv", "b"),
            _edge("a", "store"),
        ]
        self.assertIsNone(find_join_node_id("inv", nodes, edges))

    def test_child_node_ids_excludes_join_and_descendants(self) -> None:
        self.assertEqual(
            child_node_ids("inv", "join", _NODES, _EDGES),
            {"a", "b"},
        )

    def test_child_node_ids_equals_full_downstream_without_join(self) -> None:
        self.assertEqual(
            child_node_ids("inv", None, _NODES, _EDGES),
            {"a", "b", "join", "store"},
        )

    def test_downstream_of_join_is_post_join_set(self) -> None:
        self.assertEqual(
            downstream_node_ids("join", _NODES, _EDGES),
            {"store"},
        )
```

This test file is the most direct regression check for the whole extraction — it exercises `find_join_node_id`, `child_node_ids`, and `downstream_node_ids` against the same diamond-graph fixture (`_NODES`/`_EDGES`, lines 29–42, unchanged) both before and after the move, so a passing `test_fan_in.py` after the edit is strong evidence the extraction preserved behavior exactly.

### Code before — `backend/services/execution/step_runner.py` (`execute_all`, the `_find_join_node_id` call, line 168)

```python
                join_node_id = self._find_join_node_id(node_id, nodes, edges)
```

### Code after

```python
                join_node_id = find_join_node_id(node_id, nodes, edges)
```

### Code before — `backend/services/execution/step_runner.py` (`resume_after_join`, line 476)

```python
        post_join_ids = {join_node_id} | self._downstream_node_ids(join_node_id, nodes, edges)
```

### Code after

```python
        post_join_ids = {join_node_id} | downstream_node_ids(join_node_id, nodes, edges)
```

### Now the `WorkflowService` side — `backend/services/workflow/workflow_service.py`

### Code before (imports + `create_workflow` + `update_workflow`)

```python
from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.models.workflows import Workflow
from models.workflows import (
    WorkflowCreate,
    WorkflowListResponse,
    WorkflowNameCheckResponse,
    WorkflowResponse,
    WorkflowSummary,
    WorkflowUpdate,
)
from repositories.workflow_repository import WorkflowRepository

logger = logging.getLogger(__name__)
```

```python
    def create_workflow(self, data: WorkflowCreate, user_id: int) -> WorkflowResponse:
        logger.info("Creating workflow name=%r user_id=%s", data.name, user_id)
        try:
            workflow = self.repo.create(
                name=data.name,
                creator_id=user_id,
                description=data.description,
                folder=data.folder,
                visibility=data.visibility,
                canvas_nodes=data.canvas_nodes,
                canvas_edges=data.canvas_edges,
                canvas_groups=data.canvas_groups,
            )
```

```python
    def update_workflow(
        self, workflow_id: int, data: WorkflowUpdate, user_id: int
    ) -> WorkflowResponse:
        logger.info("Updating workflow id=%s user_id=%s", workflow_id, user_id)
        try:
            result = self.repo.get_by_id(workflow_id)
            if result is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found"
                )
            workflow, creator_username = result
            if workflow.creator_id != user_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            updated_fields = data.model_dump(exclude_unset=True)
            workflow = self.repo.update(workflow, updated_fields)
```

### Code after

```python
from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.models.workflows import Workflow
from models.workflows import (
    WorkflowCreate,
    WorkflowListResponse,
    WorkflowNameCheckResponse,
    WorkflowResponse,
    WorkflowSummary,
    WorkflowUpdate,
)
from repositories.workflow_repository import WorkflowRepository
from services.execution.graph import GraphCycleError, topological_order

logger = logging.getLogger(__name__)


def _validate_no_cycle(canvas_nodes: list[dict], canvas_edges: list[dict]) -> None:
    """Raise HTTP 400 if the canvas graph contains a cycle.

    See doc/FABLE-ANALYSIS.md §4.2: without this, a cyclic graph is accepted
    at save time and then silently loses the cyclic nodes at run time (they
    never reach in-degree 0 in StepRunner's topological sort).
    """
    try:
        topological_order(canvas_nodes, canvas_edges)
    except GraphCycleError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
```

```python
    def create_workflow(self, data: WorkflowCreate, user_id: int) -> WorkflowResponse:
        logger.info("Creating workflow name=%r user_id=%s", data.name, user_id)
        _validate_no_cycle(data.canvas_nodes, data.canvas_edges)
        try:
            workflow = self.repo.create(
                name=data.name,
                creator_id=user_id,
                description=data.description,
                folder=data.folder,
                visibility=data.visibility,
                canvas_nodes=data.canvas_nodes,
                canvas_edges=data.canvas_edges,
                canvas_groups=data.canvas_groups,
            )
```

```python
    def update_workflow(
        self, workflow_id: int, data: WorkflowUpdate, user_id: int
    ) -> WorkflowResponse:
        logger.info("Updating workflow id=%s user_id=%s", workflow_id, user_id)
        try:
            result = self.repo.get_by_id(workflow_id)
            if result is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found"
                )
            workflow, creator_username = result
            if workflow.creator_id != user_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            updated_fields = data.model_dump(exclude_unset=True)
            if "canvas_nodes" in updated_fields or "canvas_edges" in updated_fields:
                _validate_no_cycle(
                    updated_fields.get("canvas_nodes", workflow.canvas_nodes),
                    updated_fields.get("canvas_edges", workflow.canvas_edges),
                )
            workflow = self.repo.update(workflow, updated_fields)
```

> `WorkflowCreate.canvas_nodes`/`canvas_edges` default to `[]` (`models/workflows.py:16-17`), so `_validate_no_cycle` on an empty graph is a trivial, guaranteed pass. `WorkflowUpdate` fields are `| None = None` — the `"canvas_nodes" in updated_fields` guard (via `model_dump(exclude_unset=True)`) ensures we only validate when the caller actually sent new canvas data, and we fall back to the persisted `workflow.canvas_nodes`/`canvas_edges` for the field the caller didn't touch, so a partial update (e.g. renaming a workflow without resending canvas data) still validates the *effective* post-update graph.

### New tests

**`backend/tests/unit/test_execution_graph.py`** (new file — the extracted module has no direct test today):

```python
"""Tests for services.execution.graph — extracted from step_runner.py.
See doc/FABLE-ANALYSIS.md §4.2, §5.3."""

from __future__ import annotations

import pytest

from services.execution.graph import (
    GraphCycleError,
    child_node_ids,
    downstream_node_ids,
    find_join_node_id,
    topological_order,
)


def _node(node_id: str, kind: str = "log-message") -> dict:
    return {"id": node_id, "data": {"kind": kind}}


def _edge(source: str, target: str) -> dict:
    return {"source": source, "target": target}


class TestTopologicalOrder:
    def test_linear_chain_orders_by_dependency(self) -> None:
        nodes = [_node("a"), _node("b"), _node("c")]
        edges = [_edge("a", "b"), _edge("b", "c")]

        ordered = topological_order(nodes, edges)

        assert [n["id"] for n in ordered] == ["a", "b", "c"]

    def test_disconnected_nodes_all_included(self) -> None:
        nodes = [_node("a"), _node("b")]
        ordered = topological_order(nodes, edges=[])
        assert {n["id"] for n in ordered} == {"a", "b"}

    def test_direct_cycle_raises(self) -> None:
        nodes = [_node("a"), _node("b")]
        edges = [_edge("a", "b"), _edge("b", "a")]

        with pytest.raises(GraphCycleError, match="a|b"):
            topological_order(nodes, edges)

    def test_self_loop_raises(self) -> None:
        nodes = [_node("a")]
        edges = [_edge("a", "a")]

        with pytest.raises(GraphCycleError):
            topological_order(nodes, edges)

    def test_cycle_downstream_of_valid_prefix_raises(self) -> None:
        # a -> b -> c -> b (cycle does not include the entry node "a")
        nodes = [_node("a"), _node("b"), _node("c")]
        edges = [_edge("a", "b"), _edge("b", "c"), _edge("c", "b")]

        with pytest.raises(GraphCycleError):
            topological_order(nodes, edges)


class TestDownstreamNodeIds:
    def test_returns_transitive_downstream_only(self) -> None:
        nodes = [_node("a"), _node("b"), _node("c"), _node("d")]
        edges = [_edge("a", "b"), _edge("b", "c"), _edge("a", "d")]

        assert downstream_node_ids("a", nodes, edges) == {"b", "c", "d"}
        assert downstream_node_ids("c", nodes, edges) == set()


class TestFindJoinNodeId:
    def test_finds_fan_in_downstream(self) -> None:
        nodes = [_node("inv", "get-nautobot-devices"), _node("fi", "fan-in")]
        edges = [_edge("inv", "fi")]

        assert find_join_node_id("inv", nodes, edges) == "fi"

    def test_returns_none_when_no_fan_in(self) -> None:
        nodes = [_node("inv"), _node("x")]
        edges = [_edge("inv", "x")]

        assert find_join_node_id("inv", nodes, edges) is None


class TestChildNodeIds:
    def test_excludes_join_and_post_join_nodes(self) -> None:
        nodes = [_node("inv"), _node("x"), _node("fi", "fan-in"), _node("y")]
        edges = [_edge("inv", "x"), _edge("x", "fi"), _edge("fi", "y")]

        assert child_node_ids("inv", "fi", nodes, edges) == {"x"}

    def test_legacy_behaviour_without_join_node(self) -> None:
        nodes = [_node("inv"), _node("x"), _node("y")]
        edges = [_edge("inv", "x"), _edge("x", "y")]

        assert child_node_ids("inv", None, nodes, edges) == {"x", "y"}
```

**`backend/tests/unit/test_workflow_service_graph_validation.py`** (new file):

```python
"""WorkflowService must reject cyclic canvas graphs at save time.
See doc/FABLE-ANALYSIS.md §4.2."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from models.workflows import WorkflowCreate
from services.workflow.workflow_service import WorkflowService


def _cyclic_nodes_and_edges() -> tuple[list[dict], list[dict]]:
    nodes = [{"id": "a", "data": {"kind": "log-message"}}, {"id": "b", "data": {"kind": "log-message"}}]
    edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]
    return nodes, edges


def test_create_workflow_rejects_cyclic_graph() -> None:
    service = WorkflowService(MagicMock())
    nodes, edges = _cyclic_nodes_and_edges()
    data = WorkflowCreate(
        name="cyclic",
        canvas_nodes=nodes,
        canvas_edges=edges,
    )

    with pytest.raises(HTTPException) as exc_info:
        service.create_workflow(data, user_id=1)

    assert exc_info.value.status_code == 400
    assert "cycle" in exc_info.value.detail.lower()
```

> Check `WorkflowCreate`'s required fields in `models/workflows.py` before running this test — if fields beyond `name`/`canvas_nodes`/`canvas_edges` are mandatory (e.g. `visibility`, `folder` with non-`None` defaults), add them to the constructor call above; `models/workflows.py:11-19` should be re-read at implementation time to confirm the exact required set.

### Verification

```bash
cd backend
ruff check .
wc -l services/execution/step_runner.py   # should now be well under 800

# Confirm zero remaining StepRunner.<graph-method> references anywhere:
grep -rn "StepRunner\._find_join_node_id\|StepRunner\._child_node_ids\|StepRunner\._downstream_node_ids\|self\._find_join_node_id\|self\._downstream_node_ids" --include="*.py" .

python -m pytest -q tests/unit/test_execution_graph.py tests/unit/test_workflow_service_graph_validation.py tests/unit/test_fan_in.py -v
python -m pytest -q   # full suite — this touches step_runner.py, both hatchet workflow files, and test_fan_in.py
python scripts/check_asyncio_run.py
```

---

## Step 8: `SettingsService` Domain Exception for the Worker Path (Rec. 5, §3.1)

**What:** `workflow_steps/get_from_config/executor.py` imports `fastapi.HTTPException` solely to catch what `SettingsService.get_source_config` raises and re-wrap it as `ValueError`. This is the only workflow-step executor that imports FastAPI (verified: `grep -rn "HTTPException" backend/workflow_steps/` has exactly this one hit). Add a worker-safe wrapper method on `SettingsService` that raises a domain exception (a `ValueError` subclass) instead, so the executor never needs FastAPI at all.

**Why:** Workflow-step executors run inside the Hatchet worker process, not a FastAPI request — pulling in `fastapi.HTTPException` there is a layering leak (CLAUDE.md: steps raise `ValueError`/`RuntimeError`, never HTTP types). `get_source_config` itself is left untouched because it is also called from 4 router endpoints (`routers/sources/git/ops.py:125,169,229,251`) that rely on it raising `HTTPException` directly and let it propagate uncaught to FastAPI's built-in handler — changing its raise type would be a much larger, riskier change touching those 4 call sites for no benefit to this fix.

**Files:** new `backend/services/settings/exceptions.py`, edits to `backend/services/settings/settings_service.py` and `backend/workflow_steps/get_from_config/executor.py`.

### New file — `backend/services/settings/exceptions.py`

```python
"""Domain exceptions for the settings service.

``SourceConfigError`` is a ``ValueError`` subclass specifically so
worker-side callers (workflow-step executors) can let it propagate directly
per the step contract in doc/WORKFLOW-STEPS.md (ValueError = configuration
problem) without ever importing FastAPI. See doc/FABLE-ANALYSIS.md §3.1.
"""

from __future__ import annotations


class SourceConfigError(ValueError):
    """Raised by SettingsService.get_source_config_for_step when a source_type/
    source_id pair cannot be resolved to a setting."""
```

### Code before — `backend/services/settings/settings_service.py` (lines 1–56, header + `get_source_config`)

```python
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.models.settings import Setting
from core.safe_urls import UnsafeURLError, validate_outbound_http_url
from models.settings import (
    SettingCreate,
    SettingListResponse,
    SettingResponse,
    SettingUpdate,
)
from repositories.settings_repository import SettingsRepository
from services.settings.source_keys import (
    SourceType,
    build_source_key,
    ensure_value_source_id,
    parse_source_key,
)

logger = logging.getLogger(__name__)
```

```python
    def get_source_config(self, source_type: SourceType, source_id: str) -> dict[str, Any]:
        """Load a typed source setting and return its value with ``source_id`` set."""
        source_id = source_id.strip()
        if not source_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{source_type}_source_id is required",
            )
        try:
            setting_key = build_source_key(source_type, source_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        setting = self.repo.get_by_key(setting_key)
        if setting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{source_type.title()} source '{source_id}' not found in settings",
            )
        return {**(setting.value or {}), "source_id": source_id}
```

### Code after

```python
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.models.settings import Setting
from core.safe_urls import UnsafeURLError, validate_outbound_http_url
from models.settings import (
    SettingCreate,
    SettingListResponse,
    SettingResponse,
    SettingUpdate,
)
from repositories.settings_repository import SettingsRepository
from services.settings.exceptions import SourceConfigError
from services.settings.source_keys import (
    SourceType,
    build_source_key,
    ensure_value_source_id,
    parse_source_key,
)

logger = logging.getLogger(__name__)
```

```python
    def get_source_config(self, source_type: SourceType, source_id: str) -> dict[str, Any]:
        """Load a typed source setting and return its value with ``source_id`` set.

        Router-facing: raises ``HTTPException`` directly, matching the 4
        call sites in routers/sources/git/ops.py that let it propagate
        uncaught to FastAPI's handler. Workflow-step executors must use
        ``get_source_config_for_step`` instead — see its docstring.
        """
        source_id = source_id.strip()
        if not source_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{source_type}_source_id is required",
            )
        try:
            setting_key = build_source_key(source_type, source_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        setting = self.repo.get_by_key(setting_key)
        if setting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{source_type.title()} source '{source_id}' not found in settings",
            )
        return {**(setting.value or {}), "source_id": source_id}

    def get_source_config_for_step(self, source_type: SourceType, source_id: str) -> dict[str, Any]:
        """Worker-safe equivalent of ``get_source_config``.

        Workflow-step executors run in the Hatchet worker, not a FastAPI
        request, and must raise ``ValueError`` for configuration problems
        (doc/WORKFLOW-STEPS.md) rather than importing/catching
        ``fastapi.HTTPException`` — see doc/FABLE-ANALYSIS.md §3.1.
        """
        try:
            return self.get_source_config(source_type, source_id)
        except HTTPException as exc:
            raise SourceConfigError(str(exc.detail)) from exc
```

### Code before — `backend/workflow_steps/get_from_config/executor.py` (imports, lines 1–25)

```python
"""Executor for the get-from-config step."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from core.database import get_db_session
from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.settings.settings_service import SettingsService
from services.sources.git.git_content_search_service import GitContentSearchService
from services.sources.git.git_source_service import clone_or_pull
from workflow_steps.common.cisco_config_parsing import parse_cisco_config_text
from workflow_steps.common.device_builders import device_context_from_config_match
from workflow_steps.common.fan_out import build_fan_out_metadata

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)
```

### Code after

```python
"""Executor for the get-from-config step."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from core.database import get_db_session
from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.settings.settings_service import SettingsService
from services.sources.git.git_content_search_service import GitContentSearchService
from services.sources.git.git_source_service import clone_or_pull
from workflow_steps.common.cisco_config_parsing import parse_cisco_config_text
from workflow_steps.common.device_builders import device_context_from_config_match
from workflow_steps.common.fan_out import build_fan_out_metadata

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)
```

> Note: if Step 9 (moving `cisco_config_parsing.py` into `services/network/`) is applied, the `workflow_steps.common.cisco_config_parsing` import line above changes to `services.network.cisco_config_parsing` — apply steps in the order given (Step 8 before Step 9) to avoid a merge conflict on this line, or reconcile manually if done out of order.

### Code before — `backend/workflow_steps/get_from_config/executor.py` (lines 59–66)

```python
    db = get_db_session()
    try:
        try:
            source_config = SettingsService(db).get_source_config("git", git_source_id)
        except HTTPException as exc:
            raise ValueError(f"get-from-config: {exc.detail}") from exc
    finally:
        db.close()
```

### Code after

```python
    db = get_db_session()
    try:
        try:
            source_config = SettingsService(db).get_source_config_for_step("git", git_source_id)
        except SourceConfigError as exc:
            raise ValueError(f"get-from-config: {exc}") from exc
    finally:
        db.close()
```

Add the import:

```python
from services.settings.exceptions import SourceConfigError
```

(place it alphabetically with the other `services.*` imports, right after `from services.artifacts import ArtifactService` and before `from services.settings.settings_service import SettingsService`).

### Verification

```bash
cd backend
grep -rn "HTTPException" workflow_steps/   # must print nothing
ruff check .
python -m pytest -q tests/unit/test_get_from_config_workflow_step.py -v
python -m pytest -q
```

The existing test mocks `settings_service.get_source_config` (see `tests/unit/test_get_from_config_workflow_step.py:30`) — update that mock target to `get_source_config_for_step` when applying this step (`settings_service.get_source_config_for_step.return_value = self.source_config`), and add a companion test asserting a `SourceConfigError` from the service surfaces as a `ValueError` from the executor.

---

## Step 9: Move `workflow_steps/common` Shared Helpers into `services/` (Rec. 5, §3.2)

**What:** CLAUDE.md: *"External code must never import `workflow_steps` packages directly; only `StepRunner` calls executors."* Three routers violate this by importing from `workflow_steps.common`:

- `routers/netmiko.py:29` → `cisco_config_parsing`
- `routers/workflow_update_attribute.py:18-19` → `attribute_path`, `attribute_regex`
- `routers/sources/git/ops.py:31` → `cisco_config_parsing`

These three modules are de-facto shared libraries, not step-internal helpers — move them into `services/` where routers are allowed to import from. This is a pure import-path rename; no logic changes.

**Why:** `workflow_steps/common/` currently plays two incompatible roles (step-internal helpers *and* a shared library reachable from routers). Moving the three router-consumed modules resolves the CLAUDE.md violation without having to touch the rule itself.

**Moves:**

| From | To |
|---|---|
| `backend/workflow_steps/common/attribute_path.py` | `backend/services/workflow_context/attribute_path.py` |
| `backend/workflow_steps/common/attribute_regex.py` | `backend/services/workflow_context/attribute_regex.py` |
| `backend/workflow_steps/common/cisco_config_parsing.py` | `backend/services/network/cisco_config_parsing.py` |

`services/workflow_context/` is the natural home for `attribute_path`/`attribute_regex` — `attribute_path.py` already imports `from services.workflow_context.secret_fields import (...)`, so it belongs beside `secret_fields.py`, `guards.py`, `merge.py`, `registry.py`. `services/network/` (parent of `services/network/netmiko/`) already exists as a package and is the natural home for generic Cisco config parsing, which is not netmiko-specific.

**Complete list of every file whose import statement must change** (verified via `grep -rln`, no other files reference these three module paths):

`workflow_steps.common.attribute_path` → `services.workflow_context.attribute_path` (17 files):
```
backend/routers/workflow_update_attribute.py
backend/tests/unit/test_update_attribute_executor.py
backend/tests/unit/test_update_ise_tacacs_key_executor.py
backend/tests/unit/test_add_to_ise_executor.py
backend/tests/unit/test_attribute_write.py
backend/tests/unit/test_get_ise_tacacs_key_executor.py
backend/tests/unit/test_attribute_path.py
backend/tests/unit/test_log_message_executor.py
backend/workflow_steps/list_contains/executor.py
backend/workflow_steps/add_to_ise/executor.py
backend/workflow_steps/get_ise_tacacs_key/executor.py
backend/workflow_steps/log_message/executor.py
backend/workflow_steps/common/attribute_write.py
backend/workflow_steps/common/update_field_expression.py
backend/workflow_steps/common/placeholder_template.py
backend/workflow_steps/route_on_attribute/executor.py
backend/workflow_steps/update_attribute/executor.py
```

`workflow_steps.common.attribute_regex` → `services.workflow_context.attribute_regex` (3 files):
```
backend/routers/workflow_update_attribute.py
backend/tests/unit/test_attribute_regex.py
backend/workflow_steps/update_attribute/executor.py
```

`workflow_steps.common.cisco_config_parsing` → `services.network.cisco_config_parsing` (5 files):
```
backend/routers/netmiko.py
backend/routers/sources/git/ops.py
backend/scripts/parse_config.py
backend/workflow_steps/parse_cisco_config/executor.py
backend/workflow_steps/get_from_config/executor.py
```

### Code before (representative — `backend/routers/workflow_update_attribute.py:17-18`)

```python
from workflow_steps.common.attribute_path import resolve_device_attribute
from workflow_steps.common.attribute_regex import RegexFlagsConfig, probe_regex_transform
```

### Code after

```python
from services.workflow_context.attribute_path import resolve_device_attribute
from services.workflow_context.attribute_regex import RegexFlagsConfig, probe_regex_transform
```

Every other importer follows the identical substring substitution (only the module path changes; imported names are untouched). Execute as a scripted move + global replace rather than 25 hand-written diffs:

```bash
cd backend
git mv workflow_steps/common/attribute_path.py services/workflow_context/attribute_path.py
git mv workflow_steps/common/attribute_regex.py services/workflow_context/attribute_regex.py
git mv workflow_steps/common/cisco_config_parsing.py services/network/cisco_config_parsing.py

grep -rl 'workflow_steps\.common\.attribute_path' --include='*.py' . \
  | xargs sed -i '' 's/workflow_steps\.common\.attribute_path/services.workflow_context.attribute_path/g'
grep -rl 'workflow_steps\.common\.attribute_regex' --include='*.py' . \
  | xargs sed -i '' 's/workflow_steps\.common\.attribute_regex/services.workflow_context.attribute_regex/g'
grep -rl 'workflow_steps\.common\.cisco_config_parsing' --include='*.py' . \
  | xargs sed -i '' 's/workflow_steps\.common\.cisco_config_parsing/services.network.cisco_config_parsing/g'
```

(On Linux, drop the empty `''` after `-i` in the `sed` invocations.)

No changes are needed inside the three moved files themselves — all three already use fully-qualified absolute imports (e.g. `attribute_path.py` imports `from models.workflow_context import DeviceContext` and `from services.workflow_context.secret_fields import (...)`, neither of which is relative to its own former location), so moving the file does not break its own imports.

### Verification

```bash
cd backend
# Confirm zero remaining references to the old paths:
grep -rn "workflow_steps\.common\.attribute_path\|workflow_steps\.common\.attribute_regex\|workflow_steps\.common\.cisco_config_parsing" --include="*.py" .

ruff check .
python -m pytest -q   # full suite — this touches 25 files' imports, run everything
grep -rn "^from workflow_steps\|^import workflow_steps" routers/ --include="*.py"   # should now print nothing
```

That last `grep` directly verifies the CLAUDE.md rule this step exists to satisfy: zero `workflow_steps` imports remaining anywhere under `routers/`.

---

## Step 10: Replace Router-Level Service Singletons with `Depends()` (§3.3)

**What:** `routers/git/files.py` and `routers/oidc.py` construct services at import time (module-level globals) instead of through `dependencies.py`/`service_factory.py`, unlike every other router (e.g. `routers/git/debug.py` correctly uses `Depends(get_git_debug_service)`).

**Why:** Consistency with the established DI pattern; makes these two routers mockable in tests the same way the rest of the codebase already is.

**Files:** `backend/service_factory.py`, `backend/dependencies.py`, `backend/routers/git/files.py`, `backend/routers/oidc.py`

### 10a. `routers/git/files.py`

### Code before — `backend/service_factory.py` (append after the existing git builders, lines 173–183)

```python
def build_git_debug_service():
    from services.git.debug_service import GitDebugService

    return GitDebugService()


def build_git_version_control_service():
    from services.git.version_control_service import GitVersionControlService

    return GitVersionControlService()
```

### Code after

```python
def build_git_debug_service():
    from services.git.debug_service import GitDebugService

    return GitDebugService()


def build_git_version_control_service():
    from services.git.version_control_service import GitVersionControlService

    return GitVersionControlService()


def build_git_file_service():
    from services.git.file_service import GitFileService

    return GitFileService()


def build_git_csv_service():
    from services.git.csv_service import GitCsvService

    return GitCsvService()
```

### Code before — `backend/dependencies.py` (end of file, lines 71–73)

```python
def get_git_version_control_service():
    return service_factory.build_git_version_control_service()
```

### Code after

```python
def get_git_version_control_service():
    return service_factory.build_git_version_control_service()


def get_git_file_service():
    return service_factory.build_git_file_service()


def get_git_csv_service():
    return service_factory.build_git_csv_service()
```

### Code before — `backend/routers/git/files.py` (complete file)

```python
"""
Git file operations router — thin delegates to GitFileService.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from core.auth import get_current_user, require_permission
from dependencies import get_cache_service
from services.git.csv_service import GitCsvService
from services.git.file_service import GitFileService

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/git/{repo_id}",
    tags=["git-files"],
    dependencies=[Depends(require_permission("git.files", "read"))],
)

_git_file_service = GitFileService()
_git_csv_service = GitCsvService()


@router.get("/files/search")
async def search_repository_files(
    repo_id: int,
    query: str = "",
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
):
    return _git_file_service.search_files(repo_id, query, limit)


@router.get("/files/{commit_hash}/commit")
async def get_files(
    repo_id: int,
    commit_hash: str,
    file_path: str = None,
    current_user: dict = Depends(get_current_user),
):
    return _git_file_service.get_commit_files(repo_id, commit_hash, file_path)


@router.get("/files/{file_path:path}/history")
async def get_file_history(
    repo_id: int,
    file_path: str,
    current_user: dict = Depends(get_current_user),
):
    return _git_file_service.get_file_last_commit(repo_id, file_path)


@router.get("/files/{file_path:path}/complete-history")
async def get_file_complete_history(
    repo_id: int,
    file_path: str,
    from_commit: str = None,
    current_user: dict = Depends(get_current_user),
    cache_service=Depends(get_cache_service),
):
    return _git_file_service.get_file_history(
        repo_id,
        file_path,
        from_commit,
        cache_service,
    )


@router.get("/file-content")
async def get_file_content(
    repo_id: int,
    path: str,
    current_user: dict = Depends(get_current_user),
):
    content = _git_file_service.get_file_content(
        repo_id, path, username=current_user.get("username")
    )
    return PlainTextResponse(content=content)


@router.get("/file-content-parsed")
async def get_file_content_parsed(
    repo_id: int,
    path: str,
    current_user: dict = Depends(get_current_user),
):
    return _git_file_service.get_file_content_parsed(
        repo_id, path, username=current_user.get("username")
    )


@router.get("/tree")
async def get_directory_tree(
    repo_id: int,
    path: str = "",
    current_user: dict = Depends(get_current_user),
):
    return _git_file_service.get_directory_tree(repo_id, path)


@router.get("/directory")
async def get_directory_files(
    repo_id: int,
    path: str = "",
    current_user: dict = Depends(get_current_user),
):
    return _git_file_service.get_directory_files(repo_id, path)


@router.get("/csv-files")
async def list_csv_files(
    repo_id: int,
    query: str = "",
    limit: int = 200,
    current_user: dict = Depends(get_current_user),
):
    return _git_csv_service.list_csv_files(repo_id, query, limit)


@router.get("/csv-headers")
async def get_csv_headers(
    repo_id: int,
    path: str,
    delimiter: str = ",",
    quote_char: str = '"',
    current_user: dict = Depends(get_current_user),
):
    return _git_csv_service.get_csv_headers(repo_id, path, delimiter, quote_char)
```

### Code after — `backend/routers/git/files.py` (complete file)

```python
"""
Git file operations router — thin delegates to GitFileService.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from core.auth import get_current_user, require_permission
from dependencies import get_cache_service, get_git_csv_service, get_git_file_service
from services.git.csv_service import GitCsvService
from services.git.file_service import GitFileService

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/git/{repo_id}",
    tags=["git-files"],
    dependencies=[Depends(require_permission("git.files", "read"))],
)


@router.get("/files/search")
async def search_repository_files(
    repo_id: int,
    query: str = "",
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    git_file_service: GitFileService = Depends(get_git_file_service),
):
    return git_file_service.search_files(repo_id, query, limit)


@router.get("/files/{commit_hash}/commit")
async def get_files(
    repo_id: int,
    commit_hash: str,
    file_path: str = None,
    current_user: dict = Depends(get_current_user),
    git_file_service: GitFileService = Depends(get_git_file_service),
):
    return git_file_service.get_commit_files(repo_id, commit_hash, file_path)


@router.get("/files/{file_path:path}/history")
async def get_file_history(
    repo_id: int,
    file_path: str,
    current_user: dict = Depends(get_current_user),
    git_file_service: GitFileService = Depends(get_git_file_service),
):
    return git_file_service.get_file_last_commit(repo_id, file_path)


@router.get("/files/{file_path:path}/complete-history")
async def get_file_complete_history(
    repo_id: int,
    file_path: str,
    from_commit: str = None,
    current_user: dict = Depends(get_current_user),
    cache_service=Depends(get_cache_service),
    git_file_service: GitFileService = Depends(get_git_file_service),
):
    return git_file_service.get_file_history(
        repo_id,
        file_path,
        from_commit,
        cache_service,
    )


@router.get("/file-content")
async def get_file_content(
    repo_id: int,
    path: str,
    current_user: dict = Depends(get_current_user),
    git_file_service: GitFileService = Depends(get_git_file_service),
):
    content = git_file_service.get_file_content(
        repo_id, path, username=current_user.get("username")
    )
    return PlainTextResponse(content=content)


@router.get("/file-content-parsed")
async def get_file_content_parsed(
    repo_id: int,
    path: str,
    current_user: dict = Depends(get_current_user),
    git_file_service: GitFileService = Depends(get_git_file_service),
):
    return git_file_service.get_file_content_parsed(
        repo_id, path, username=current_user.get("username")
    )


@router.get("/tree")
async def get_directory_tree(
    repo_id: int,
    path: str = "",
    current_user: dict = Depends(get_current_user),
    git_file_service: GitFileService = Depends(get_git_file_service),
):
    return git_file_service.get_directory_tree(repo_id, path)


@router.get("/directory")
async def get_directory_files(
    repo_id: int,
    path: str = "",
    current_user: dict = Depends(get_current_user),
    git_file_service: GitFileService = Depends(get_git_file_service),
):
    return git_file_service.get_directory_files(repo_id, path)


@router.get("/csv-files")
async def list_csv_files(
    repo_id: int,
    query: str = "",
    limit: int = 200,
    current_user: dict = Depends(get_current_user),
    git_csv_service: GitCsvService = Depends(get_git_csv_service),
):
    return git_csv_service.list_csv_files(repo_id, query, limit)


@router.get("/csv-headers")
async def get_csv_headers(
    repo_id: int,
    path: str,
    delimiter: str = ",",
    quote_char: str = '"',
    current_user: dict = Depends(get_current_user),
    git_csv_service: GitCsvService = Depends(get_git_csv_service),
):
    return git_csv_service.get_csv_headers(repo_id, path, delimiter, quote_char)
```

### 10b. `routers/oidc.py`

Same pattern — add builders and DI getters, then replace the module-level `_config_service`/`_oidc_service` singletons with per-request `Depends()`. `OidcConfigService()` and `OIDCService(config_service)` take no `db: Session` (they're config/env-backed, not DB-backed), so the factory functions need no `db` parameter — same shape as `build_git_debug_service()`.

### Code before — `backend/service_factory.py` (append near the auth-related builders; there is currently no OIDC builder)

```python
def build_credentials_service(db: Session | None = None):
    from core.database import SessionLocal
    from services.credentials.credentials_service import CredentialsService

    session = db if db is not None else SessionLocal()
    return CredentialsService(session)
```

### Code after

```python
def build_credentials_service(db: Session | None = None):
    from core.database import SessionLocal
    from services.credentials.credentials_service import CredentialsService

    session = db if db is not None else SessionLocal()
    return CredentialsService(session)


def build_oidc_config_service():
    from services.auth.oidc_config_service import OidcConfigService

    return OidcConfigService()


def build_oidc_service():
    from services.auth.oidc_service import OIDCService

    return OIDCService(build_oidc_config_service())
```

### Code before — `backend/dependencies.py` (end of file)

```python
def get_git_file_service():
    return service_factory.build_git_file_service()


def get_git_csv_service():
    return service_factory.build_git_csv_service()
```

*(this is the end-state from Step 10a — append the OIDC getters after it)*

### Code after

```python
def get_git_file_service():
    return service_factory.build_git_file_service()


def get_git_csv_service():
    return service_factory.build_git_csv_service()


def get_oidc_config_service():
    return service_factory.build_oidc_config_service()


def get_oidc_service():
    return service_factory.build_oidc_service()
```

### Code before — `backend/routers/oidc.py` (lines 1–39)

```python
"""OIDC SSO login/callback/logout endpoints, plus admin debug/test-login routes
that power the /tools/oidc-test dashboard."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import service_factory
from core.auth import require_permission
from core.database import get_db
from core.safe_http_errors import raise_internal_server_error
from models.auth import (
    ApprovalPendingResponse,
    OIDCCallbackRequest,
    OIDCLoginResponse,
    OIDCLogoutResponse,
    OIDCProvider,
    OIDCProvidersResponse,
    OIDCTestLoginRequest,
    TokenResponse,
)
from services.auth.auth_service import AuthService
from services.auth.oidc_config_service import OidcConfigService
from services.auth.oidc_service import (
    OIDCApprovalPendingError,
    OIDCAutoProvisioningDisabledError,
    OIDCError,
    OIDCService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/oidc", tags=["oidc"])

_config_service = OidcConfigService()
_oidc_service = OIDCService(_config_service)

OIDC_STATE_TTL_SECONDS = 600
```

### Code after

```python
"""OIDC SSO login/callback/logout endpoints, plus admin debug/test-login routes
that power the /tools/oidc-test dashboard."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import service_factory
from core.auth import require_permission
from core.database import get_db
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_oidc_config_service, get_oidc_service
from models.auth import (
    ApprovalPendingResponse,
    OIDCCallbackRequest,
    OIDCLoginResponse,
    OIDCLogoutResponse,
    OIDCProvider,
    OIDCProvidersResponse,
    OIDCTestLoginRequest,
    TokenResponse,
)
from services.auth.auth_service import AuthService
from services.auth.oidc_config_service import OidcConfigService
from services.auth.oidc_service import (
    OIDCApprovalPendingError,
    OIDCAutoProvisioningDisabledError,
    OIDCError,
    OIDCService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/oidc", tags=["oidc"])

OIDC_STATE_TTL_SECONDS = 600
```

Then, **every one of the 15 usages of `_config_service.*`/`_oidc_service.*` in the rest of the file** must gain the corresponding `Depends()` parameter on its enclosing route handler and switch to the parameter name instead of the module-level name. This is the one sub-step in this whole plan that needs the full route handler bodies re-read at implementation time (there are 9 handlers; reproducing all of them verbatim here would not add accuracy over reading the live file, since the transformation is a pure rename within each handler once the parameter is added). The rule to apply per handler:

```python
# Before (pattern used in every affected handler):
async def some_endpoint(...):
    ...
    x = _config_service.get_enabled_providers()
    ...
    y = await _oidc_service.generate_authorization_url(...)

# After:
async def some_endpoint(
    ...,
    config_service: OidcConfigService = Depends(get_oidc_config_service),
    oidc_service: OIDCService = Depends(get_oidc_service),
):
    ...
    x = config_service.get_enabled_providers()
    ...
    y = await oidc_service.generate_authorization_url(...)
```

Add `config_service`/`oidc_service` parameters only to the handlers that actually use them (not all 9 need both — e.g. `list_providers` at line 55 only needs `config_service`). The exact line numbers to touch (re-verify against the live file, since Step 10a's edits to `dependencies.py` don't shift these): lines 56-57, 110, 112, 154, 161-163, 186, 195-196, 202, 209, 240, 243 (all currently-known usages, enumerated in the analysis).

### Verification

```bash
cd backend
ruff check .
python -m pytest -q tests/unit -k "oidc or git_file or git_csv or files"
python -m pytest -q
python scripts/check_router_repositories.py
```

---

## Step 11: Fix `RunService.get_run_artifact` DI/Import Hygiene (§3.4)

**What:** `get_run_artifact` imports `models.artifacts` and `services.artifacts` inside the method body and constructs a new `FilesystemArtifactService(settings.data_directory)` on every call, instead of module-level imports + constructor injection (the pattern the rest of `RunService` and the rest of the codebase follows).

**Why:** Consistency; also avoids repeatedly touching the filesystem-service's `mkdir(parents=True, exist_ok=True)` call in `FilesystemArtifactService.__init__` on every artifact fetch.

**File:** `backend/services/execution/run_service.py`

### Code before (imports, lines 1–23)

```python
from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.config import settings
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.safe_http_errors import raise_internal_server_error
from models.runs import (
    RUN_LIST_STATUS_FILTERS,
    TERMINAL_RUN_STATUSES,
    WorkflowRunCreate,
    WorkflowRunListResponse,
    WorkflowRunResponse,
    WorkflowRunSummary,
    WorkflowStepResultResponse,
)
from repositories.run_repository import RunRepository
from repositories.workflow_repository import WorkflowRepository

logger = logging.getLogger(__name__)
```

### Code after

```python
from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.config import settings
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.safe_http_errors import raise_internal_server_error
from models.artifacts import ArtifactContentResponse
from models.runs import (
    RUN_LIST_STATUS_FILTERS,
    TERMINAL_RUN_STATUSES,
    WorkflowRunCreate,
    WorkflowRunListResponse,
    WorkflowRunResponse,
    WorkflowRunSummary,
    WorkflowStepResultResponse,
)
from repositories.run_repository import RunRepository
from repositories.workflow_repository import WorkflowRepository
from services.artifacts import ArtifactNotFoundError, FilesystemArtifactService

logger = logging.getLogger(__name__)
```

### Code before (`__init__`, lines 98–102)

```python
class RunService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.run_repo = RunRepository(db)
        self.wf_repo = WorkflowRepository(db)
```

### Code after

```python
class RunService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.run_repo = RunRepository(db)
        self.wf_repo = WorkflowRepository(db)
        self.artifact_service = FilesystemArtifactService(settings.data_directory)
```

### Code before (`get_run_artifact`, lines 192–217)

```python
    def get_run_artifact(self, run_id: int, artifact_id: str, user_id: int):
        from models.artifacts import ArtifactContentResponse
        from services.artifacts import ArtifactNotFoundError, FilesystemArtifactService

        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        run, _username = result
        self._assert_workflow_access(run.workflow_id, user_id)

        service = FilesystemArtifactService(settings.data_directory)
        try:
            ref, content = service.get_for_run(run_uuid=run.uuid, artifact_id=artifact_id)
        except ArtifactNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Artifact not found",
            ) from exc

        return ArtifactContentResponse(
            artifact_id=ref.artifact_id,
            kind=ref.kind,
            media_type=ref.media_type,
            size_bytes=ref.size_bytes,
            content=content,
        )
```

### Code after

```python
    def get_run_artifact(self, run_id: int, artifact_id: str, user_id: int) -> ArtifactContentResponse:
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        run, _username = result
        self._assert_workflow_access(run.workflow_id, user_id)

        try:
            ref, content = self.artifact_service.get_for_run(run_uuid=run.uuid, artifact_id=artifact_id)
        except ArtifactNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Artifact not found",
            ) from exc

        return ArtifactContentResponse(
            artifact_id=ref.artifact_id,
            kind=ref.kind,
            media_type=ref.media_type,
            size_bytes=ref.size_bytes,
            content=content,
        )
```

`ArtifactContentResponse` and `models.artifacts` were verified to have no import cycle back to `services.execution` or `services.artifacts` (checked directly: neither module imports anything from `services.execution`), so the move to module-level imports is safe.

### Verification

```bash
cd backend
ruff check .
python -m pytest -q tests/unit -k "run_service or artifact"
python -m pytest -q
```

---

## Step 12: Testing Debt (Rec. 7, §7) — Sustained Work, Not a Single Patch

**What:** Coverage is 53% against the 80% target, concentrated in the highest-risk code:

| Area | Current coverage | File(s) |
|---|---|---|
| Git write path | 0–21% | `services/git/debug_service.py` (0%), `services/git/operations.py` (0%), `services/git/cache.py` (0%), `services/git/file_service.py` (7%), `services/git/service.py` (21%) |
| Nautobot mutation path | 6–14% | `services/nautobot/devices/update.py` (7%), `devices/interface_workflow.py` (6%), `devices/creation.py` (14%), resolvers (7-9%) |
| Cache layer | 11% | `services/cache/redis_cache_service.py` |
| Source routers | 21–25% | `routers/sources/ise/ops.py`, `routers/sources/nautobot/ops.py`, `routers/sources/nautobot/crud.py` |
| Under-tested executors | 14–16% | `update_nautobot_device` (15%), `merge_content` (16%), `filter_output` (14%) |
| Integration suite | **0 tests** | `tests/integration/` contains only a README |

**Why this cannot be "one patch":** closing a 27-point coverage gap concentrated in git-write and Nautobot-mutation code means writing dozens of new test cases against real (mocked at the httpx/subprocess boundary, not the service boundary) external-system behavior — this is genuine, multi-day test-authoring work, not a mechanical fix.

**Recommended order (highest risk first, matching the analysis's own ordering):**

1. **Git write path** — `debug_service.py`, `operations.py`, `cache.py`. These perform real filesystem/subprocess/GitPython writes; 0% coverage on write operations is the single highest-risk gap in the codebase. Start with `GitOperationsService` (the service backing `routers/git/operations.py`, itself only 23% covered) since it's the primary write entry point, then `GitCacheService`.
2. **Nautobot mutation path** — `devices/update.py`, `devices/interface_workflow.py`, `devices/creation.py`, and the three resolvers they depend on. Mock at the `NautobotService` client boundary (`services/nautobot/client.py`) the same way existing 80%+-covered tests already do for read paths — check `tests/unit/test_nautobot_resolve.py` and `tests/unit/test_nautobot_interfaces.py` for the established mocking pattern before writing new tests, to stay consistent.
3. **Integration suite** — stand up `tests/integration/` against a real PostgreSQL instance (a docker-compose test database, matching the dev environment's existing Docker postgres/redis setup — see the project's dev-environment memory notes) to cover the PostgreSQL-dialect-specific behavior that `doc/refactoring/REFACTORING_RAW_SQL.md` §3 explicitly requires integration coverage for. This is the only way to close the "integration" leg of the testing rule (`common/testing.md`: unit + integration + E2E all required) — right now there is exactly zero.
4. **Under-tested executors** — `update_nautobot_device`, `merge_content`, `filter_output`. These are lower risk than 1–2 (pure in-process logic, easier to test, smaller blast radius if wrong) — do them opportunistically alongside step 13's decomposition work, since splitting a monolithic `execute()` into named helpers (step 13) naturally produces smaller, individually-testable units.
5. **`redis_cache_service.py`** — lowest priority of this list; cache-miss behavior is already exercised indirectly by higher-level tests, but the service itself deserves direct unit coverage for its Redis-specific serialization/TTL logic.

**Concrete first task** (to make this actionable rather than purely aspirational): before writing any new test, run

```bash
cd backend
python -m pytest -q --cov=. --cov-report=term-missing services.git.operations
```

against just `services/git/operations.py` to get the exact uncovered line ranges, then write one test class per public method in `GitOperationsService`, following the existing convention of one `test_<module>.py` file per service (see `tests/unit/test_git_auth_credentials.py`, `test_git_push_helpers.py`, `test_git_content_search_service.py` for the file-per-service-concern convention already in use in this test suite).

---

## Step 13: Decompose the Largest `execute()`/Service Functions (Rec. 9, §5.2) — Opportunistic, Do Last

**What:** 77 functions exceed the 80-line line-count threshold from the analysis; the worst 10 are listed below with their current line counts. The rule (`coding-style.md`: functions <50 lines) is already met by one executor in this same codebase — **`workflow_steps/get_ise_tacacs_key/executor.py`** — which decomposes its 439-line file into small `_tier_name_exact32`, `_tier_name_any`, `_tier_location_group`, `_tier_ip_prefix_scan`, `_tier_ip_range_scan`, `_find_tacacs_key` helpers (see `get_ise_tacacs_key/executor.py:138-284`). That file is the pattern to copy for every entry below — read it first as the worked example before touching any of these.

| Lines | Location | Suggested decomposition seam |
|---|---|---|
| 288 | `workflow_steps/deploy_rendered_template/executor.py:84` `execute` | Split into `_parse_config`, `_render_for_device` (calls the existing 156-line `deploy_on_device` at line 153, itself a second decomposition candidate), `_build_outcomes` |
| 245 | `workflow_steps/update_nautobot_device/executor.py:83` `execute` | Split by per-device iteration body vs. outcome assembly, mirroring `add_to_nautobot/executor.py`'s existing structure if it already separates these (compare before duplicating a pattern) |
| 243 | `services/git/debug_service.py:242` `test_push` | Split into `_stage_debug_commit`, `_push_debug_commit`, `_build_diagnostics_payload` |
| 240 | `services/nautobot/devices/update.py:49` `update_device` | Split into `_resolve_update_targets`, `_apply_field_updates`, `_apply_interface_updates` |
| 238 | `workflow_steps/add_to_ise/executor.py:122` `execute` | Same per-device-loop vs. outcome-assembly split as `update_nautobot_device` |
| 219 | `workflow_steps/compare_data/executor.py:164` `execute` | Split comparison-logic from outcome-building |
| 216 | `services/nautobot/managers/ip_manager.py:43` `ensure_ip_address_exists` | Split into `_find_existing_ip`, `_create_ip`, `_attach_ip_to_interface` |
| 202 | `workflow_steps/run_command/executor.py:78` `execute` | Split into `_parse_config` (partially exists already as `_parse_commands`/`_parse_use_textfsm`), `_run_commands_for_device`, `_build_outcomes` |
| 197 | `workflow_steps/add_to_nautobot/executor.py:109` `execute` | Same per-device-loop split |
| 196 | `hatchet/workflows/workflow_run.py:399` `_dispatch_children` | Split child-input-building (`_build_child_inputs`, already a separate method at line 445 — check whether `_dispatch_children` still inlines logic that duplicates it) from the actual dispatch/gather loop |

**Why this section has no "code before/after" blocks:** these are 150–290-line function bodies; reproducing them verbatim here would either (a) go stale the moment anyone touches the file between now and implementation, or (b) require re-reading the full body anyway to split it correctly — a line-count table and a proven in-repo exemplar is the accurate, durable artifact; a frozen diff of a 288-line function is not.

**Procedure per function** (repeat for each row above):

1. Read the full function body.
2. Identify natural seams: config-parsing/validation → per-device (or per-item) work → outcome/response assembly is the recurring shape across every workflow-step executor in this codebase.
3. Extract each seam into a module-level `_snake_case` helper directly above `execute()`, taking only the specific values it needs (not the whole `config`/`context` dict) as parameters — this is also what makes the helper independently unit-testable.
4. Add or extend the corresponding `tests/unit/test_<step>_executor.py` file with direct tests of the new helpers, not just end-to-end `execute()` tests — this simultaneously advances Step 12's coverage goal for the executors in this list (`update_nautobot_device`, `merge_content`, `filter_output` all appear in both lists).
5. Run `ruff check .` and the step's existing test file to confirm behavior is unchanged before moving to the next function.

**Order:** do the two executors that also appear in Step 12's under-tested list first (`update_nautobot_device`, then any of `merge_content`/`filter_output` if convenient), since decomposition there pays a double dividend (line-count *and* coverage). Everything else in the table is genuinely optional polish — do not block a release on this step.

### Verification (per function, not once at the end)

```bash
cd backend
ruff check .
python -m pytest -q tests/unit/test_<step>_executor.py -v
python -m pytest -q   # full suite after each extraction, not just at the end
```
