# Refactoring Plan — Oversized Functions 21–30

**Date:** 2026-08-03
**Based on:** `doc/TOO_LARGE_FUNCTIONS.md` (post pass-2 remaining ≥80);
  prior plans `TOO_LARGE_FUNCTIONS_1_to_10.md`, `TOO_LARGE_FUNCTIONS_11_to_20.md`;
  `doc/FABLE-ANALYSIS.md` §5.2
**Pattern:** same as passes 1–2 — `_parse_*` / phase helpers / `_build_outcomes`;
  exemplar `workflow_steps/update_nautobot_device/executor.py`
**Goal:** Bring each of the next 10 longest functions under the 80-line offender
  threshold (style rule remains `<50` lines).

> Status: **Implemented** (with one intentional skip). "Code before" was the live tree at
> plan time; actual after-line counts are in the Summary table. Rank 23 (`update_device`)
> was **left unchanged** — docstring kept per implementer request. Full suite + four
> regression guards green.

## Target selection

Passes 1–2 closed ranks 1–20. A fresh AST rescan of `backend/` (excluding
`tests/` / `migrations/`) finds **59** functions still ≥80 lines. The next 10
by length are ranks 21–30 below.

**Note on rank 23 (`update_device`):** pass 1 already thinned the executable body;
AST length is again dominated by a restored/oversized docstring (~76 lines). The
fix for this pass is primarily to **shrink the docstring** back under the
threshold (optional tiny helpers only if still needed).

## Summary

| Rank | Function | Before | After | File |
|---:|---|---:|---:|---|
| 21 | `execute_steps` | 152 | 49 | `backend/hatchet/workflows/workflow_run.py` |
| 22 | `validate_update_data` | 152 | 33 | `backend/services/nautobot/devices/update.py` |
| 23 | `update_device` | 151 | 151 (skipped — docstring kept) | `backend/services/nautobot/devices/update.py` |
| 24 | `_query_devices_by_custom_field` | 150 | 71 | `backend/services/sources/nautobot/live_query_mixin.py` |
| 25 | `_compare_for_device` | 143 | 69 | `backend/workflow_steps/compare_data/executor.py` |
| 26 | `execute` | 141 | 76 | `backend/workflow_steps/get_ise_tacacs_key/executor.py` |
| 27 | `execute` | 141 | 54 | `backend/workflow_steps/render_jinja_template/executor.py` |
| 28 | `get_diagnostics` | 139 | 26 | `backend/services/git/debug_service.py` |
| 29 | `_query_devices_by_location` | 139 | 35 | `backend/services/sources/nautobot/live_query_mixin.py` |
| 30 | `get_repository_status` | 136 | 22 | `backend/services/git/operations.py` |

## Implementation order

| Order | Rank | Risk | Notes |
|---:|---:|---|---|
| 1 | 23 | low | Docstring shrink; body already pass-1 helpers |
| 2 | 29 | low | GraphQL template dedupe; share selection with 24 |
| 3 | 24 | low | Pair with 29 — shared `_DEVICE_SELECTION_FIELDS` |
| 4 | 27 | low | Same fan-out pattern as prior executor lifts |
| 5 | 25 | low | Pure compare helper split; no I/O contract change |
| 6 | 22 | medium | Field-resolution switch; preserve omit-vs-raise |
| 7 | 30 | medium | Soft fetch/ahead-behind semantics |
| 8 | 28 | medium | Diagnostics section contracts |
| 9 | 26 | medium | ISE mid-loop abort-vs-continue (mirror add_to_ise) |
| 10 | 21 | high | Durable waits + DB session boundary before fan-out |

## Verification (after every step)

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

## Step 21: `execute_steps` — 152 → ~52 lines

**File:** `backend/hatchet/workflows/workflow_run.py`
**What:** Extract phase-1 (+ debug pause) and phase-3/4 finalize; keep session boundary before dispatch.
**Why:** Still ≥80 lines after passes 1–2; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md` / `11_to_20.md`.

**Helpers to extract:**

- `_phase1_run_or_early_finish`
- `_debug_pause_before_fan_out`
- `_finalize_fan_out_parent`

### Code before — `backend/hatchet/workflows/workflow_run.py` (`execute_steps`, 152 lines)

```python
async def execute_steps(input: WorkflowRunInput, ctx: DurableContext) -> dict:
    logger.info("Executing steps for run_id=%s", input.run_id)

    from core.database import SessionLocal
    from repositories.run_repository import RunRepository
    from repositories.workflow_repository import WorkflowRepository
    from services.execution.step_runner import StepRunner

    # Phase 1: run in topological order until completion or a fan-out signal
    with SessionLocal() as db:
        run_repo = RunRepository(db)
        wf_repo = WorkflowRepository(db)

        run_result = run_repo.get_run_by_id(input.run_id)
        if run_result is None:
            raise ValueError(f"WorkflowRun {input.run_id} not found")
        run, _ = run_result
        # Captured now — the phase-1 DB session closes before phase 2 dispatch.
        run_uuid = run.uuid

        wf_result = wf_repo.get_by_id(run.workflow_id)
        if wf_result is None:
            raise ValueError(f"Workflow {run.workflow_id} not found")
        wf, _ = wf_result

        runner = StepRunner(db)
        try:
            final_status, fan_out, run = await _run_steps_until_fan_out_or_done(
                run_repo=run_repo, runner=runner, run=run, wf=wf, ctx=ctx
            )
        finally:
            # Close (not suspend) here: on the fan-out path, children build their
            # own pools and phase 2/3 hold no device connections — this also runs
            # before the fan-out debug pause below.
            await runner.close_device_sessions()

        if fan_out is None:
            run_repo.update_run_status(
                run,
                status=final_status,
                finished_at=datetime.now(UTC),
            )
            logger.info("Run finished run_id=%s status=%s", input.run_id, final_status)
            return {"run_id": input.run_id, "status": final_status}

        signal = fan_out["signal"]
        canvas_nodes: list[dict[str, Any]] = fan_out["canvas_nodes"]
        canvas_edges: list[dict[str, Any]] = fan_out["canvas_edges"]

        # Fan-out runs as one atomic step in debug mode: pause once before
        # dispatching children; the join and everything downstream of it then
        # run in a single block on the next step/continue click (no per-device
        # or per-post-join-node pausing — see doc/WORKFLOW-STEPS.md fan-out
        # notes on why children can't be stepped individually).
        if run.run_mode == "debug":
            fan_out_label = signal.join_node_id or signal.inventory_node_id
            run_repo.update_run_status(
                run,
                status="paused",
                current_node_id=fan_out_label,
                debug_message=(
                    "Paused before fan-out dispatch. Click Next Step to run all "
                    "device groups and the fan-in join as one block."
                ),
            )
            event_key = debug_step_event_key(run.uuid, fan_out_label)
            logger.info("Debug pause (fan-out) run_id=%s node_id=%s", run.id, fan_out_label)
            await ctx.aio_wait_for_event(
                event_key,
                scope=event_key,
                lookback_window=STEP_EVENT_LOOKBACK,
            )

            run_repo.db.refresh(run)
            run_repo.update_run_status(run, status="running")

    # Phase 2: dispatch child workflows (DB session intentionally closed)
    logger.info(
        "Fan-out started run_id=%s mode=%s max_concurrency=%s",
        input.run_id,
        signal.fan_out_config.get("mode"),
        signal.fan_out_config.get("max_concurrency"),
    )
    child_results = await _dispatch_children(
        signal,
        input.run_id,
        ctx=ctx,
        run_uuid=run_uuid,
        canvas_nodes=canvas_nodes,
        canvas_edges=canvas_edges,
    )

    # Phase 3: aggregate child outcomes and persist to parent run step results
    with SessionLocal() as db:
        run_repo = RunRepository(db)
        wf_repo = WorkflowRepository(db)

        run_result = run_repo.get_run_by_id(input.run_id)
        if run_result is None:
            raise ValueError(f"WorkflowRun {input.run_id} not found (phase 3)")
        run, _ = run_result

        success, child_merged = _aggregate_and_persist(
            run_repo=run_repo,
            run_id=run.id,
            signal=signal,
            canvas_nodes=canvas_nodes,
            canvas_edges=canvas_edges,
            child_results=child_results,
        )

        # Phase 4: when a fan-in node exists, resume execution once on the merged
        # (fanned-in) context so git/store steps after the join run exactly once.
        if signal.join_node_id is not None:
            wf_result = wf_repo.get_by_id(run.workflow_id)
            if wf_result is None:
                raise ValueError(f"Workflow {run.workflow_id} not found (phase 4 resume)")
            wf, _ = wf_result

            # The fan-in node's parents are child-branch nodes; the inventory
            # node is included so a join wired directly to it still resolves.
            merged_outcomes: dict[str, dict[str, Any]] = {
                signal.inventory_node_id: {"success": signal.inventory_outcome}
            }
            merged_outcomes.update(child_merged)

            logger.info(
                "Fan-in resume run_id=%s join_node_id=%s",
                input.run_id,
                signal.join_node_id,
            )
            post_join_runner = StepRunner(db)
            try:
                join_success = await post_join_runner.resume_after_join(
                    run=run,
                    workflow=wf,
                    merged_outcomes=merged_outcomes,
                    join_node_id=signal.join_node_id,
                )
            finally:
                await post_join_runner.close_device_sessions()
            success = success and join_success

        final_status = "success" if success else "failed"
        run_repo.update_run_status(
            run,
            status=final_status,
            finished_at=datetime.now(UTC),
        )

    logger.info("Run finished (fan-out) run_id=%s status=%s", input.run_id, final_status)
    return {"run_id": input.run_id, "status": final_status}
