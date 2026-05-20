# Backend Code Analysis — May 2026

## Overall Assessment

The codebase is architecturally sound: good layering (Model → Repository → Service → Router), no hardcoded secrets, no f-string logging, and Ruff reports only 5 minor errors. The issues below are ranked by production impact.

---

## Findings

### CRITICAL

**GraphQL injection via f-string interpolation**
`workflow_steps/get_nautobot_devices/nautobot/query_service.py:170–200`

`_query_devices_by_ip_prefix` accepts user-supplied `cidr`, `namespace`, and `operator` and embeds them directly into GraphQL query strings via f-strings. A crafted value can escape the query structure and invoke arbitrary GraphQL operations (including mutations) on the Nautobot instance.

Fix: Replace all f-string query composition with GraphQL variables (`$cidr: String!`, etc.). Validate `operator` against a `Literal["within", "within_include", "exact"]` allowlist at the Pydantic model layer before the value reaches this function.

---

### HIGH

**`HTTPException` raised inside the service layer**
`services/workflow/workflow_service.py:69,72,89–92,109,112,150,153`

`WorkflowService` imports and raises `fastapi.HTTPException` directly. Services must not depend on FastAPI. This prevents unit testing without a running FastAPI context and breaks any Hatchet or Celery task that calls into the service — the caller receives an `HTTPException` it has no handler for.

Fix: Define domain exceptions (`WorkflowNotFoundError`, `WorkflowAccessDeniedError`) in the service module. Raise those. Translate them to `HTTPException` in the router or a shared exception handler.

---

**Double `get_current_user` dependency evaluation**
`routers/workflows.py:25,35,47,62,71,81,90`

The router declares `dependencies=[Depends(get_current_user)]` at the router level and then every endpoint redeclares `current_user: User = Depends(get_current_user)`. FastAPI does not deduplicate by argument identity here — the auth DB lookup runs twice per request.

Fix: Remove the router-level `dependencies=[...]` declaration and keep only the per-endpoint injection, which also yields the `current_user` object needed by the handler.

---

**Unvalidated `operation_type`, `field`, and `operator` strings**
`models/plugins.py:85–91`, `workflow_steps/get_nautobot_devices/nautobot/evaluator.py:76–84`

`LogicalConditionRequest.field`, `.operator`, and `LogicalOperationRequest.operation_type` are plain `str` with no allowlist validation. Unknown values silently return empty device sets instead of a 422 error, making filter bugs invisible to callers.

Fix: Use `Literal` types for all three fields. Pydantic rejects invalid values at the API boundary with a 422 automatically.

---

**`visibility` query parameter unvalidated**
`routers/workflows.py:45`

`visibility: str = Query("private")` accepts any string. It is passed through to the repository `WHERE` clause unchanged. An invalid value silently returns "available" for any name (no rows match), giving a wrong uniqueness answer with no error.

Fix: Change the type to `WorkflowVisibility` (the `Literal["public", "private"]` alias already defined in `models/workflows.py`).

---

**`logger.info` with `exc_info=True` on failures**
`services/workflow/workflow_service.py:99,120`

Workflow save failures are logged at `INFO` level. With `LOG_LEVEL=WARNING` (typical in production) these lines produce no output. The exception is re-raised, so the client sees a 500, but there is no server-side record.

Fix: Replace `logger.info("Failed to ...", exc_info=True)` with `logger.exception("Failed to ...")`. The `exception` helper sets `ERROR` level and attaches `exc_info` implicitly.

---

**In-process rate limiter not shared across workers**
`routers/auth.py:20–21`

`login_attempts: defaultdict[str, deque[float]]` is module-level in-process state. Each Uvicorn worker holds an independent copy — with 4 workers an attacker gets 4× the allowed attempts before lockout. State is also lost on every restart.

Fix: Move rate limit state to Redis (`INCR` + `EXPIRE`). Redis is already in the project stack.

---

### MEDIUM

**`preview.py` appears to be dead code**
`workflow_steps/get_nautobot_devices/preview.py`

`preview_device_selection()` is not imported or called anywhere in the active router. It reads credentials from environment variables (inconsistent with the rest of the flow, which takes them from the request body) and uses a different GraphQL schema shape (`site`, `status.value`) that no longer matches the Nautobot v3/v4 queries used elsewhere.

Fix: Delete the file. If a future use is intended, document it and reconcile the credential and schema model with the rest of the system.

---

**Two parallel model hierarchies with manual conversion**
`routers/workflow_steps.py:144–180`, `models/plugins.py`, `workflow_steps/get_nautobot_devices/models.py`