```

### Code after — `backend/hatchet/workflows/workflow_run.py` (`execute_steps`, ~52 lines)

```python
@workflow.durable_task(
    name="execute_steps", parents=[prepare], execution_timeout=timedelta(hours=24)
)
async def execute_steps(input: WorkflowRunInput, ctx: DurableContext) -> dict:
    logger.info("Executing steps for run_id=%s", input.run_id)

    from core.database import SessionLocal
    from repositories.run_repository import RunRepository
    from repositories.workflow_repository import WorkflowRepository
    from services.execution.step_runner import StepRunner

    early = await _phase1_run_or_early_finish(
        run_id=input.run_id,
        ctx=ctx,
        SessionLocal=SessionLocal,
        RunRepository=RunRepository,
        WorkflowRepository=WorkflowRepository,
        StepRunner=StepRunner,
    )
    if isinstance(early, dict):
        return early

    run_uuid, signal, canvas_nodes, canvas_edges = early

    logger.info(
        "Fan-out started run_id=%s mode=%s max_concurrency=%s",
        input.run_id,
        signal.fan_out_config.get("mode"),
        signal.fan_out_config.get("max_concurrency"),
    )
    child_results = await _dispatch_children(
        signal,
        input.run_id,
        ctx=ctx,
        run_uuid=run_uuid,
        canvas_nodes=canvas_nodes,
        canvas_edges=canvas_edges,
    )

    final_status = await _finalize_fan_out_parent(
        run_id=input.run_id,
        signal=signal,
        canvas_nodes=canvas_nodes,
        canvas_edges=canvas_edges,
        child_results=child_results,
        SessionLocal=SessionLocal,
        RunRepository=RunRepository,
        WorkflowRepository=WorkflowRepository,
        StepRunner=StepRunner,
    )
    logger.info("Run finished (fan-out) run_id=%s status=%s", input.run_id, final_status)
    return {"run_id": input.run_id, "status": final_status}
```

---

## Step 22: `validate_update_data` — 152 → ~33 lines

**File:** `backend/services/nautobot/devices/update.py`
**What:** Extract field prepare/resolve helpers + rack position/face consistency check.
**Why:** Still ≥80 lines after passes 1–2; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md` / `11_to_20.md`.

**Helpers to extract:**

- `_prepare_update_field`
- `_resolve_update_field`
- `_enforce_rack_position_face`

### Code before — `backend/services/nautobot/devices/update.py` (`validate_update_data`, 152 lines)

```python
    async def validate_update_data(
        self,
        device_id: str,
        update_data: dict[str, Any],
        interface_config: dict[str, str] | None = None,
        rack_location: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        """
        Validate update data and resolve all resource names to UUIDs.

        Args:
            device_id: Device UUID (for context)
            update_data: Raw update data dictionary
            interface_config: Optional interface config for primary_ip4

        Returns:
            Tuple of (validated_data dict, ip_namespace str or None)

        Note:
            - Filters out empty values
            - Handles nested fields like "platform.name" → "platform"
            - Resolves all names to UUIDs
            - Normalizes tags to list format
        """
        logger.debug("Validating update data for device %s: %s", device_id, update_data)

        validated = {}
        ip_namespace = None

        for field, value in update_data.items():
            # Skip empty values, but allow explicit None for rack-assignment fields
            # so they can be sent as JSON null to Nautobot (clearing the assignment).
            if value is None and field not in ("rack", "position", "face"):
                continue
            if isinstance(value, str) and not value.strip():
                continue

            # Handle nested fields (e.g., "platform.name" → "platform")
            if "." in field:
                base_field, nested_field = field.rsplit(".", 1)
                field = base_field
                logger.debug("Flattened nested field: %s.%s → %s", field, nested_field, field)

            # Clean string values
            if isinstance(value, str):
                value = value.strip()

            # Handle special fields that need resolution
            if field == "status":
                # Resolve status name to UUID
                if not self.common._is_valid_uuid(value):
                    validated[field] = await self.common.resolve_status_id(value, "dcim.device")
                else:
                    validated[field] = value

            elif field == "platform":
                # Resolve platform name to UUID
                if not self.common._is_valid_uuid(value):
                    platform_id = await self.common.resolve_platform_id(value)
                    if platform_id:
                        validated[field] = platform_id
                    else:
                        logger.warning("Platform '%s' not found, will be omitted", value)
                else:
                    validated[field] = value

            elif field == "role":
                # Resolve role name to UUID
                if not self.common._is_valid_uuid(value):
                    role_id = await self.common.resolve_role_id(value)
                    if role_id:
                        validated[field] = role_id
                    else:
                        logger.warning("Role '%s' not found, will be omitted", value)
                else:
                    validated[field] = value

            elif field == "location":
                # Resolve location name to UUID
                if not self.common._is_valid_uuid(value):
                    location_id = await self.common.resolve_location_id(value)
                    if location_id:
                        validated[field] = location_id
                    else:
                        logger.warning("Location '%s' not found, will be omitted", value)
                else:
                    validated[field] = value

            elif field == "rack":
                # Resolve rack name to UUID, optionally filtered by location.
                # None means explicit clear (send null to Nautobot).
                if value is None:
                    validated[field] = None
                elif not self.common._is_valid_uuid(value):
                    rack_id = await self.common.resolve_rack_id(value, location=rack_location)
                    if rack_id:
                        validated[field] = rack_id
                    else:
                        logger.warning("Rack '%s' not found, will be omitted", value)
                else:
                    validated[field] = value

            elif field == "device_type":
                # Resolve device type name to UUID
                if not self.common._is_valid_uuid(value):
                    device_type_id = await self.common.resolve_device_type_id(value)
                    if device_type_id:
                        validated[field] = device_type_id
                    else:
                        logger.warning("Device type '%s' not found, will be omitted", value)
                else:
                    validated[field] = value

            elif field == "tags":
                # Normalize tags to list
                validated[field] = self.common.normalize_tags(value)

            elif field == "ip_namespace":
                # Store for later use with primary_ip4
                ip_namespace = value

            elif field == "custom_fields":
                # Ensure custom_fields is a simple dict (Nautobot expects {"field_name": "value"})
                if isinstance(value, dict):
                    validated[field] = value
                else:
                    logger.warning("Invalid custom_fields format: %s, expected dict", type(value))

            else:
                # Copy other fields as-is (including primary_ip4, etc.)
                validated[field] = value

        # Rack / position / face consistency check.
        # Nautobot requires "face" whenever "position" is set.  If "position" arrived
        # in the update data but "face" did not (or is empty), clear "position" to
        # avoid the "Must specify rack face when defining rack position" error.
        # Exception: when position is None (explicit clear), both None is intentional.
        if (
            "position" in validated
            and validated.get("position") is not None
            and not validated.get("face")
        ):
            logger.warning(
                "Dropping 'position' from update data because 'face' is not set — "
                "Nautobot requires both fields when specifying a rack position."
            )
            validated.pop("position")

        logger.info("Validation complete, %s fields to update", len(validated))
        logger.debug("Validated data: %s", validated)

        return validated, ip_namespace
```

### Code after — `backend/services/nautobot/devices/update.py` (`validate_update_data`, ~33 lines)

```python
async def validate_update_data(
    self,
    device_id: str,
    update_data: dict[str, Any],
    interface_config: dict[str, str] | None = None,
    rack_location: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Validate update data and resolve resource names to UUIDs."""
    logger.debug("Validating update data for device %s: %s", device_id, update_data)

    validated: dict[str, Any] = {}
    ip_namespace: str | None = None

    for raw_field, raw_value in update_data.items():
        prepared = _prepare_update_field(raw_field, raw_value)
        if prepared is None:
            continue
        field, value = prepared

        outcome = await self._resolve_update_field(
            field, value, rack_location=rack_location
        )
        kind = outcome[0]
        if kind == "set":
            validated[outcome[1]] = outcome[2]
        elif kind == "namespace":
            ip_namespace = outcome[1]

    _enforce_rack_position_face(validated)

    logger.info("Validation complete, %s fields to update", len(validated))
    logger.debug("Validated data: %s", validated)
    return validated, ip_namespace
```

---

## Step 23: `update_device` — 151 → ~72 lines

**File:** `backend/services/nautobot/devices/update.py`
**What:** Shrink oversized docstring (pass-1 body already thin); optional prepare/empty helpers.
**Why:** Still ≥80 lines after passes 1–2; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md` / `11_to_20.md`.

**Helpers to extract:**

- `_prepare_device_update_context (optional)`
- `_maybe_empty_update_result (optional)`
- `short class/method docstring`

### Code before — `backend/services/nautobot/devices/update.py` (`update_device`, 151 lines)

```python
    async def update_device(
        self,
        device_identifier: dict[str, Any],
        update_data: dict[str, Any],
        interface_config: dict[str, str] | None = None,
        interfaces: list[dict[str, Any]] | None = None,
        create_if_missing: bool = False,
        add_prefix: bool = True,
        default_prefix_length: str = "/24",
        matching_strategy: str = "exact",
        rack_location: str | None = None,
        sync_interfaces: bool = False,
    ) -> dict[str, Any]:
        """
        Update a single device.

        Workflow:
        1. Resolve device UUID from identifier
        2. Validate and resolve update data (names → UUIDs)
        3. Update device properties via PATCH
        4. Update/create interfaces if needed
        5. Verify updates applied

        Args:
            device_identifier: Device identifier dict with at least one of:
                - id: Device UUID
                - name: Device name
                - ip_address: Primary IPv4 address

            update_data: Fields to update, can include:
                - status: Status name or UUID
                - platform: Platform name or UUID
                - role: Role name or UUID
                - location: Location name or UUID
                - device_type: Device type name or UUID
                - serial: Serial number
                - asset_tag: Asset tag
                - tags: List of tag names or comma-separated string
                - custom_fields: Dict of custom field values
                - primary_ip4: IP address (will create interface if needed)
                - Any other device field

            interface_config: Optional interface config for primary_ip4 updates (legacy):
                {
                    "name": "Loopback0",        # Default: "Loopback"
                    "type": "virtual",          # Default: "virtual"
                    "status": "active",         # Default: "active"
                }

            interfaces: Optional list of interfaces to create/update:
                [
                    {
                        "name": "Ethernet0/0",
                        "type": "1000base-t",
                        "status": "active",
                        "ip_address": "192.168.1.1/24",
                        "namespace": "Global",
                        "is_primary_ipv4": True,
                        "enabled": True,
                        "description": "...",
                        ...
                    },
                    ...
                ]

            create_if_missing: If True, create device if not found (uses DeviceImportService)

        Returns:
            {
                "success": True,  # Always True (exceptions raised on failure)
                "device_id": str,
                "device_name": str,
                "message": str,
                "updated_fields": List[str],
                "warnings": List[str],
                "interfaces_created": int,
                "interfaces_failed": int,
                "details": {
                    "before": {...},  # Device state before update
                    "after": {...},   # Device state after update
                    "changes": {...}  # Fields that changed
                }
            }

        Raises:
            ValueError: If device not found and create_if_missing=False, or validation fails
            NautobotAPIError: If Nautobot API request fails
            Exception: If update fails for any other reason
        """
        logger.info("Starting device update for: %s", device_identifier)
        warnings: list[str] = []
        details: dict[str, Any] = {"before": None, "after": None, "changes": {}}
        try:
            device_id, device_name = await self._resolve_device_for_update(
                device_identifier,
                matching_strategy=matching_strategy,
                create_if_missing=create_if_missing,
            )
            details["before"] = await self.common.get_device_details(device_id=device_id, depth=1)
            current_primary_ip4 = await self.common.extract_primary_ip_address(details["before"])

            logger.info("Step 2: Validating and resolving update data")
            validated_data, ip_namespace = await self.validate_update_data(
                device_id, update_data, interface_config, rack_location=rack_location
            )
            if not validated_data and not interfaces:
                logger.info("No fields to update and no interfaces for device %s", device_name)
                return self._empty_update_result(
                    device_id=device_id, device_name=device_name, details=details
                )
            if not validated_data and interfaces:
                logger.info(
                    "No device fields to update, but processing %s interface(s)",
                    len(interfaces),
                )

            updated_fields = await self._apply_property_updates(
                device_id=device_id,
                device_name=device_name,
                validated_data=validated_data,
                interface_config=interface_config,
                ip_namespace=ip_namespace,
                current_primary_ip4=current_primary_ip4,
            )
            interfaces_created = interfaces_updated = interfaces_failed = 0
            if interfaces:
                interfaces_created, interfaces_updated, interfaces_failed = (
                    await self._apply_interface_updates(
                        device_id=device_id,
                        interfaces=interfaces,
                        add_prefix=add_prefix,
                        sync_interfaces=sync_interfaces,
                        warnings=warnings,
                    )
                )
            return await self._finalize_device_update(
                device_id=device_id,
                device_name=device_name,
                validated_data=validated_data,
                updated_fields=updated_fields,
                warnings=warnings,
                interfaces_created=interfaces_created,
                interfaces_updated=interfaces_updated,
                interfaces_failed=interfaces_failed,
                details=details,
            )
        except Exception as e:
            logger.error(
                "Failed to update device %s: %s", device_identifier, e, exc_info=True
            )
            raise