`LogicalOperationRequest` (request model) and `LogicalOperation` (internal model) have the same shape but live in different modules. A manual recursive `_convert_nested()` function translates between them. Any field added to one must be added to the other and to the conversion function.

Fix: Use `LogicalOperation` directly as the API request model, or make `LogicalOperationRequest` a type alias. Eliminate the conversion step.

---

**`_parse_devices()` is a hand-rolled field extractor**
`workflow_steps/get_nautobot_devices/nautobot/query_service.py:254–299`

45 lines of `if d.get(...)` checks that manually extract nested fields from the GraphQL response into `DeviceInfo`. `DeviceInfo` is already a Pydantic model. When a new field is added to the GraphQL query, the parser must be updated manually.

Fix: Define a `RawNautobotDevice` Pydantic model matching the GraphQL response shape. Use `DeviceInfo.model_validate(raw_device)` with a `@model_validator` or `@computed_field` for any flatten/extract logic.

---

**`NautobotEvaluator` accesses private methods of `NautobotQueryService`**
`workflow_steps/get_nautobot_devices/nautobot/evaluator.py:22–31`

`self._field_map` maps field names to `query_service._query_devices_by_name`, `_query_devices_by_role`, etc. (all `_`-prefixed). Refactoring the private interface of `NautobotQueryService` silently breaks the evaluator with no type error.

Fix: Remove the leading `_` from the referenced query methods to make them part of the public interface, or add a single `query_by_field(field, value, **kwargs)` dispatch method on `NautobotQueryService`.

---

**`WorkflowSummary.visibility` typed as `str`**
`models/workflows.py:37`

`WorkflowCreate` and `WorkflowUpdate` correctly use `WorkflowVisibility = Literal["public", "private"]`, but the response model `WorkflowSummary.visibility` is typed as plain `str`, weakening the OpenAPI schema.

Fix: Change `visibility: str` to `visibility: WorkflowVisibility`.

---

**`WorkflowRepository.update()` applies arbitrary keys via `setattr`**
`repositories/workflow_repository.py:68–73`

`for key, value in fields.items(): setattr(workflow, key, value)` applies every key from the update dict to the ORM model without an allowlist. A key that does not map to a column (e.g., `id`, `creator_id`) is silently ignored by SQLAlchemy — safe only because `WorkflowUpdate` currently does not expose those fields.

Fix: Explicitly allowlist the updatable fields (`name`, `description`, `folder`, `visibility`, `canvas_nodes`, `canvas_edges`) in the repository method and raise `ValueError` for unexpected keys.

---

### LOW

**Ruff violations**
- `services/workflow/workflow_service.py:99,109,120` — E501 lines exceed 100 characters
- `workflow_steps/get_nautobot_devices/nautobot/evaluator.py:5–10` — I001 import block unsorted

Fix: Run `ruff check --fix .` from `backend/`.

---

**`get_config()` return type too broad**
`workflow_steps/get_nautobot_devices/config.py:4`

Returns bare `dict` without type parameters.

Fix: Change to `dict[str, Any]` or a typed `TypedDict`.

---

**GraphQL device field selection duplicated across three query strings**
`workflow_steps/get_nautobot_devices/nautobot/query_service.py:117–160`

The full 11-field device selection block is repeated verbatim in three variants of `_query_devices_by_location`. Adding a new field requires three edits.

Fix: Extract into a module-level `_DEVICE_FIELDS_FRAGMENT` constant and reference it in each query string.

---

## Summary Table

| Severity | Count | Key Files |
|---|---|---|
| CRITICAL | 1 | `query_service.py` |
| HIGH | 5 | `workflow_service.py`, `workflows.py` (router), `plugins.py`, `auth.py` |
| MEDIUM | 6 | `preview.py`, `workflow_steps.py`, `query_service.py`, `evaluator.py`, `workflows.py` (model), `workflow_repository.py` |
| LOW | 3 | `workflow_service.py`, `evaluator.py`, `config.py` |

## Recommended Fix Order

1. **GraphQL injection** (CRITICAL) — before any real Nautobot credentials reach this code
2. **`logger.exception` on failures** (HIGH, 2-line fix) — production observability
3. **Double auth dep** (HIGH, 1-line fix) — wasted DB round-trips on every workflow request
4. **`visibility` param validation** (HIGH, 1-line fix) — silent wrong answers
5. **`operation_type`/`field`/`operator` Literals** (HIGH) — silent empty results on bad input
6. **Domain exceptions in `WorkflowService`** (HIGH) — larger refactor, required before Hatchet integration
7. **Redis rate limiter** (HIGH) — required before multi-worker production deployment
8. **MEDIUM items** — address incrementally during normal feature work