```

### Code after — `backend/services/nautobot/devices/update.py` (`update_device`, ~72 lines)

```python
async def update_device(
    self,
    device_identifier: dict[str, Any],
    update_data: dict[str, Any],
    interface_config: dict[str, str] | None = None,
    interfaces: list[dict[str, Any]] | None = None,
    create_if_missing: bool = False,
    add_prefix: bool = True,
    default_prefix_length: str = "/24",
    matching_strategy: str = "exact",
    rack_location: str | None = None,
    sync_interfaces: bool = False,
) -> dict[str, Any]:
    """Update one device: resolve → validate → PATCH → interfaces → verify.

    Raises ValueError / NautobotAPIError on failure. See class docstring for
    identifier/update_data/interfaces shapes and return payload.
    """
    logger.info("Starting device update for: %s", device_identifier)
    warnings: list[str] = []
    details: dict[str, Any] = {"before": None, "after": None, "changes": {}}
    try:
        device_id, device_name = await self._resolve_device_for_update(
            device_identifier,
            matching_strategy=matching_strategy,
            create_if_missing=create_if_missing,
        )
        details["before"] = await self.common.get_device_details(device_id=device_id, depth=1)
        current_primary_ip4 = await self.common.extract_primary_ip_address(details["before"])

        logger.info("Step 2: Validating and resolving update data")
        validated_data, ip_namespace = await self.validate_update_data(
            device_id, update_data, interface_config, rack_location=rack_location
        )
        if not validated_data and not interfaces:
            logger.info("No fields to update and no interfaces for device %s", device_name)
            return self._empty_update_result(
                device_id=device_id, device_name=device_name, details=details
            )
        if not validated_data and interfaces:
            logger.info(
                "No device fields to update, but processing %s interface(s)",
                len(interfaces),
            )

        updated_fields = await self._apply_property_updates(
            device_id=device_id,
            device_name=device_name,
            validated_data=validated_data,
            interface_config=interface_config,
            ip_namespace=ip_namespace,
            current_primary_ip4=current_primary_ip4,
        )
        interfaces_created = interfaces_updated = interfaces_failed = 0
        if interfaces:
            interfaces_created, interfaces_updated, interfaces_failed = (
                await self._apply_interface_updates(
                    device_id=device_id,
                    interfaces=interfaces,
                    add_prefix=add_prefix,
                    sync_interfaces=sync_interfaces,
                    warnings=warnings,
                )
            )
        return await self._finalize_device_update(
            device_id=device_id,
            device_name=device_name,
            validated_data=validated_data,
            updated_fields=updated_fields,
            warnings=warnings,
            interfaces_created=interfaces_created,
            interfaces_updated=interfaces_updated,
            interfaces_failed=interfaces_failed,
            details=details,
        )
    except Exception as e:
        logger.error(
            "Failed to update device %s: %s", device_identifier, e, exc_info=True
        )
        raise
```

---

## Step 24: `_query_devices_by_custom_field` — 150 → ~53 lines

**File:** `backend/services/sources/nautobot/live_query_mixin.py`
**What:** Shared GraphQL selection + var-type/query/variables helpers; soft-fail preserved.
**Why:** Still ≥80 lines after passes 1–2; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md` / `11_to_20.md`.

**Helpers to extract:**

- `_custom_field_graphql_var_type`
- `_build_custom_field_devices_query`
- `_device_graphql_selection (shared)`
- `_custom_field_query_variables`

### Code before — `backend/services/sources/nautobot/live_query_mixin.py` (`_query_devices_by_custom_field`, 150 lines)

```python
    async def _query_devices_by_custom_field(
        self,
        custom_field_name: str,
        custom_field_value: str,
        use_contains: bool = False,
    ) -> list[DeviceInfo]:
        """
        Query devices by custom field value.

        Intentionally kept as a live Nautobot call: custom fields are dynamic
        and not stored in the bulk device cache.

        Args:
            custom_field_name: Name of the custom field (with cf_ prefix)
            custom_field_value: Value to search for
            use_contains: Whether to use contains (icontains) or exact match

        Returns:
            List of matching devices
        """
        try:
            if (
                not custom_field_name
                or not custom_field_value
                or (isinstance(custom_field_value, str) and custom_field_value.strip() == "")
            ):
                logger.warning(
                    "Empty custom_field_name or custom_field_value provided, returning empty result"
                )
                return []

            custom_field_types = await self._get_custom_field_types()

            cf_key = custom_field_name.replace("cf_", "")
            cf_type = custom_field_types.get(cf_key)

            if cf_type == "select":
                graphql_var_type = "[String]"
            elif use_contains:
                graphql_var_type = "[String]"
            else:
                graphql_var_type = "String"

            logger.info(
                "Custom field '%s' type='%s', use_contains=%s, GraphQL type='%s'",
                cf_key,
                cf_type,
                use_contains,
                graphql_var_type,
            )

            filter_field = custom_field_name

            if use_contains:
                query = f"""
                query devices_by_custom_field($field_value: {graphql_var_type}) {{
                  devices({filter_field}__ic: $field_value) {{
                    id
                    name
                    serial
                    role {{
                      name
                    }}
                    location {{
                      name
                    }}
                    primary_ip4 {{
                      address
                    }}
                    status {{
                      name
                    }}
                    device_type {{
                      model
                      manufacturer {{
                        name
                      }}
                    }}
                    tags {{
                      name
                    }}
                    platform {{
                      name
                      network_driver
                    }}
                  }}
                }}
                """
            else:
                query = f"""
                query devices_by_custom_field($field_value: {graphql_var_type}) {{
                  devices({filter_field}: $field_value) {{
                    id
                    name
                    serial
                    role {{
                      name
                    }}
                    location {{
                      name
                    }}
                    primary_ip4 {{
                      address
                    }}
                    status {{
                      name
                    }}
                    device_type {{
                      model
                      manufacturer {{
                        name
                      }}
                    }}
                    tags {{
                      name
                    }}
                    platform {{
                      name
                      network_driver
                    }}
                  }}
                }}
                """

            if graphql_var_type == "[String]":
                variables = {"field_value": [custom_field_value]}
            else:
                variables = {"field_value": custom_field_value}

            logger.debug("Custom field '%s' GraphQL query:\n%s", cf_key, query)
            logger.debug("Custom field '%s' variables: %s", cf_key, variables)
            logger.info(
                "Custom field '%s' filter: %s, type: %s, graphql_var_type: %s",
                cf_key,
                filter_field,
                cf_type,
                graphql_var_type,
            )

            result = await self._nautobot.graphql_query(query, variables, self._credentials)

            if "errors" in result:
                logger.error("GraphQL errors in custom field query: %s", result["errors"])
                return []

            return self._parse_device_data(result.get("data", {}).get("devices", []))

        except Exception as e:
            logger.error("Error querying devices by custom field '%s': %s", custom_field_name, e)
            return []
```

### Code after — `backend/services/sources/nautobot/live_query_mixin.py` (`_query_devices_by_custom_field`, ~53 lines)

```python
async def _query_devices_by_custom_field(
    self,
    custom_field_name: str,
    custom_field_value: str,
    use_contains: bool = False,
) -> list[DeviceInfo]:
    """Live GraphQL lookup by custom field (not in bulk cache)."""
    try:
        if (
            not custom_field_name
            or not custom_field_value
            or (isinstance(custom_field_value, str) and custom_field_value.strip() == "")
        ):
            logger.warning(
                "Empty custom_field_name or custom_field_value provided, returning empty result"
            )
            return []

        custom_field_types = await self._get_custom_field_types()
        cf_key = custom_field_name.replace("cf_", "")
        cf_type = custom_field_types.get(cf_key)
        graphql_var_type = _custom_field_graphql_var_type(cf_type, use_contains)
        logger.info(
            "Custom field '%s' type='%s', use_contains=%s, GraphQL type='%s'",
            cf_key,
            cf_type,
            use_contains,
            graphql_var_type,
        )

        query = _build_custom_field_devices_query(
            custom_field_name, graphql_var_type, use_contains=use_contains
        )
        variables = _custom_field_query_variables(graphql_var_type, custom_field_value)

        logger.debug("Custom field '%s' GraphQL query:\n%s", cf_key, query)
        logger.debug("Custom field '%s' variables: %s", cf_key, variables)
        logger.info(
            "Custom field '%s' filter: %s, type: %s, graphql_var_type: %s",
            cf_key,
            custom_field_name,
            cf_type,
            graphql_var_type,
        )

        result = await self._nautobot.graphql_query(query, variables, self._credentials)
        if "errors" in result:
            logger.error("GraphQL errors in custom field query: %s", result["errors"])
            return []
        return self._parse_device_data(result.get("data", {}).get("devices", []))
    except Exception as e:
        logger.error("Error querying devices by custom field '%s': %s", custom_field_name, e)
        return []
```

---

## Step 25: `_compare_for_device` — 143 → ~69 lines

**File:** `backend/workflow_steps/compare_data/executor.py`
**What:** Split export resolve / load texts / match / mismatch builders.
**Why:** Still ≥80 lines after passes 1–2; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md` / `11_to_20.md`.

**Helpers to extract:**

- `_resolve_compare_export_item`
- `_load_compare_texts`
- `_build_compare_match_result`
- `_build_compare_mismatch_result`

### Code before — `backend/workflow_steps/compare_data/executor.py` (`_compare_for_device`, 143 lines)

```python
async def _compare_for_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    config: dict[str, Any],
    context_run_id: str | None,
    parsed: _ParsedCompareConfig,
    artifact_service: ArtifactService,
    diff_service: GitDiffService,
) -> tuple[str, DeviceContext, str, dict[str, Any] | None]:
    export_items = list_exportable_content(
        device,
        content_source=parsed.content_source,
        source_step_node_id=parsed.source_step_node_id,
        parsed_output_key=parsed.parsed_output_key,
    )
    if not export_items:
        failed = _device_failure(
            device=device,
            node_id=node_id,
            code="missing_content",
            message=(
                f"No {parsed.content_source!r} content available for device {device_id}. "
                "Ensure an upstream step produced the selected data."
            ),
        )
        return device_id, failed, "failure", None

    item = export_items[0]
    if len(export_items) > 1:
        logger.warning(
            "compare-data device=%s source=%s has %d export items; using first only",
            device_id,
            parsed.content_source,
            len(export_items),
        )

    try:
        source_content = await artifact_service.resolve(item.artifact_ref)
        reference_path = _render_reference_path(
            device=device,
            item=item,
            config=config,
            run_id=context_run_id,
        )
        reference_content = await read_reference_text(
            config=config,
            relative_path=reference_path,
        )
    except Exception as exc:
        failed = _device_failure(device=device, node_id=node_id, message=str(exc))
        return device_id, failed, "failure", None

    normalized_source = _normalize_text(
        source_content,
        normalize_line_endings=parsed.normalize_line_endings,
        ignore_trailing_whitespace=parsed.ignore_trailing_whitespace,
    )
    normalized_reference = _normalize_text(
        reference_content,
        normalize_line_endings=parsed.normalize_line_endings,
        ignore_trailing_whitespace=parsed.ignore_trailing_whitespace,
    )
    matched = normalized_source == normalized_reference

    device_parsed = dict(device.parsed)
    capabilities = set(device.capabilities)
    record: dict[str, Any] = {
        "device_id": device_id,
        "content_source": parsed.content_source,
        "reference_location": parsed.reference_location,
        "reference_path": reference_path,
        "matched": matched,
        **item.extra,
    }

    if matched:
        device_parsed[f"{node_id}.comparison"] = _comparison_result_entry(
            matched=True,
            content_source=parsed.content_source,
            reference_path=reference_path,
            reference_location=parsed.reference_location,
            node_id=node_id,
            item_extra=item.extra,
        )
        capabilities.add(Capability.PARSED)
        enriched = device.model_copy(
            update={
                "parsed": device_parsed,
                "capabilities": capabilities,
                "status": DeviceStatus.OK,
            }
        )
        return device_id, enriched, "match", record

    diff_result = diff_service.compare_text_content(
        normalized_source,
        normalized_reference,
    )
    diff_text = "\n".join(diff_result.diff_lines)
    diff_ref = await artifact_service.store(
        content=diff_text,
        kind="comparison_diff",
        device_id=device_id,
        run_id=context_run_id,
        media_type="text/plain",
    )
    diff_stats = {
        "additions": diff_result.stats.additions,
        "deletions": diff_result.stats.deletions,
    }
    comparison_diff_key = f"{node_id}.comparison_diff"
    device_parsed[comparison_diff_key] = _comparison_diff_entry(
        artifact_ref=diff_ref,
        content_source=parsed.content_source,
        reference_path=reference_path,
        reference_location=parsed.reference_location,
        node_id=node_id,
        item_extra=item.extra,
        diff_stats=diff_stats,
    )
    device_parsed[f"{node_id}.comparison"] = _comparison_result_entry(
        matched=False,
        content_source=parsed.content_source,
        reference_path=reference_path,
        reference_location=parsed.reference_location,
        diff_stats=diff_stats,
        comparison_diff_key=comparison_diff_key,
        node_id=node_id,
        item_extra=item.extra,
    )
    capabilities.add(Capability.PARSED)
    record["diff_stats"] = diff_stats
    record["comparison_diff_key"] = comparison_diff_key
    enriched = device.model_copy(
        update={
            "parsed": device_parsed,
            "capabilities": capabilities,
            "status": DeviceStatus.OK,
        }
    )
    return device_id, enriched, "mismatch", record
```

### Code after — `backend/workflow_steps/compare_data/executor.py` (`_compare_for_device`, ~69 lines)

```python
async def _compare_for_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    config: dict[str, Any],
    context_run_id: str | None,
    parsed: _ParsedCompareConfig,
    artifact_service: ArtifactService,
    diff_service: GitDiffService,
) -> tuple[str, DeviceContext, str, dict[str, Any] | None]:
    item = _resolve_compare_export_item(device, device_id, parsed)
    if item is None:
        failed = _device_failure(
            device=device,
            node_id=node_id,
            code="missing_content",
            message=(
                f"No {parsed.content_source!r} content available for device {device_id}. "
                "Ensure an upstream step produced the selected data."
            ),
        )
        return device_id, failed, "failure", None

    try:
        source_content, reference_content, reference_path = await _load_compare_texts(
            device=device,
            item=item,
            config=config,
            run_id=context_run_id,
            artifact_service=artifact_service,
        )
    except Exception as exc:
        failed = _device_failure(device=device, node_id=node_id, message=str(exc))
        return device_id, failed, "failure", None

    normalized_source = _normalize_text(
        source_content,
        normalize_line_endings=parsed.normalize_line_endings,
        ignore_trailing_whitespace=parsed.ignore_trailing_whitespace,
    )
    normalized_reference = _normalize_text(
        reference_content,
        normalize_line_endings=parsed.normalize_line_endings,
        ignore_trailing_whitespace=parsed.ignore_trailing_whitespace,
    )
    if normalized_source == normalized_reference:
        return _build_compare_match_result(
            device_id=device_id,
            device=device,
            node_id=node_id,
            parsed=parsed,
            item=item,
            reference_path=reference_path,
        )

    return await _build_compare_mismatch_result(
        device_id=device_id,
        device=device,
        node_id=node_id,
        parsed=parsed,
        item=item,
        reference_path=reference_path,
        normalized_source=normalized_source,
        normalized_reference=normalized_reference,
        context_run_id=context_run_id,
        artifact_service=artifact_service,
        diff_service=diff_service,
    )
```

---

## Step 26: `execute` — 141 → ~76 lines

**File:** `backend/workflow_steps/get_ise_tacacs_key/executor.py`
**What:** Mirror add_to_ise/update_ise_tacacs: service bind, preflight, process loop, metadata.
**Why:** Still ≥80 lines after passes 1–2; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md` / `11_to_20.md`.

**Helpers to extract:**

- `_resolve_ise_device_service`
- `_ise_unreachable_outcome`
- `_process_devices_for_tacacs_key`
- `_build_tacacs_result_metadata`

### Code before — `backend/workflow_steps/get_ise_tacacs_key/executor.py` (`execute`, 141 lines)

```python
async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service  # unused for this step

    source_id = (config.get("ise_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: ise_source_id is not configured")

    priority = _parse_priority(config)
    location_group_prefix = _parse_location_group_prefix(config)

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    source_config_service = service_factory.build_ise_source_config_service(db)
    try:
        credentials = source_config_service.resolve_credentials(source_id)
    except ISESourceNotFoundError as exc:
        raise ValueError(f"{_STEP_ID}: ISE source '{source_id}' not found") from exc
    except ISEValidationError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc

    device_service = service_factory.build_ise_network_device_service(credentials)

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        len(context.devices),
    )

    try:
        await device_service.test_connection()
    except ISEAPIError as exc:
        logger.warning("%s: could not reach ISE source '%s': %s", _STEP_ID, source_id, exc)
        return [
            StepOutcome(
                name="failure",
                context=context,
                summary=f"could not reach ISE source '{source_id}': {exc}",
            )
        ]

    updated_devices: dict[str, DeviceContext] = {}
    found_count = 0
    already_present_count = 0
    not_found_count = 0

    for device_id, device in context.devices.items():
        existing_secret = (device.attribute_bags.get("tacacs") or {}).get("shared_secret")
        if secret_is_present(existing_secret):
            updated_devices[device_id] = device
            already_present_count += 1
            continue

        try:
            secret, matched_tier = await _find_tacacs_key(
                device=device,
                device_service=device_service,
                priority=priority,
                location_group_prefix=location_group_prefix,
            )
        except ISEAPIError as exc:
            # Connectivity/auth failure discovered mid-run (ISE was reachable
            # for the pre-flight check but has since dropped, or a login
            # eventually got rejected). Every remaining device would fail the
            # same way, so abort the whole step as a "failure" outcome rather
            # than mislabeling every device "key not found".
            logger.warning(
                "%s: lost connection to ISE source '%s' while processing device '%s': %s",
                _STEP_ID,
                source_id,
                device.name,
                exc,
            )
            return [
                StepOutcome(
                    name="failure",
                    context=context,
                    summary=f"lost connection to ISE source '{source_id}': {exc}",
                )
            ]
        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError(f"{_STEP_ID}: failed for device '{device.name}': {exc}") from exc

        if secret:
            updated_devices[device_id] = set_device_attribute(
                device, "tacacs.shared_secret", seal_secret(secret)
            )
            found_count += 1
            logger.info(
                "%s: found tacacs key for device=%s tier=%s", _STEP_ID, device.name, matched_tier
            )
        else:
            updated_devices[device_id] = _mark_not_found(
                device, node_id=node_id, source_id=source_id
            )
            not_found_count += 1

    metadata = {
        **context.metadata,
        f"{node_id}.total": len(context.devices),
        f"{node_id}.found_count": found_count,
        f"{node_id}.already_present_count": already_present_count,
        f"{node_id}.not_found_count": not_found_count,
    }

    logger.info(
        "%s finished node_id=%s found=%d already_present=%d not_found=%d run_id=%s",
        _STEP_ID,
        node_id,
        found_count,
        already_present_count,
        not_found_count,
        context.run_id,
    )

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": updated_devices, "metadata": metadata}),
            summary=(
                f"found {found_count}, already had key {already_present_count}, "
                f"not found {not_found_count}"
            ),
        )
    ]
```

### Code after — `backend/workflow_steps/get_ise_tacacs_key/executor.py` (`execute`, ~76 lines)

```python
async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service

    source_id = (config.get("ise_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: ise_source_id is not configured")

    priority = _parse_priority(config)
    location_group_prefix = _parse_location_group_prefix(config)

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    device_service = _resolve_ise_device_service(run, source_id)

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        len(context.devices),
    )

    try:
        await device_service.test_connection()
    except ISEAPIError as exc:
        logger.warning("%s: could not reach ISE source '%s': %s", _STEP_ID, source_id, exc)
        return [_ise_unreachable_outcome(context, source_id, exc, prefix="could not reach")]

    loop_result = await _process_devices_for_tacacs_key(
        devices=context.devices,
        device_service=device_service,
        priority=priority,
        location_group_prefix=location_group_prefix,
        node_id=node_id,
        source_id=source_id,
        context=context,
    )
    if isinstance(loop_result, list):
        return loop_result

    updated_devices, found_count, already_present_count, not_found_count = loop_result
    metadata = _build_tacacs_result_metadata(
        context, node_id, found_count, already_present_count, not_found_count
    )

    logger.info(
        "%s finished node_id=%s found=%d already_present=%d not_found=%d run_id=%s",
        _STEP_ID,
        node_id,
        found_count,
        already_present_count,
        not_found_count,
        context.run_id,
    )

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(
                update={"devices": updated_devices, "metadata": metadata}
            ),
            summary=(
                f"found {found_count}, already had key {already_present_count}, "
                f"not found {not_found_count}"
            ),
        )
    ]
```

---

## Step 27: `execute` — 141 → ~54 lines

**File:** `backend/workflow_steps/render_jinja_template/executor.py`
**What:** Lift nested render_device; partition + build outcomes.
**Why:** Still ≥80 lines after passes 1–2; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md` / `11_to_20.md`.

**Helpers to extract:**

- `_mark_render_failed`
- `_render_and_store_device`
- `_partition_render_results`
- `_build_render_outcomes`

### Code before — `backend/workflow_steps/render_jinja_template/executor.py` (`execute`, 141 lines)

```python
async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    output_key = parse_output_key(config.get("output_key") or _default_config()["output_key"])
    template = _resolve_template(config)

    logger.info(
        "render-jinja-template run_id=%s devices=%d output_key=%s",
        run.id,
        len(context.devices),
        output_key,
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def render_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        try:
            jinja_context = build_jinja_context(
                device,
                run_id=context.run_id,
                workflow_id=context.workflow_id,
            )
            jinja_context.update(await _build_command_context(device, artifact_service))
            rendered = render_jinja_template(template, jinja_context)
            artifact_ref = await artifact_service.store(
                content=rendered,
                kind="rendered_template",
                device_id=device_id,
                run_id=context.run_id,
            )
            parsed = dict(device.parsed)
            parsed[output_key] = _parsed_template_entry(
                artifact_ref=artifact_ref,
                node_id=node_id,
                output_key=output_key,
                size_bytes=len(rendered.encode("utf-8")),
            )
            enriched = device.model_copy(
                update={
                    "parsed": parsed,
                    "capabilities": device.capabilities | {Capability.PARSED},
                    "status": DeviceStatus.OK,
                }
            )
            return device_id, enriched, True
        except (JinjaTemplateError, ValueError) as exc:
            logger.warning(
                "render-jinja-template failed run_id=%s node_id=%s device_id=%s error=%s",
                run.id,
                node_id,
                device_id,
                exc,
            )
            err = DeviceError(
                node_id=node_id,
                step_id="render-jinja-template",
                code="template_error",
                message=str(exc),
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                }
            )
            return device_id, failed, False
        except Exception as exc:
            logger.warning(
                "render-jinja-template failed run_id=%s node_id=%s device_id=%s error=%s",
                run.id,
                node_id,
                device_id,
                exc,
            )
            err = DeviceError(
                node_id=node_id,
                step_id="render-jinja-template",
                code=type(exc).__name__.lower(),
                message=str(exc),
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                }
            )
            return device_id, failed, False

    results = await asyncio.gather(
        *[render_device(device_id, device) for device_id, device in context.devices.items()]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    metadata = {
        **context.metadata,
        f"{node_id}.rendered_template_key": output_key,
        f"{node_id}.rendered_success_count": len(success_devices),
        f"{node_id}.rendered_failure_count": len(failed_devices),
    }

    logger.info(
        "render-jinja-template finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        run.id,
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices, "metadata": metadata}),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(
                    update={"devices": failed_devices, "metadata": metadata}
                ),
            )
        )
    return outcomes
```

### Code after — `backend/workflow_steps/render_jinja_template/executor.py` (`execute`, ~54 lines)

```python
async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    output_key = parse_output_key(config.get("output_key") or _default_config()["output_key"])
    template = _resolve_template(config)

    logger.info(
        "render-jinja-template run_id=%s devices=%d output_key=%s",
        run.id,
        len(context.devices),
        output_key,
    )

    results = await asyncio.gather(
        *[
            _render_and_store_device(
                device_id,
                device,
                template=template,
                output_key=output_key,
                node_id=node_id,
                context=context,
                run=run,
                artifact_service=artifact_service,
            )
            for device_id, device in context.devices.items()
        ]
    )

    success_devices, failed_devices = _partition_render_results(results)
    metadata = {
        **context.metadata,
        f"{node_id}.rendered_template_key": output_key,
        f"{node_id}.rendered_success_count": len(success_devices),
        f"{node_id}.rendered_failure_count": len(failed_devices),
    }

    logger.info(
        "render-jinja-template finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        run.id,
    )

    return _build_render_outcomes(context, success_devices, failed_devices, metadata)
```

---

## Step 28: `get_diagnostics` — 139 → ~26 lines

**File:** `backend/services/git/debug_service.py`
**What:** Split local/ssl/auth+push diagnostic collectors.
**Why:** Still ≥80 lines after passes 1–2; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md` / `11_to_20.md`.

**Helpers to extract:**

- `_repository_info_section`
- `_collect_local_repo_diagnostics`
- `_collect_ssl_diagnostics`
- `_collect_auth_and_push_diagnostics`

### Code before — `backend/services/git/debug_service.py` (`get_diagnostics`, 139 lines)

```python
    def get_diagnostics(self, repo_id: int, git_auth_service) -> dict[str, Any]:
        """Return comprehensive diagnostic information for the repository."""
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        diagnostics: dict[str, Any] = {
            "repository_info": {
                "id": repository["id"],
                "name": repository["name"],
                "url": repository["url"],
                "branch": repository["branch"],
                "is_active": repository["is_active"],
                "verify_ssl": repository.get("verify_ssl", True),
            },
            "access_test": {},
            "file_system": {},
            "git_status": {},
            "ssl_info": {},
            "credentials": {},
            "push_capability": {},
        }

        try:
            repo = get_git_repo_by_id(repo_id)
            repo_path = Path(repo.working_dir)

            diagnostics["access_test"] = {
                "accessible": True,
                "path": str(repo_path),
                "exists": repo_path.exists(),
            }

            try:
                diagnostics["file_system"] = {
                    "readable": os.access(str(repo_path), os.R_OK),
                    "writable": os.access(str(repo_path), os.W_OK),
                    "executable": os.access(str(repo_path), os.X_OK),
                    "path": str(repo_path),
                }
            except Exception as e:
                diagnostics["file_system"] = {"error": str(e), "error_type": type(e).__name__}

            try:
                diagnostics["git_status"] = {
                    "is_dirty": repo.is_dirty(untracked_files=True),
                    "active_branch": repo.active_branch.name,
                    "head_commit": (
                        repo.head.commit.hexsha[:8] if repo.head.is_valid() else "no commits"
                    ),
                    "remotes": [r.name for r in repo.remotes],
                    "has_origin": "origin" in [r.name for r in repo.remotes],
                }
            except Exception as e:
                diagnostics["git_status"] = {"error": str(e), "error_type": type(e).__name__}

        except Exception as e:
            diagnostics["access_test"] = {
                "accessible": False,
                "error": str(e),
                "error_type": type(e).__name__,
            }

        try:
            if not repository.get("verify_ssl", True):
                diagnostics["ssl_info"] = {
                    "verification": "disabled",
                    "note": "SSL verification is disabled for this repository",
                }
            else:
                diagnostics["ssl_info"] = {
                    "verification": "enabled",
                    "ssl_version": ssl.OPENSSL_VERSION,
                }
        except Exception as e:
            diagnostics["ssl_info"] = {"error": str(e), "error_type": type(e).__name__}

        try:
            username, token, ssh_key_path = git_auth_service.resolve_credentials(repository)
            auth_type = repository.get("auth_type", "token")

            diagnostics["credentials"] = {
                "credential_name": repository.get("credential_name", "none"),
                "auth_type": auth_type,
                "has_username": bool(username),
                "has_token": bool(token),
                "has_ssh_key": bool(ssh_key_path),
                "token_length": len(token) if token else 0,
                "authentication": "configured" if (username and token) or ssh_key_path else "none",
            }

            if auth_type == "ssh_key":
                has_credentials = bool(ssh_key_path)
            elif auth_type == "token":
                has_credentials = bool(username and token)
            else:
                has_credentials = False

            has_remote = False
            remote_url = "unknown"
            try:
                repo = get_git_repo_by_id(repo_id)
                if "origin" in [r.name for r in repo.remotes]:
                    has_remote = True
                    origin = repo.remote("origin")
                    remote_url = list(origin.urls)[0] if origin.urls else "unknown"
            except Exception:
                pass

            if has_credentials and has_remote:
                push_status, push_message = "ready", "Push capability is configured and ready"
            elif not has_credentials:
                push_status, push_message = (
                    "no_credentials",
                    "Push requires authentication credentials",
                )
            elif not has_remote:
                push_status, push_message = "no_remote", "No remote 'origin' configured"
            else:
                push_status, push_message = "unknown", "Push capability status unclear"

            diagnostics["push_capability"] = {
                "status": push_status,
                "message": push_message,
                "has_credentials": has_credentials,
                "has_remote": has_remote,
                "remote_url": remote_url,
                "can_push": has_credentials and has_remote,
            }

        except Exception as e:
            diagnostics["credentials"] = {"error": str(e), "error_type": type(e).__name__}
            diagnostics["push_capability"] = {
                "status": "error",
                "message": f"Failed to assess push capability: {str(e)}",
                "can_push": False,
            }

        return {"success": True, "repository_id": repo_id, "diagnostics": diagnostics}
```

### Code after — `backend/services/git/debug_service.py` (`get_diagnostics`, ~26 lines)

```python
def get_diagnostics(self, repo_id: int, git_auth_service) -> dict[str, Any]:
    """Return comprehensive diagnostic information for the repository."""
    repository = git_repo_manager.get_repository(repo_id)
    if not repository:
        raise ValueError(f"Repository {repo_id} not found")

    diagnostics: dict[str, Any] = {
        "repository_info": _repository_info_section(repository),
        "access_test": {},
        "file_system": {},
        "git_status": {},
        "ssl_info": {},
        "credentials": {},
        "push_capability": {},
    }

    diagnostics.update(_collect_local_repo_diagnostics(repo_id))
    diagnostics["ssl_info"] = _collect_ssl_diagnostics(repository)

    creds_section, push_section = _collect_auth_and_push_diagnostics(
        repo_id, repository, git_auth_service
    )
    diagnostics["credentials"] = creds_section
    diagnostics["push_capability"] = push_section

    return {"success": True, "repository_id": repo_id, "diagnostics": diagnostics}
```

---

## Step 29: `_query_devices_by_location` — 139 → ~24 lines

**File:** `backend/services/sources/nautobot/live_query_mixin.py`
**What:** Shared device GraphQL selection + filter-arg/query builders (pair with rank 24).
**Why:** Still ≥80 lines after passes 1–2; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md` / `11_to_20.md`.

**Helpers to extract:**

- `_DEVICE_SELECTION_FIELDS`
- `_resolve_location_filter_arg`
- `_location_devices_query`

### Code before — `backend/services/sources/nautobot/live_query_mixin.py` (`_query_devices_by_location`, 139 lines)

```python
    async def _query_devices_by_location(
        self,
        location_filter: str,
        use_contains: bool = False,
        use_negation: bool = False,
    ) -> list[DeviceInfo]:
        """Query devices by location using GraphQL.

        Intentionally kept as a live Nautobot call: Nautobot resolves the full
        child-location hierarchy server-side.  Replicating that logic in Python
        would require fetching and traversing the entire location tree, which is
        more expensive than a single filtered GraphQL query.

        Args:
            location_filter: Location name or ID to filter by
            use_contains: Use case-insensitive contains matching
            use_negation: Use negation (location__n) to exclude devices from this location
        """
        if not location_filter or location_filter.strip() == "":
            logger.warning("Empty location_filter provided, returning empty result")
            return []

        if use_negation:
            query = """
            query devices_by_location ($location_filter: [String]) {
                devices (location__n: $location_filter) {
                    id
                    name
                    serial
                    role {
                        name
                    }
                    location {
                        name
                    }
                    primary_ip4 {
                        address
                    }
                    status {
                        name
                    }
                    device_type {
                        model
                        manufacturer {
                            name
                        }
                    }
                    tags {
                        name
                    }
                    platform {
                        name
                        network_driver
                    }
                }
            }
            """
        elif use_contains:
            query = """
            query devices_by_location ($location_filter: [String]) {
                devices (location__name__ic: $location_filter) {
                    id
                    name
                    serial
                    role {
                        name
                    }
                    location {
                        name
                    }
                    primary_ip4 {
                        address
                    }
                    status {
                        name
                    }
                    device_type {
                        model
                        manufacturer {
                            name
                        }
                    }
                    tags {
                        name
                    }
                    platform {
                        name
                        network_driver
                    }
                }
            }
            """
        else:
            query = """
            query devices_by_location ($location_filter: [String]) {
                devices (location: $location_filter) {
                    id
                    name
                    serial
                    role {
                        name
                    }
                    location {
                        name
                    }
                    primary_ip4 {
                        address
                    }
                    status {
                        name
                    }
                    device_type {
                        model
                        manufacturer {
                            name
                        }
                    }
                    tags {
                        name
                    }
                    platform {
                        name
                        network_driver
                    }
                }
            }
            """

        variables = {"location_filter": [location_filter]}
        result = await self._nautobot.graphql_query(query, variables, self._credentials)

        logger.info(
            "GraphQL result for location query '%s': Found %s devices",
            location_filter,
            len(result.get("data", {}).get("devices", [])),
        )

        devices_data = result.get("data", {}).get("devices", [])
        return self._parse_device_data(devices_data)
```

### Code after — `backend/services/sources/nautobot/live_query_mixin.py` (`_query_devices_by_location`, ~24 lines)

```python
async def _query_devices_by_location(
    self,
    location_filter: str,
    use_contains: bool = False,
    use_negation: bool = False,
) -> list[DeviceInfo]:
    """Query devices by location using GraphQL (live; hierarchy is server-side)."""
    if not location_filter or location_filter.strip() == "":
        logger.warning("Empty location_filter provided, returning empty result")
        return []

    filter_arg = _resolve_location_filter_arg(use_contains, use_negation)
    query = _location_devices_query(filter_arg)
    variables = {"location_filter": [location_filter]}
    result = await self._nautobot.graphql_query(query, variables, self._credentials)

    logger.info(
        "GraphQL result for location query '%s': Found %s devices",
        location_filter,
        len(result.get("data", {}).get("devices", [])),
    )

    devices_data = result.get("data", {}).get("devices", [])
    return self._parse_device_data(devices_data)
```

---

## Step 30: `get_repository_status` — 136 → ~22 lines

**File:** `backend/services/git/operations.py`
**What:** Extract local metadata / cache commits / remote sync / config-file scan helpers.
**Why:** Still ≥80 lines after passes 1–2; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md` / `11_to_20.md`.

**Helpers to extract:**

- `_empty_repository_status`
- `_fill_local_git_metadata`
- `_fill_cached_commits`
- `_fill_remote_sync_status`
- `_scan_config_files`

### Code before — `backend/services/git/operations.py` (`get_repository_status`, 136 lines)

```python
    def get_repository_status(self, repository: dict[str, Any], repo_id: int) -> dict[str, Any]:
        """Get comprehensive repository status using GitPython.

        This replaces the old implementation that used 7 subprocess calls
        with a single GitPython Repo instance for ~50% performance improvement.

        Args:
            repository: Repository metadata dict
            repo_id: Repository ID for cache access

        Returns:
            Dictionary with comprehensive status information
        """
        repo_path = str(get_repo_path(repository))

        status_info = {
            "repository_name": repository["name"],
            "repository_url": repository["url"],
            "repository_branch": repository["branch"],
            "sync_status": repository.get("sync_status", "unknown"),
            "exists": os.path.exists(repo_path),
            "is_git_repo": False,
            "is_synced": False,
            "behind_count": 0,
            "ahead_count": 0,
            "current_commit": None,
            "current_branch": None,
            "last_commit_message": None,
            "last_commit_date": None,
            "branches": [],
            "commits": [],
            "config_files": [],
        }

        if not status_info["exists"]:
            return status_info

        # Use GitPython for all git operations (replaces 7 subprocess calls)
        try:
            repo = Repo(repo_path)
            status_info["is_git_repo"] = True

            # Get current branch (replaces subprocess git rev-parse)
            try:
                status_info["current_branch"] = repo.active_branch.name
            except Exception as e:
                logger.warning("Could not get current branch: %s", e)
                status_info["current_branch"] = "HEAD"

            # Get current commit info (replaces subprocess git log)
            try:
                if repo.head.is_valid():
                    commit = repo.head.commit
                    status_info["current_commit"] = commit.hexsha[:8]
                    status_info["last_commit_message"] = commit.message.strip()
                    status_info["last_commit_date"] = commit.committed_datetime.isoformat()
                    status_info["last_commit_author"] = commit.author.name
                    status_info["last_commit_author_email"] = commit.author.email
            except Exception as e:
                logger.warning("Could not get commit info: %s", e)

            # Get list of branches (replaces subprocess git branch)
            try:
                status_info["branches"] = [branch.name for branch in repo.branches]
            except Exception as e:
                logger.warning("Could not list branches: %s", e)

            # Get recent commits using cache service
            try:
                import service_factory

                git_cache_service = service_factory.build_git_cache_service()

                status_info["commits"] = git_cache_service.get_commits(
                    repo_id=repo_id,
                    repo_path=repo_path,
                    branch_name=repository["branch"],
                    limit=50,
                    use_models=False,
                )
            except Exception as e:
                logger.warning("Could not get recent commits: %s", e)
                status_info["commits"] = []

            # Check if repository is synced with remote (replaces subprocess git fetch/rev-list)
            try:
                if "origin" in [r.name for r in repo.remotes]:
                    origin = repo.remote("origin")

                    # Fetch to update remote refs
                    try:
                        origin.fetch()
                    except Exception as fetch_error:
                        logger.debug("Fetch failed: %s", fetch_error)

                    # Calculate commits behind/ahead using GitPython
                    try:
                        remote_branch = f"origin/{repository['branch']}"
                        if remote_branch in [ref.name for ref in repo.refs]:
                            # Commits behind (replaces git rev-list HEAD..origin/branch)
                            behind = list(
                                repo.iter_commits(f"HEAD..{remote_branch}", max_count=100)
                            )
                            status_info["behind_count"] = len(behind)

                            # Commits ahead (replaces git rev-list origin/branch..HEAD)
                            ahead = list(repo.iter_commits(f"{remote_branch}..HEAD", max_count=100))
                            status_info["ahead_count"] = len(ahead)

                            status_info["is_synced"] = status_info["behind_count"] == 0
                    except Exception as rev_error:
                        logger.debug("Could not calculate ahead/behind: %s", rev_error)
            except Exception as e:
                logger.warning("Could not check sync status: %s", e)
                status_info["is_synced"] = False

            # Get list of configuration files (filesystem operation)
            try:
                for root, _dirs, files in os.walk(repo_path):
                    # Skip .git directory
                    if ".git" in root:
                        continue

                    for file in files:
                        if not file.startswith("."):
                            rel_path = os.path.relpath(os.path.join(root, file), repo_path)
                            status_info["config_files"].append(rel_path)

                status_info["config_files"].sort()
            except Exception as e:
                logger.warning("Could not scan config files: %s", e)

        except Exception as e:
            logger.warning("Error checking Git repository status: %s", e)

        return status_info
```

### Code after — `backend/services/git/operations.py` (`get_repository_status`, ~22 lines)

```python
def get_repository_status(self, repository: dict[str, Any], repo_id: int) -> dict[str, Any]:
    """Get comprehensive repository status using GitPython."""
    repo_path = str(get_repo_path(repository))
    status_info = _empty_repository_status(repository, repo_path)

    if not status_info["exists"]:
        return status_info

    try:
        repo = Repo(repo_path)
        status_info["is_git_repo"] = True
        _fill_local_git_metadata(repo, status_info)
        _fill_cached_commits(status_info, repo_id, repo_path, repository["branch"])
        _fill_remote_sync_status(repo, status_info, repository["branch"])
        try:
            status_info["config_files"] = _scan_config_files(repo_path)
        except Exception as e:
            logger.warning("Could not scan config files: %s", e)
    except Exception as e:
        logger.warning("Error checking Git repository status: %s", e)

    return status_info
```

---

