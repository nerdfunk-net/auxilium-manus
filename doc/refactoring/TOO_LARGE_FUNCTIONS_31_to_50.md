# Refactoring Plan — Oversized Functions 31–50

**Date:** 2026-08-03
**Based on:** `doc/TOO_LARGE_FUNCTIONS.md` (post pass-3 remaining ≥80);
  prior plans `TOO_LARGE_FUNCTIONS_1_to_10.md`, `_11_to_20.md`, `_21_to_30.md`;
  `doc/FABLE-ANALYSIS.md` §5.2
**Pattern:** same as passes 1–3 — `_parse_*` / phase helpers / `_build_outcomes`;
  exemplar `workflow_steps/update_nautobot_device/executor.py`
**Goal:** Bring each of the next 20 longest remaining functions under the 80-line
  offender threshold (style rule remains `<50` lines). Rank 31 is an intentional
  skip (docstring kept).

> Status: **Implemented** (with one intentional skip). "Code before" was the live tree at
> plan time; actual after-line counts are in the Summary table. Rank 31 (`update_device`)
> was **left unchanged** — docstring kept per prior pass. Full suite + four regression
> guards green. Remaining functions ≥80: **31** (was 50).

## Target selection

Passes 1–3 closed ranks 1–30 (except rank 23 / this pass’s rank 31 `update_device`,
whose docstring was intentionally kept). A fresh AST rescan of `backend/` (excluding
`tests/` / `migrations/`) finds **50** functions still ≥80 lines. The next 20 by
length are ranks 31–50 below.

**Note on rank 31 (`update_device`):** same function as pass-3 rank 23. Executable
body is already thin; AST length is docstring. **Do not shrink the docstring** unless
explicitly requested — mark implemented as skipped.

## Summary

| Rank | Function | Before | After | File |
|---:|---|---:|---:|---|
| 31 | `update_device` | 151 | 151 (skipped — docstring kept) | `backend/services/nautobot/devices/update.py` |
| 32 | `execute` | 136 | 49 | `backend/workflow_steps/parse_cisco_config/executor.py` |
| 33 | `_create_or_update_interface` | 135 | 48 | `backend/services/nautobot/devices/interface_workflow.py` |
| 34 | `_update_one_device` | 126 | 63 | `backend/workflow_steps/update_nautobot_device/executor.py` |
| 35 | `execute` | 125 | 54 | `backend/workflow_steps/get_from_config/executor.py` |
| 36 | `_create_ip_addresses` | 124 | 56 | `backend/services/nautobot/devices/interface_workflow.py` |
| 37 | `_update_device_properties` | 124 | 57 | `backend/services/nautobot/devices/update.py` |
| 38 | `_migrate` | 123 | 30 | `backend/scripts/database/sync.py` |
| 39 | `get_directory_files` | 123 | 37 | `backend/services/git/file_service.py` |
| 40 | `execute` | 123 | 53 | `backend/workflow_steps/get_ise_devices/executor.py` |
| 41 | `_run_steps_until_fan_out_or_done` | 122 | 70 | `backend/hatchet/workflows/workflow_run.py` |
| 42 | `get_file_history` | 121 | 50 | `backend/services/git/file_service.py` |
| 43 | `_dispatch_with_approval` | 120 | 75 | `backend/hatchet/workflows/workflow_run.py` |
| 44 | `update_interface_ip` | 119 | 65 | `backend/services/nautobot/managers/interface_manager.py` |
| 45 | `search_files` | 117 | 50 | `backend/services/git/file_service.py` |
| 46 | `sync_repository` | 117 | 54 | `backend/services/git/operations.py` |
| 47 | `ensure_prefix_exists` | 117 | 43 | `backend/services/nautobot/managers/prefix_manager.py` |
| 48 | `_execute_operation` | 116 | 49 | `backend/services/sources/nautobot/evaluator.py` |
| 49 | `execute` | 116 | 44 | `backend/workflow_steps/list_contains/executor.py` |
| 50 | `execute_subgraph` | 112 | 79 | `backend/services/execution/step_runner.py` |

## Implementation order

| Order | Rank | Risk | Notes |
|---:|---:|---|---|
| 1 | 45 | low | Pure FS search + soft-fail envelope |
| 2 | 49 | low | Same step-executor pattern as prior passes |
| 3 | 38 | low | Dev schema tooling; no runtime path |
| 4 | 47 | low | REST lookup/create; docstring shrink |
| 5 | 44 | low | Fallback dedupe + docstring |
| 6 | 39 | low | Directory listing path + commit metadata |
| 7 | 32 | low | Fan-out parse executor |
| 8 | 31 | n/a | SKIP — docstring kept |
| 9 | 48 | medium | AND/OR/NOT set algebra |
| 10 | 42 | medium | SHA prefix match + soft prepend |
| 11 | 46 | medium | Clone cleanup / auth wrap |
| 12 | 50 | medium | Fan-out subgraph error fold contract |
| 13 | 34 | medium | interfaces_failed hard-fail + dual shapes |
| 14 | 35 | medium | DB session only around source config load |
| 15 | 36 | medium | Missing-prefix re-raise when auto-prefix off |
| 16 | 37 | medium | primary_ip4 create-vs-update + verify |
| 17 | 33 | medium | Unique-constraint race PATCH fallback |
| 18 | 40 | medium | CIDR expand + keep raw ISE when resolve empty |
| 19 | 41 | high | Durable debug waits + suspend sessions |
| 20 | 43 | high | Durable approval + SessionLocal boundaries |

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

## Step 31: `update_device` — 151 → ~151 lines

**File:** `backend/services/nautobot/devices/update.py`
**What:** SKIP — docstring intentionally kept from pass 3; executable body already thin (~60 lines of orchestration).
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Status:** **SKIP** — leave docstring and body unchanged.

### Code before — live body (unchanged)

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

### Code after

_Same as before — no change._

---

## Step 32: `execute` — 136 → ~48 lines

**File:** `backend/workflow_steps/parse_cisco_config/executor.py`
**What:** Lift per-device parse + outcome builders out of nested `parse_device`.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_parse_one_device`
- `_build_parse_entry`
- `_partition_parse_results`
- `_build_parse_outcomes`

### Code before — `backend/workflow_steps/parse_cisco_config/executor.py` (`execute`, 136 lines)

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

    config_source = _parse_config_source(config)
    output_key = parse_output_key(config.get("output_key") or get_config()["output_key"])
    need_running, need_startup = _config_targets(config_source)

    logger.info(
        "parse-cisco-config started run_id=%s node_id=%s devices=%d config_source=%s output_key=%s",
        run.id,
        node_id,
        len(context.devices),
        config_source,
        output_key,
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def parse_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        platform_hint = _platform_hint(device)
        try:
            running_model: dict[str, Any] | None = None
            startup_model: dict[str, Any] | None = None

            if need_running:
                if device.running_config_ref is None:
                    raise ValueError(
                        "running config is not available on this device — add a "
                        "Get Configs step upstream with running config enabled"
                    )
                running_text = await artifact_service.resolve(device.running_config_ref)
                running_model = parse_cisco_config_text(running_text, platform_hint)

            if need_startup:
                if device.startup_config_ref is None:
                    raise ValueError(
                        "startup config is not available on this device — add a "
                        "Get Configs step upstream with startup config enabled"
                    )
                startup_text = await artifact_service.resolve(device.startup_config_ref)
                startup_model = parse_cisco_config_text(startup_text, platform_hint)

            if config_source == "both":
                entry: dict[str, Any] | None = {
                    "running": running_model,
                    "startup": startup_model,
                }
            elif config_source == "running":
                entry = running_model
            else:
                entry = startup_model

            parsed = dict(device.parsed)
            parsed[output_key] = entry
            enriched = device.model_copy(
                update={
                    "parsed": parsed,
                    "capabilities": device.capabilities | {Capability.PARSED},
                    "status": DeviceStatus.OK,
                }
            )
            return device_id, enriched, True
        except Exception as exc:
            logger.warning(
                "parse-cisco-config failed run_id=%s node_id=%s device_id=%s error=%s",
                run.id,
                node_id,
                device_id,
                exc,
            )
            err = DeviceError(
                node_id=node_id,
                step_id="parse-cisco-config",
                code="config_error" if isinstance(exc, ValueError) else type(exc).__name__.lower(),
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
        *[parse_device(device_id, device) for device_id, device in context.devices.items()]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    metadata = {
        **context.metadata,
        f"{node_id}.parse_success_count": len(success_devices),
        f"{node_id}.parse_failure_count": len(failed_devices),
    }

    logger.info(
        "parse-cisco-config finished success=%d failure=%d run_id=%s",
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

### Code after — planned (`execute`, ~48 lines)

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

    config_source = _parse_config_source(config)
    output_key = parse_output_key(config.get("output_key") or get_config()["output_key"])
    need_running, need_startup = _config_targets(config_source)

    logger.info(
        "parse-cisco-config started run_id=%s node_id=%s devices=%d config_source=%s output_key=%s",
        run.id, node_id, len(context.devices), config_source, output_key,
    )

    results = await asyncio.gather(
        *[
            _parse_one_device(
                device_id=device_id,
                device=device,
                artifact_service=artifact_service,
                run_id=run.id,
                node_id=node_id,
                need_running=need_running,
                need_startup=need_startup,
                config_source=config_source,
                output_key=output_key,
            )
            for device_id, device in context.devices.items()
        ]
    )
    success_devices, failed_devices = _partition_parse_results(results)
    return _build_parse_outcomes(
        context=context,
        node_id=node_id,
        run_id=run.id,
        success_devices=success_devices,
        failed_devices=failed_devices,
    )
```

---

## Step 33: `_create_or_update_interface` — 135 → ~42 lines

**File:** `backend/services/nautobot/devices/interface_workflow.py`
**What:** Split payload build / existing PATCH / create-with-unique-race fallback.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_normalize_interface_type`
- `_build_interface_payload`
- `_patch_existing_interface`
- `_create_interface_with_race_fallback`

### Code before — `backend/services/nautobot/devices/interface_workflow.py` (`_create_or_update_interface`, 135 lines)

```python
    async def _create_or_update_interface(
        self,
        device_id: str,
        interface: dict[str, Any],
        warnings: list[str],
    ) -> tuple[str | None, bool]:
        """
        Create or update a single interface.

        Args:
            device_id: Device UUID
            interface: Interface specification
            warnings: List to append warnings to

        Returns:
            Tuple of (interface UUID if successful, was_updated flag)
        """
        # Validate required fields before hitting Nautobot
        # Nautobot interface type slugs are always lowercase (e.g. "virtual", "1000base-t")
        # Frontend may store the display name (e.g. "Virtual") — normalize to lowercase slug
        interface_type = (interface.get("type") or "").strip().lower()
        if not interface_type:
            warnings.append(
                f"Interface {interface['name']}: 'type' is required but was not provided — skipping"
            )
            logger.warning("Interface '%s' has no type set, skipping creation", interface["name"])
            return None, False

        # Resolve status to UUID — use "or" fallback so empty string also defaults to "active"
        interface_status = interface.get("status") or "active"
        interface_status_id = await self.common.resolve_status_id(
            interface_status, "dcim.interface"
        )

        interface_payload: dict[str, Any] = {
            "name": interface["name"],
            "device": device_id,
            "type": interface_type,
            "status": interface_status_id,
        }

        optional_fields = [
            "enabled",
            "mgmt_only",
            "description",
            "mac_address",
            "mtu",
            "mode",
        ]
        for field in optional_fields:
            if field in interface and interface[field] is not None:
                # "none" is the UI sentinel for "no mode"; Nautobot rejects it
                if field == "mode" and interface[field] == "none":
                    continue
                interface_payload[field] = interface[field]

        # Nautobot REST API requires VLAN references as {"id": uuid}
        untagged_vlan = interface.get("untagged_vlan")
        if untagged_vlan and untagged_vlan != "none":
            interface_payload["untagged_vlan"] = {"id": untagged_vlan}

        tagged_vlans = interface.get("tagged_vlans")
        if tagged_vlans:
            interface_payload["tagged_vlans"] = [{"id": vid} for vid in tagged_vlans]

        existing_id = await self.common.resolve_interface_by_name(
            device_id=device_id,
            interface_name=interface["name"],
        )
        if existing_id:
            patch_payload = {
                k: v for k, v in interface_payload.items() if k not in ("name", "device")
            }
            try:
                await self.nautobot.rest_request(
                    endpoint=f"dcim/interfaces/{existing_id}/",
                    method="PATCH",
                    data=patch_payload,
                )
                logger.info("Updated interface %s with ID: %s", interface["name"], existing_id)
                return existing_id, True
            except Exception as patch_error:
                warnings.append(f"Interface {interface['name']}: Failed to update: {patch_error}")
                return existing_id, True

        logger.debug("Creating interface with payload: %s", interface_payload)

        try:
            interface_response = await self.nautobot.rest_request(
                endpoint="dcim/interfaces/",
                method="POST",
                data=interface_payload,
            )

            if interface_response and "id" in interface_response:
                interface_id = interface_response["id"]
                logger.info("Created interface %s with ID: %s", interface["name"], interface_id)
                return interface_id, False

        except Exception as create_error:
            if "must make a unique set" in str(create_error).lower():
                interface_id = await self.common.resolve_interface_by_name(
                    device_id=device_id,
                    interface_name=interface["name"],
                )
                if interface_id:
                    patch_payload = {
                        k: v for k, v in interface_payload.items() if k not in ("name", "device")
                    }
                    try:
                        await self.nautobot.rest_request(
                            endpoint=f"dcim/interfaces/{interface_id}/",
                            method="PATCH",
                            data=patch_payload,
                        )
                    except Exception as patch_error:
                        warnings.append(
                            f"Interface {interface['name']}: Failed to patch: {patch_error}"
                        )
                    return interface_id, True
                warnings.append(
                    f"Interface {interface['name']}: Interface exists but could not be found"
                )
            else:
                logger.error(
                    "Failed to create interface '%s': %s",
                    interface["name"],
                    str(create_error),
                )
                warnings.append(
                    f"Interface {interface['name']}: Failed to create interface: "
                    f"{str(create_error)}"
                )

        return None, False
```

### Code after — planned (`_create_or_update_interface`, ~42 lines)

```python
async def _create_or_update_interface(
    self,
    device_id: str,
    interface: dict[str, Any],
    warnings: list[str],
) -> tuple[str | None, bool]:
    interface_type = _normalize_interface_type(interface, warnings)
    if interface_type is None:
        return None, False

    interface_status = interface.get("status") or "active"
    interface_status_id = await self.common.resolve_status_id(
        interface_status, "dcim.interface"
    )
    interface_payload = _build_interface_payload(
        device_id=device_id,
        interface=interface,
        interface_type=interface_type,
        interface_status_id=interface_status_id,
    )

    existing_id = await self.common.resolve_interface_by_name(
        device_id=device_id,
        interface_name=interface["name"],
    )
    if existing_id:
        return await self._patch_existing_interface(
            existing_id, interface, interface_payload, warnings
        )

    return await self._create_interface_with_race_fallback(
        device_id=device_id,
        interface=interface,
        interface_payload=interface_payload,
        warnings=warnings,
    )
```

---

## Step 34: `_update_one_device` — 126 → ~68 lines

**File:** `backend/workflow_steps/update_nautobot_device/executor.py`
**What:** Extract fail/success mapping; keep interfaces_failed hard-fail and dual device/placeholder shapes.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_fail_device`
- `_apply_update_result`

### Code before — `backend/workflow_steps/update_nautobot_device/executor.py` (`_update_one_device`, 126 lines)

```python
async def _update_one_device(
    *,
    device_key: str,
    device: DeviceContext | None,
    config: dict[str, Any],
    context: WorkflowContext,
    node_id: str,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    update_service: DeviceUpdateService,
    parsed: _ParsedConfig,
) -> tuple[str, DeviceContext | None, bool, str | None]:
    try:
        nautobot_device_id: str | None = None
        if device is not None:
            nautobot_device_id = await resolve_nautobot_device_id(
                nautobot_service=nautobot_service,
                credentials=credentials,
                device=device,
            )
            if nautobot_device_id is None:
                err = DeviceError(
                    node_id=node_id,
                    step_id=_STEP_ID,
                    code="not_found",
                    message=(
                        f"No Nautobot device found for workflow device {device_key} "
                        f"(name={device.name!r}, ip={device.primary_ip4!r})"
                    ),
                )
                failed = device.model_copy(
                    update={
                        "status": DeviceStatus.FAILED,
                        "errors": [*device.errors, err],
                    }
                )
                return device_key, failed, False, None

        device_identifier = _resolve_device_identifier(
            config=config,
            device=device or DeviceContext(id=device_key, name=device_key, hostname=device_key),
            nautobot_device_id=nautobot_device_id,
        )
        if not any(device_identifier.get(k) for k in ("id", "name", "ip_address")):
            raise ValueError("device identifier must include id, name, or ip_address")

        resolved_device = device or DeviceContext(
            id=device_key,
            name=device_key,
            hostname=device_key,
        )
        update_data = build_resolved_update_data(
            device=resolved_device,
            raw_fields=parsed.raw_update_fields,
            run_id=str(context.run_id) if context.run_id else None,
        )

        result = await update_service.update_device(
            device_identifier=device_identifier,
            update_data=update_data,
            interfaces=parsed.interfaces or None,
            add_prefix=parsed.add_prefix,
            default_prefix_length=parsed.default_prefix_length,
            sync_interfaces=parsed.sync_interfaces,
        )

        interfaces_failed = int(result.get("interfaces_failed") or 0)
        if interfaces_failed > 0:
            raise RuntimeError(
                f"{interfaces_failed} interface update(s) failed for device "
                f"{result.get('device_name') or device_key}"
            )

        if device is None:
            device_name = result.get("device_name") or device_key
            placeholder = DeviceContext(
                id=result.get("device_id") or device_key,
                name=device_name,
                hostname=device_name,
                source="nautobot",
                status=DeviceStatus.OK,
            )
            return device_key, placeholder, True, result.get("device_id")

        enriched = device.model_copy(
            update={
                "id": str(result.get("device_id") or device.id),
                "name": result.get("device_name") or device.name,
                "source": "nautobot",
                "status": DeviceStatus.OK,
            }
        )
        return device_key, enriched, True, result.get("device_id")
    except Exception as exc:
        message = str(exc)
        if device is None:
            placeholder = DeviceContext(
                id=device_key,
                name=device_key,
                hostname=device_key,
                source="nautobot",
                status=DeviceStatus.FAILED,
                errors=[
                    DeviceError(
                        node_id=node_id,
                        step_id=_STEP_ID,
                        code=type(exc).__name__.lower(),
                        message=message,
                    )
                ],
            )
            return device_key, placeholder, False, None

        err = DeviceError(
            node_id=node_id,
            step_id=_STEP_ID,
            code=type(exc).__name__.lower(),
            message=message,
        )
        failed = device.model_copy(
            update={
                "status": DeviceStatus.FAILED,
                "errors": [*device.errors, err],
            }
        )
        return device_key, failed, False, None
```

### Code after — planned (`_update_one_device`, ~68 lines)

```python
async def _update_one_device(
    *,
    device_key: str,
    device: DeviceContext | None,
    config: dict[str, Any],
    context: WorkflowContext,
    node_id: str,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    update_service: DeviceUpdateService,
    parsed: _ParsedConfig,
) -> tuple[str, DeviceContext | None, bool, str | None]:
    try:
        nautobot_device_id: str | None = None
        if device is not None:
            nautobot_device_id = await resolve_nautobot_device_id(
                nautobot_service=nautobot_service,
                credentials=credentials,
                device=device,
            )
            if nautobot_device_id is None:
                return _fail_device(
                    device_key=device_key,
                    device=device,
                    node_id=node_id,
                    code="not_found",
                    message=(
                        f"No Nautobot device found for workflow device {device_key} "
                        f"(name={device.name!r}, ip={device.primary_ip4!r})"
                    ),
                )

        device_identifier = _resolve_device_identifier(
            config=config,
            device=device or DeviceContext(id=device_key, name=device_key, hostname=device_key),
            nautobot_device_id=nautobot_device_id,
        )
        if not any(device_identifier.get(k) for k in ("id", "name", "ip_address")):
            raise ValueError("device identifier must include id, name, or ip_address")

        resolved = device or DeviceContext(id=device_key, name=device_key, hostname=device_key)
        result = await update_service.update_device(
            device_identifier=device_identifier,
            update_data=build_resolved_update_data(
                device=resolved,
                raw_fields=parsed.raw_update_fields,
                run_id=str(context.run_id) if context.run_id else None,
            ),
            interfaces=parsed.interfaces or None,
            add_prefix=parsed.add_prefix,
            default_prefix_length=parsed.default_prefix_length,
            sync_interfaces=parsed.sync_interfaces,
        )
        if int(result.get("interfaces_failed") or 0) > 0:
            raise RuntimeError(
                f"{result.get('interfaces_failed')} interface update(s) failed for device "
                f"{result.get('device_name') or device_key}"
            )
        return _apply_update_result(device_key=device_key, device=device, result=result)
    except Exception as exc:
        return _fail_device(
            device_key=device_key, device=device, node_id=node_id, exc=exc
        )
```

---

## Step 35: `execute` — 125 → ~52 lines

**File:** `backend/workflow_steps/get_from_config/executor.py`
**What:** Parse config, load git repo, map matches → devices, build fan-out outcome.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_parse_get_from_config`
- `_load_git_repo_for_search`
- `_devices_from_config_matches`
- `_build_get_from_config_outcome`

### Code before — `backend/workflow_steps/get_from_config/executor.py` (`execute`, 125 lines)

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

    git_source_id = (config.get("git_source_id") or "").strip()
    search_text = (config.get("search_text") or "").strip()
    directory = (config.get("directory") or "").strip()
    file_filter = (config.get("file_filter") or "").strip()
    recursive = bool(config.get("recursive", True))
    include_history = bool(config.get("include_history", False))
    case_sensitive = bool(config.get("case_sensitive", False))

    if not git_source_id:
        raise ValueError("get-from-config: git_source_id is not configured")
    if not search_text:
        raise ValueError("get-from-config: search_text is not configured")

    logger.info(
        "get-from-config started run_id=%s git_source_id=%s search_text_len=%d",
        run.id,
        git_source_id,
        len(search_text),
    )

    db = get_db_session()
    try:
        try:
            source_config = SettingsService(db).get_source_config_for_step("git", git_source_id)
        except SourceConfigError as exc:
            raise ValueError(f"get-from-config: {exc}") from exc
    finally:
        db.close()

    loop = asyncio.get_running_loop()
    repo_dir = await loop.run_in_executor(None, lambda: clone_or_pull(source_config))

    search_service = GitContentSearchService()
    matches, files_scanned = await loop.run_in_executor(
        None,
        lambda: search_service.search(
            repo_dir,
            source_config,
            directory=directory,
            file_filter=file_filter,
            recursive=recursive,
            include_history=include_history,
            search_text=search_text,
            case_sensitive=case_sensitive,
        ),
    )

    new_devices: dict[str, DeviceContext] = {}
    for match in matches:
        try:
            parsed = parse_cisco_config_text(match.content, None)
        except ValueError:
            logger.warning(
                "get-from-config: could not parse %s (unrecognized platform) run_id=%s",
                match.file_path,
                run.id,
            )
            continue

        hostname = str(parsed.get("hostname") or "").strip()
        if not hostname:
            logger.warning(
                "get-from-config: no hostname found in %s run_id=%s",
                match.file_path,
                run.id,
            )
            continue

        key = hostname.lower()
        if key in new_devices:
            continue

        new_devices[key] = device_context_from_config_match(
            hostname,
            source_id=git_source_id,
            file_path=match.file_path,
            commit=match.commit,
        )

    devices_by_id = {device.id: device for device in new_devices.values()}

    logger.info(
        "get-from-config finished devices=%d matches=%d files_scanned=%d run_id=%s",
        len(devices_by_id),
        len(matches),
        files_scanned,
        run.id,
    )

    fan_out_metadata = build_fan_out_metadata(config.get("fan_out"), node_id)

    metadata_update: dict[str, Any] = {
        **context.metadata,
        f"{node_id}.source_id": git_source_id,
        f"{node_id}.total": len(devices_by_id),
        f"{node_id}.files_scanned": files_scanned,
        f"{node_id}.matches_found": len(matches),
    }
    if fan_out_metadata is not None:
        metadata_update["_fan_out"] = fan_out_metadata

    new_context = context.model_copy(
        update={
            "devices": {**context.devices, **devices_by_id},
            "metadata": metadata_update,
        }
    )
    return [
        StepOutcome(
            name="success",
            context=new_context,
            summary=(f"Found {len(devices_by_id)} device(s) from {len(matches)} matching file(s)"),
        )
    ]
```

### Code after — planned (`execute`, ~52 lines)

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
    parsed = _parse_get_from_config(config)

    logger.info(
        "get-from-config started run_id=%s git_source_id=%s search_text_len=%d",
        run.id, parsed.git_source_id, len(parsed.search_text),
    )

    loop = asyncio.get_running_loop()
    source_config, repo_dir = await _load_git_repo_for_search(parsed.git_source_id, loop)
    matches, files_scanned = await loop.run_in_executor(
        None,
        lambda: GitContentSearchService().search(
            repo_dir,
            source_config,
            directory=parsed.directory,
            file_filter=parsed.file_filter,
            recursive=parsed.recursive,
            include_history=parsed.include_history,
            search_text=parsed.search_text,
            case_sensitive=parsed.case_sensitive,
        ),
    )
    devices_by_id = _devices_from_config_matches(
        matches, git_source_id=parsed.git_source_id, run_id=run.id
    )
    logger.info(
        "get-from-config finished devices=%d matches=%d files_scanned=%d run_id=%s",
        len(devices_by_id), len(matches), files_scanned, run.id,
    )
    return _build_get_from_config_outcome(
        context=context,
        node_id=node_id,
        config=config,
        git_source_id=parsed.git_source_id,
        devices_by_id=devices_by_id,
        matches_found=len(matches),
        files_scanned=files_scanned,
    )
```

---

## Step 36: `_create_ip_addresses` — 124 → ~48 lines

**File:** `backend/services/nautobot/devices/interface_workflow.py`
**What:** Normalize legacy ip_address vs ip_addresses[]; per-IP ensure helper.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_normalize_interface_ip_list`
- `_ensure_one_interface_ip`
- `_ip_map_key`

### Code before — `backend/services/nautobot/devices/interface_workflow.py` (`_create_ip_addresses`, 124 lines)

```python
    async def _create_ip_addresses(
        self,
        interfaces: list[dict[str, Any]],
        warnings: list[str],
        add_prefixes_automatically: bool = False,
    ) -> dict[str, str]:
        """
        Create IP addresses for all interfaces that need them.

        Uses common.ensure_ip_address_exists() to handle IP creation with proper
        error checking for missing prefixes.

        Args:
            interfaces: List of interface specifications
            warnings: List to append warnings to
            add_prefixes_automatically: Auto-create missing prefix if IP creation fails
                (default: False)

        Returns:
            Dictionary mapping "interface_name:ip_address" to IP UUID
        """
        logger.info("=" * 80)
        logger.info("==== STEP 1: CREATE IP ADDRESSES ====")
        logger.info("=" * 80)
        ip_address_map = {}

        for interface in interfaces:
            logger.info("\n--- Processing interface: %s ---", interface["name"])
            logger.info("Interface data: %s", interface)

            # Handle both formats: ip_addresses (array) and ip_address (string)
            ip_addresses = interface.get("ip_addresses", [])
            if not ip_addresses and interface.get("ip_address"):
                # Backwards compatibility: convert single ip_address to array format
                logger.info("Found single ip_address field, converting to array format")
                ip_addresses = [
                    {
                        "address": interface["ip_address"],
                        "namespace": interface.get("namespace", "Global"),
                        "ip_role": interface.get("ip_role"),
                    }
                ]

            if not ip_addresses:
                logger.info(
                    "No ip_address or ip_addresses field found for interface %s, skipping",
                    interface["name"],
                )
                continue

            logger.info("Found %s IP address(es) to process", len(ip_addresses))

            # Process each IP address for this interface
            for idx, ip_data in enumerate(ip_addresses):
                logger.info("\n  >> Processing IP #%s: %s", idx + 1, ip_data)

                ip_address = ip_data.get("address")
                if not ip_address:
                    logger.warning("  IP data missing 'address' field, skipping")
                    continue

                # Get namespace from IP data or fall back to interface level
                namespace = ip_data.get("namespace") or interface.get("namespace", "Global")
                status = interface.get("status", "active")
                ip_role = ip_data.get("ip_role")

                logger.info(
                    "  Extracted values: ip=%s, namespace=%s, status=%s, ip_role=%s",
                    ip_address,
                    namespace,
                    status,
                    ip_role,
                )

                if not namespace:
                    warnings.append(
                        f"Interface {interface['name']}: namespace required for IP "
                        f"{ip_address}, skipping IP creation"
                    )
                    continue

                try:
                    # Resolve namespace to UUID
                    namespace_id = await self.common.resolve_namespace_id(namespace)

                    # Build kwargs for additional IP fields
                    ip_kwargs = {}
                    if ip_role and ip_role != "none":
                        ip_kwargs["role"] = ip_role
                        logger.info("  Adding role '%s' to IP creation", ip_role)

                    # Use common service to ensure IP exists (handles all error cases)
                    logger.info("  Calling ensure_ip_address_exists for %s", ip_address)
                    ip_id = await self.common.ensure_ip_address_exists(
                        ip_address=ip_address,
                        namespace_id=namespace_id,
                        status_name=status,
                        add_prefixes_automatically=add_prefixes_automatically,
                        **ip_kwargs,
                    )

                    map_key = f"{interface['name']}:{ip_address}"
                    ip_address_map[map_key] = ip_id
                    logger.info("  ✓ SUCCESS: IP address %s ready", ip_address)
                    logger.info("    - IP ID: %s", ip_id)
                    logger.info("    - Map key: %s", map_key)

                except Exception as e:
                    logger.error("  ✗ Error ensuring IP %s: %s", ip_address, str(e))
                    warnings.append(
                        f"Interface {interface['name']}: Failed to ensure IP address "
                        f"{ip_address}: {str(e)}"
                    )
                    # If this is a missing prefix error and add_prefixes_automatically is False,
                    # the exception should propagate to stop the device creation
                    if "No suitable parent prefix" in str(e) and not add_prefixes_automatically:
                        raise

        logger.info("\n" + "=" * 80)
        logger.info("==== STEP 1 COMPLETE: IP ADDRESS MAP ====")
        logger.info("Total IPs created/found: %s", len(ip_address_map))
        logger.info("IP address map: %s", ip_address_map)
        logger.info("=" * 80 + "\n")
        return ip_address_map
```

### Code after — planned (`_create_ip_addresses`, ~48 lines)

```python
async def _create_ip_addresses(
    self,
    interfaces: list[dict[str, Any]],
    warnings: list[str],
    add_prefixes_automatically: bool = False,
) -> dict[str, str]:
    logger.info("=" * 80)
    logger.info("==== STEP 1: CREATE IP ADDRESSES ====")
    logger.info("=" * 80)
    ip_address_map: dict[str, str] = {}

    for interface in interfaces:
        logger.info("\n--- Processing interface: %s ---", interface["name"])
        logger.info("Interface data: %s", interface)
        ip_addresses = _normalize_interface_ip_list(interface)
        if not ip_addresses:
            logger.info(
                "No ip_address or ip_addresses field found for interface %s, skipping",
                interface["name"],
            )
            continue

        logger.info("Found %s IP address(es) to process", len(ip_addresses))
        for idx, ip_data in enumerate(ip_addresses):
            logger.info("\n  >> Processing IP #%s: %s", idx + 1, ip_data)
            entry = await self._ensure_one_interface_ip(
                interface=interface,
                ip_data=ip_data,
                warnings=warnings,
                add_prefixes_automatically=add_prefixes_automatically,
            )
            if entry is not None:
                key, ip_id = entry
                ip_address_map[key] = ip_id

    logger.info("\n" + "=" * 80)
    logger.info("==== STEP 1 COMPLETE: IP ADDRESS MAP ====")
    logger.info("Total IPs created/found: %s", len(ip_address_map))
    logger.info("IP address map: %s", ip_address_map)
    logger.info("=" * 80 + "\n")
    return ip_address_map
```

---

## Step 37: `_update_device_properties` — 124 → ~42 lines

**File:** `backend/services/nautobot/devices/update.py`
**What:** Lift primary_ip4 resolve (create vs update) + post-PATCH verification.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_default_primary_ip_interface_config`
- `_resolve_primary_ip4_for_patch`
- `_verify_primary_ip4_applied`

### Code before — `backend/services/nautobot/devices/update.py` (`_update_device_properties`, 124 lines)

```python
    async def _update_device_properties(
        self,
        device_id: str,
        validated_data: dict[str, Any],
        interface_config: dict[str, str] | None = None,
        ip_namespace: str | None = None,
        device_name: str | None = None,
        current_primary_ip4: str | None = None,
    ) -> list[str]:
        """
        Update device properties via PATCH request.

        Special handling for primary_ip4:
        - If createOnIpChange=true: Creates new interface with new IP
        - If createOnIpChange=false: Updates existing interface's IP address

        Args:
            device_id: Device UUID
            validated_data: Validated update data with UUIDs
            interface_config: Optional interface config for primary_ip4
            ip_namespace: Optional IP namespace for primary_ip4
            device_name: Device name (required for updating existing interface)
            current_primary_ip4: Current primary IP address (for finding interface to update)

        Returns:
            List of updated field names
        """
        logger.info("Updating device %s via REST API", device_id)
        logger.debug("Update data: %s", validated_data)

        # Make a copy so we don't modify the original
        update_payload = validated_data.copy()
        updated_fields = list(update_payload.keys())

        # Special handling for primary_ip4
        if "primary_ip4" in update_payload:
            primary_ip4 = update_payload["primary_ip4"]
            logger.info("Processing primary_ip4 update: %s", primary_ip4)

            # Use interface config if provided, otherwise use defaults
            if not interface_config:
                interface_config = {
                    "name": "Loopback",
                    "type": "virtual",
                    "status": "active",
                    "mgmt_interface_create_on_ip_change": False,
                }

            # Use namespace if provided, otherwise default to "Global"
            namespace = ip_namespace or "Global"

            # Check if we should create a new interface or update existing
            create_new = interface_config.get("mgmt_interface_create_on_ip_change", False)
            logger.info("Create new interface on IP change: %s", create_new)

            # Get add_prefixes_automatically flag (default to False for backward compatibility)
            add_prefixes_automatically = interface_config.get("add_prefixes_automatically", False)
            logger.info("Add prefixes automatically: %s", add_prefixes_automatically)

            # Get use_assigned_ip_if_exists flag (default to False for backward compatibility)
            use_assigned_ip_if_exists = interface_config.get("use_assigned_ip_if_exists", False)
            logger.info("Use assigned IP if exists: %s", use_assigned_ip_if_exists)

            if create_new:
                # BEHAVIOR 1: Create new interface with new IP (existing behavior)
                logger.info("Creating new interface with new IP address")
                ip_id = await self.common.ensure_interface_with_ip(
                    device_id=device_id,
                    ip_address=primary_ip4,
                    interface_name=interface_config.get("name", "Loopback"),
                    interface_type=interface_config.get("type", "virtual"),
                    interface_status=interface_config.get("status", "active"),
                    ip_namespace=namespace,
                    add_prefixes_automatically=add_prefixes_automatically,
                    use_assigned_ip_if_exists=use_assigned_ip_if_exists,
                )
            else:
                # BEHAVIOR 2: Update existing interface's IP address
                logger.info("Updating existing interface's IP address")
                ip_id = await self.common.update_interface_ip(
                    device_id=device_id,
                    device_name=device_name,
                    old_ip=current_primary_ip4,
                    new_ip=primary_ip4,
                    namespace=namespace,
                    add_prefixes_automatically=add_prefixes_automatically,
                    use_assigned_ip_if_exists=use_assigned_ip_if_exists,
                )

            # Update the payload to use the IP UUID instead of the address string
            update_payload["primary_ip4"] = ip_id
            logger.info("Updated primary_ip4 to use IP UUID: %s", ip_id)

        # PATCH the device
        endpoint = f"dcim/devices/{device_id}/"
        result = await self.nautobot.rest_request(
            endpoint=endpoint,
            method="PATCH",
            data=update_payload,
        )

        # Verify primary_ip4 was set if it was in the update
        if "primary_ip4" in update_payload:
            expected_ip_id = update_payload["primary_ip4"]
            actual_ip = result.get("primary_ip4", {})
            actual_ip_id = actual_ip.get("id") if isinstance(actual_ip, dict) else actual_ip

            if actual_ip_id != expected_ip_id:
                error_msg = (
                    f"Device update verification failed: primary_ip4 mismatch "
                    f"(expected {expected_ip_id}, got {actual_ip_id})"
                )
                logger.error(error_msg)
                logger.error("Full update result: %s", result)
                raise ValueError(error_msg)

            logger.info(
                "✓ Successfully verified device %s primary_ip4 is set to %s",
                device_id,
                expected_ip_id,
            )

        logger.info("Successfully updated device %s", device_id)
        return updated_fields
```

### Code after — planned (`_update_device_properties`, ~42 lines)

```python
async def _update_device_properties(
    self,
    device_id: str,
    validated_data: dict[str, Any],
    interface_config: dict[str, str] | None = None,
    ip_namespace: str | None = None,
    device_name: str | None = None,
    current_primary_ip4: str | None = None,
) -> list[str]:
    logger.info("Updating device %s via REST API", device_id)
    logger.debug("Update data: %s", validated_data)

    update_payload = validated_data.copy()
    updated_fields = list(update_payload.keys())

    if "primary_ip4" in update_payload:
        update_payload["primary_ip4"] = await self._resolve_primary_ip4_for_patch(
            device_id=device_id,
            primary_ip4=update_payload["primary_ip4"],
            interface_config=interface_config or _default_primary_ip_interface_config(),
            ip_namespace=ip_namespace or "Global",
            device_name=device_name,
            current_primary_ip4=current_primary_ip4,
        )

    result = await self.nautobot.rest_request(
        endpoint=f"dcim/devices/{device_id}/",
        method="PATCH",
        data=update_payload,
    )
    if "primary_ip4" in update_payload:
        _verify_primary_ip4_applied(
            device_id=device_id,
            expected_ip_id=update_payload["primary_ip4"],
            result=result,
        )

    logger.info("Successfully updated device %s", device_id)
    return updated_fields
```

---

## Step 38: `_migrate` — 123 → ~32 lines

**File:** `backend/scripts/database/sync.py`
**What:** One helper per schema-migration phase (drop/create/add/diff/index/summary).
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_drop_extra_tables`
- `_drop_extra_columns`
- `_create_missing_tables`
- `_add_missing_columns`
- `_apply_column_diffs`
- `_create_missing_indexes`
- `_print_migrate_summary`

### Code before — `backend/scripts/database/sync.py` (`_migrate`, 123 lines)

```python
def _migrate(
    diff: SchemaDiff,
    auto: AutoSchemaMigration,
    force: bool,
    drop: bool = False,
    drop_columns: bool = False,
) -> None:
    tables_created = columns_added = types_changed = indexes_created = skipped = 0
    tables_dropped = columns_dropped = 0

    if drop:
        for table_name in diff.extra_tables:
            try:
                with auto.engine.connect() as conn:
                    conn.execute(text(f"DROP TABLE {table_name}"))
                    conn.commit()
                print(f"  Dropped table: {table_name}")
                tables_dropped += 1
            except Exception as e:
                print(f"  Failed to drop table {table_name}: {e}")

    if drop_columns:
        for table_name, col_name in diff.extra_columns:
            try:
                with auto.engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE {table_name} DROP COLUMN {col_name}"))
                    conn.commit()
                print(f"  Dropped column: {table_name}.{col_name}")
                columns_dropped += 1
            except Exception as e:
                print(f"  Failed to drop column {table_name}.{col_name}: {e}")

    for table_name in diff.missing_tables:
        try:
            table = auto.base.metadata.tables[table_name]
            table.create(bind=auto.engine)
            print(f"  Created table: {table_name}")
            tables_created += 1
        except Exception as e:
            print(f"  Failed to create table {table_name}: {e}")

    # Re-inspect so subsequent steps see newly created tables.
    if diff.missing_tables:
        auto.inspector = sa_inspect(auto.engine)

    for table_name, col_name in diff.missing_columns:
        try:
            table = auto.base.metadata.tables[table_name]
            column = next(c for c in table.columns if c.name == col_name)
            col_def = auto.get_column_definition(column)
            with auto.engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}"))
                conn.commit()
            print(f"  Added column: {table_name}.{col_name}")
            columns_added += 1
        except Exception as e:
            print(f"  Failed to add column {table_name}.{col_name}: {e}")

    for cd in diff.column_diffs:
        if not cd.safe and not force:
            risky_desc = (
                f"{cd.db_type} -> {cd.model_type}" if cd.type_changed else "NULL -> NOT NULL"
            )
            print(
                f"  Skipped risky change: {cd.table}.{cd.column} "
                f"({risky_desc}) — rerun with --force"
            )
            skipped += 1
            continue
        try:
            stmts = []
            if cd.type_changed:
                cast = pg_cast(cd.model_type)
                stmts.append(
                    f"ALTER COLUMN {cd.column} TYPE {cd.model_type} USING {cd.column}::{cast}"
                )
            if cd.nullable_changed:
                if cd.model_nullable:
                    stmts.append(f"ALTER COLUMN {cd.column} DROP NOT NULL")
                else:
                    stmts.append(f"ALTER COLUMN {cd.column} SET NOT NULL")
            for stmt in stmts:
                with auto.engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE {cd.table} {stmt}"))
                    conn.commit()
            change = f"{cd.db_type} -> {cd.model_type}" if cd.type_changed else "nullable changed"
            print(f"  Changed: {cd.table}.{cd.column} ({change})")
            types_changed += 1
        except Exception as e:
            print(f"  Failed to change {cd.table}.{cd.column}: {e}")

    for table_name, idx_name in diff.missing_indexes:
        try:
            table = auto.base.metadata.tables.get(table_name)
            if not table:
                continue
            index = next((i for i in table.indexes if i.name == idx_name), None)
            if index:
                index.create(bind=auto.engine)
                print(f"  Created index: {idx_name}")
                indexes_created += 1
        except Exception as e:
            print(f"  Failed to create index {idx_name}: {e}")

    print()
    print("=" * _WIDTH)
    applied = []
    if tables_dropped:
        applied.append(f"{tables_dropped} table(s) dropped")
    if columns_dropped:
        applied.append(f"{columns_dropped} column(s) dropped")
    if tables_created:
        applied.append(f"{tables_created} table(s) created")
    if columns_added:
        applied.append(f"{columns_added} column(s) added")
    if types_changed:
        applied.append(f"{types_changed} change(s) applied")
    if indexes_created:
        applied.append(f"{indexes_created} index(es) created")
    if skipped:
        applied.append(f"{skipped} risky change(s) skipped")
    print("Summary: " + (", ".join(applied) if applied else "No changes applied."))
    print("=" * _WIDTH)
```

### Code after — planned (`_migrate`, ~32 lines)

```python
def _migrate(
    diff: SchemaDiff,
    auto: AutoSchemaMigration,
    force: bool,
    drop: bool = False,
    drop_columns: bool = False,
) -> None:
    tables_dropped = columns_dropped = 0
    if drop:
        tables_dropped = _drop_extra_tables(diff, auto)
    if drop_columns:
        columns_dropped = _drop_extra_columns(diff, auto)

    tables_created = _create_missing_tables(diff, auto)
    if diff.missing_tables:
        auto.inspector = sa_inspect(auto.engine)

    columns_added = _add_missing_columns(diff, auto)
    types_changed, skipped = _apply_column_diffs(diff, auto, force=force)
    indexes_created = _create_missing_indexes(diff, auto)

    _print_migrate_summary(
        tables_dropped=tables_dropped,
        columns_dropped=columns_dropped,
        tables_created=tables_created,
        columns_added=columns_added,
        types_changed=types_changed,
        indexes_created=indexes_created,
        skipped=skipped,
    )
```

---

## Step 39: `get_directory_files` — 123 → ~48 lines

**File:** `backend/services/git/file_service.py`
**What:** Path containment resolve + per-file last-commit listing helpers.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_resolve_directory_listing_path`
- `_empty_commit_info`
- `_file_last_commit_info`
- `_list_directory_file_entries`

### Code before — `backend/services/git/file_service.py` (`get_directory_files`, 123 lines)

```python
    def get_directory_files(
        self,
        repo_id: int,
        path: str = "",
    ) -> dict[str, Any]:
        """Return flat list of files in a specific directory."""
        try:
            repository = git_repo_manager.get_repository(repo_id)
            if not repository:
                raise HTTPException(status_code=404, detail="Repository not found")

            repo = get_git_repo_by_id(repo_id)
            repo_path = str(git_repo_path(repository))

            if not os.path.exists(repo_path):
                return {
                    "path": path,
                    "files": [],
                    "directory_exists": False,
                }

            target_path = os.path.join(repo_path, path) if path else repo_path
            target_path_resolved = os.path.realpath(target_path)
            repo_path_resolved = os.path.realpath(repo_path)

            if not target_path_resolved.startswith(repo_path_resolved):
                raise HTTPException(
                    status_code=403,
                    detail="Access denied: path is outside repository",
                )

            if not os.path.exists(target_path_resolved):
                return {
                    "path": path,
                    "files": [],
                    "directory_exists": False,
                }

            if not os.path.isdir(target_path_resolved):
                raise HTTPException(
                    status_code=400,
                    detail=f"Path is not a directory: {path}",
                )

            files_data = []

            try:
                items = os.listdir(target_path_resolved)
            except PermissionError:
                raise HTTPException(
                    status_code=403,
                    detail="Permission denied accessing directory",
                ) from None

            for item in items:
                if item.startswith("."):
                    continue

                item_path = os.path.join(target_path_resolved, item)

                if not os.path.isfile(item_path):
                    continue

                file_size = os.path.getsize(item_path)
                file_rel_path = os.path.join(path, item) if path else item

                try:
                    commits = list(repo.iter_commits(paths=file_rel_path, max_count=1))

                    if commits:
                        last_commit = commits[0]
                        commit_info = {
                            "hash": last_commit.hexsha,
                            "short_hash": last_commit.hexsha[:8],
                            "message": last_commit.message.strip(),
                            "author": {
                                "name": last_commit.author.name,
                                "email": last_commit.author.email,
                            },
                            "date": last_commit.committed_datetime.isoformat(),
                            "timestamp": int(last_commit.committed_datetime.timestamp()),
                        }
                    else:
                        commit_info = {
                            "hash": "",
                            "short_hash": "",
                            "message": "No commit history",
                            "author": {"name": "", "email": ""},
                            "date": "",
                            "timestamp": 0,
                        }
                except Exception as e:
                    logger.warning("Failed to get commit info for %s: %s", file_rel_path, e)
                    commit_info = {
                        "hash": "",
                        "short_hash": "",
                        "message": "Error fetching commit",
                        "author": {"name": "", "email": ""},
                        "date": "",
                        "timestamp": 0,
                    }

                files_data.append(
                    {
                        "name": item,
                        "path": file_rel_path,
                        "size": file_size,
                        "last_commit": commit_info,
                    }
                )

            files_data.sort(key=lambda x: x["name"].lower())

            return {
                "path": path,
                "files": files_data,
                "directory_exists": True,
            }

        except HTTPException:
            raise
        except Exception as e:
            raise_internal_server_error(logger, "Error listing directory files", e)
```

### Code after — planned (`get_directory_files`, ~48 lines)

```python
def get_directory_files(
    self,
    repo_id: int,
    path: str = "",
) -> dict[str, Any]:
    """Return flat list of files in a specific directory."""
    try:
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise HTTPException(status_code=404, detail="Repository not found")

        repo = get_git_repo_by_id(repo_id)
        repo_path = str(git_repo_path(repository))
        if not os.path.exists(repo_path):
            return {"path": path, "files": [], "directory_exists": False}

        target = _resolve_directory_listing_path(repo_path, path)
        if target is None:
            return {"path": path, "files": [], "directory_exists": False}

        try:
            items = os.listdir(target)
        except PermissionError:
            raise HTTPException(
                status_code=403,
                detail="Permission denied accessing directory",
            ) from None

        files_data = _list_directory_file_entries(
            repo=repo, target_path=target, path=path, items=items
        )
        return {"path": path, "files": files_data, "directory_exists": True}

    except HTTPException:
        raise
    except Exception as e:
        raise_internal_server_error(logger, "Error listing directory files", e)
```

---

## Step 40: `execute` — 123 → ~52 lines

**File:** `backend/workflow_steps/get_ise_devices/executor.py`
**What:** Parse config, build ISE/Nautobot services, expand group/prefix via CIDR cache, outcomes.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_parse_get_ise_devices_config`
- `_build_ise_services`
- `_expand_ise_devices`
- `_build_get_ise_devices_outcome`

### Code before — `backend/workflow_steps/get_ise_devices/executor.py` (`execute`, 123 lines)

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
        raise ValueError("get-ise-devices: ise_source_id is not configured")

    query_mode = config.get("query_mode", "name")
    if query_mode not in _QUERY_MODES:
        raise ValueError(f"get-ise-devices: unsupported query_mode '{query_mode}'")

    resolve_to_devices = bool(config.get("resolve_to_devices", False))
    nautobot_source_id = (config.get("nautobot_source_id") or "").strip()
    if resolve_to_devices and not nautobot_source_id:
        raise ValueError(
            "get-ise-devices: nautobot_source_id is required when resolve_to_devices is enabled"
        )

    db = object_session(run)
    if db is None:
        raise RuntimeError("get-ise-devices: WorkflowRun has no active DB session")

    source_config_service = service_factory.build_ise_source_config_service(db)
    try:
        credentials = source_config_service.resolve_credentials(source_id)
    except ISESourceNotFoundError as exc:
        raise ValueError(f"get-ise-devices: ISE source '{source_id}' not found") from exc
    except ISEValidationError as exc:
        raise ValueError(f"get-ise-devices: {exc}") from exc

    device_service = service_factory.build_ise_network_device_service(credentials)

    nautobot_source_service: NautobotSourceService | None = None
    if resolve_to_devices:
        nautobot_source_service = _build_nautobot_source_service(db, nautobot_source_id)

    logger.info(
        "get-ise-devices started run_id=%s node_id=%s query_mode=%s resolve_to_devices=%s",
        context.run_id,
        node_id,
        query_mode,
        resolve_to_devices,
    )

    try:
        raw_devices = await _fetch_devices(device_service, config)
    except (ISEValidationError, ISEAPIError) as exc:
        raise RuntimeError(f"get-ise-devices: ISE request failed: {exc}") from exc

    new_devices: dict[str, DeviceContext] = {}
    cidr_cache: dict[str, list[DeviceInfo]] = {}

    for raw_device in raw_devices:
        device_context = device_context_from_ise(raw_device, source_id=source_id)
        is_group_or_prefix = bool(
            device_context.attribute_bags.get("ise", {}).get("is_group_or_prefix")
        )

        if resolve_to_devices and is_group_or_prefix and nautobot_source_service is not None:
            cidr = _cidr_for_group_or_prefix(raw_device)
            resolved_devices: list[DeviceInfo] = []
            if cidr is not None:
                if cidr not in cidr_cache:
                    cidr_cache[cidr] = await _resolve_devices_via_nautobot(
                        nautobot_source_service, cidr
                    )
                resolved_devices = cidr_cache[cidr]

            if resolved_devices:
                for nautobot_device in resolved_devices:
                    resolved_context = device_context_from_nautobot(
                        nautobot_device, source_id=nautobot_source_id
                    )
                    new_devices[resolved_context.id] = resolved_context
                continue

            logger.warning(
                "get-ise-devices: resolve_to_devices found no Nautobot devices for '%s' "
                "(cidr=%s); keeping the raw ISE entry",
                raw_device.get("name"),
                cidr,
            )

        new_devices[device_context.id] = device_context

    fan_out_metadata = build_fan_out_metadata(config.get("fan_out"), node_id)

    metadata_update: dict = {
        **context.metadata,
        f"{node_id}.source_id": source_id,
        f"{node_id}.total": len(new_devices),
    }
    if fan_out_metadata is not None:
        metadata_update["_fan_out"] = fan_out_metadata

    new_context = context.model_copy(
        update={
            "devices": {**context.devices, **new_devices},
            "metadata": metadata_update,
        }
    )

    logger.info(
        "get-ise-devices finished count=%d run_id=%s",
        len(new_devices),
        context.run_id,
    )

    return [
        StepOutcome(
            name="success",
            context=new_context,
            summary=f"found {len(new_devices)} device(s)",
        )
    ]
```

### Code after — planned (`execute`, ~52 lines)

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
    parsed = _parse_get_ise_devices_config(config)

    db = object_session(run)
    if db is None:
        raise RuntimeError("get-ise-devices: WorkflowRun has no active DB session")

    device_service, nautobot_source_service = _build_ise_services(db, parsed)

    logger.info(
        "get-ise-devices started run_id=%s node_id=%s query_mode=%s resolve_to_devices=%s",
        context.run_id, node_id, parsed.query_mode, parsed.resolve_to_devices,
    )

    try:
        raw_devices = await _fetch_devices(device_service, config)
    except (ISEValidationError, ISEAPIError) as exc:
        raise RuntimeError(f"get-ise-devices: ISE request failed: {exc}") from exc

    new_devices = await _expand_ise_devices(
        raw_devices=raw_devices,
        source_id=parsed.source_id,
        resolve_to_devices=parsed.resolve_to_devices,
        nautobot_source_id=parsed.nautobot_source_id,
        nautobot_source_service=nautobot_source_service,
    )

    logger.info(
        "get-ise-devices finished count=%d run_id=%s",
        len(new_devices),
        context.run_id,
    )
    return _build_get_ise_devices_outcome(
        context=context,
        node_id=node_id,
        config=config,
        source_id=parsed.source_id,
        new_devices=new_devices,
    )
```

---

## Step 41: `_run_steps_until_fan_out_or_done` — 122 → ~70 lines

**File:** `backend/hatchet/workflows/workflow_run.py`
**What:** Lift debug pause gate and fan-out context detection from the topo walk.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_maybe_debug_pause_before_node`
- `_fan_out_context_if_requested`

### Code before — `backend/hatchet/workflows/workflow_run.py` (`_run_steps_until_fan_out_or_done`, 122 lines)

```python
async def _run_steps_until_fan_out_or_done(
    *,
    run_repo: Any,
    runner: Any,
    run: Any,
    wf: Any,
    ctx: DurableContext,
) -> tuple[Any, dict[str, Any] | None, Any]:
    """Walk nodes in topological order, executing one at a time.

    In debug mode (``run.run_mode == "debug"``), durably waits for a
    ``workflow-run.{uuid}.step.{node_id}`` event before executing each node —
    this is the "Next Step" gate. In normal mode this behaves exactly like the
    previous ``StepRunner.execute_all`` in-one-shot walk.

    Returns ``(final_status_or_none, fan_out_context, run)`` where the first
    element is a terminal status string when the walk completes without
    fan-out, or None when a fan-out signal was hit (fan_out_context then holds
    the signal plus captured canvas nodes/edges for phase 2/3/4); ``run`` is
    the (possibly reloaded, e.g. after a debug resume) WorkflowRun to keep
    using in the caller.
    """
    from services.execution.graph import find_join_node_id
    from services.execution.step_runner import FanOutSignal

    canvas_nodes: list[dict[str, Any]] = wf.canvas_nodes or []
    canvas_edges: list[dict[str, Any]] = wf.canvas_edges or []
    ordered_nodes = runner.build_execution_plan(canvas_nodes, canvas_edges)
    step_results = runner.create_pending_step_results(run_id=run.id, ordered_nodes=ordered_nodes)

    step_outcomes: dict[str, dict[str, Any]] = {}
    blocked_nodes: set[str] = set()
    failed = False
    any_reported_failure = False

    for node in ordered_nodes:
        node_id: str = node.get("id", "")
        step_result = step_results[node_id]

        if failed:
            run_repo.update_step_result(step_result, status="skipped")
            continue

        if run.run_mode == "debug":
            node_title = (node.get("data", {}) or {}).get("title", node_id)
            run_repo.update_run_status(
                run,
                status="paused",
                current_node_id=node_id,
                debug_message=(
                    f"Paused before '{node_title}' (node {node_id}). Click Next Step to continue."
                ),
            )
            event_key = debug_step_event_key(run.uuid, node_id)
            logger.info("Debug pause run_id=%s node_id=%s", run.id, node_id)
            # Devices drop idle SSH long before a debug pause can resume — release
            # live sessions now; the next network step reconnects lazily.
            await runner.suspend_device_sessions()
            await ctx.aio_wait_for_event(
                event_key,
                scope=event_key,
                lookback_window=STEP_EVENT_LOOKBACK,
            )

            # Force a refresh — a "Run to completion" click (a separate DB
            # session/request) may have flipped run_mode while we waited.
            # A plain re-select would return this same identity-mapped object
            # without re-reading already-loaded columns from the DB.
            run_repo.db.refresh(run)
            if run.run_mode == "debug":
                run_repo.update_run_status(
                    run,
                    status="running",
                    debug_message=f"Resumed. Executing '{node_title}'.",
                )
            else:
                run_repo.update_run_status(run, status="running")

        raised, indicates_failure = await runner.run_node_in_sequence(
            node=node,
            run=run,
            workflow=wf,
            edges=canvas_edges,
            step_outcomes=step_outcomes,
            step_result=step_result,
            blocked_nodes=blocked_nodes,
        )
        if raised:
            failed = True
            continue
        if indicates_failure:
            any_reported_failure = True

        success_ctx = step_outcomes.get(node_id, {}).get("success")
        if success_ctx and success_ctx.metadata.get("_fan_out", {}).get("enabled"):
            fan_out_config = dict(success_ctx.metadata["_fan_out"])
            join_node_id = find_join_node_id(node_id, canvas_nodes, canvas_edges)
            logger.info(
                "Fan-out requested node_id=%s mode=%s join_node_id=%s run_id=%s",
                node_id,
                fan_out_config.get("mode"),
                join_node_id,
                run.id,
            )
            signal = FanOutSignal(
                inventory_node_id=node_id,
                fan_out_config=fan_out_config,
                inventory_outcome=success_ctx,
                step_outcomes=dict(step_outcomes),
                join_node_id=join_node_id,
            )
            return (
                None,
                {
                    "signal": signal,
                    "canvas_nodes": canvas_nodes,
                    "canvas_edges": canvas_edges,
                },
                run,
            )

    return ("success" if not (failed or any_reported_failure) else "failed"), None, run
```

### Code after — planned (`_run_steps_until_fan_out_or_done`, ~70 lines)

```python
async def _run_steps_until_fan_out_or_done(
    *,
    run_repo: Any,
    runner: Any,
    run: Any,
    wf: Any,
    ctx: DurableContext,
) -> tuple[Any, dict[str, Any] | None, Any]:
    """Walk nodes in topological order, executing one at a time.

    In debug mode (``run.run_mode == "debug"``), durably waits for a
    ``workflow-run.{uuid}.step.{node_id}`` event before executing each node —
    this is the "Next Step" gate. In normal mode this behaves exactly like the
    previous ``StepRunner.execute_all`` in-one-shot walk.

    Returns ``(final_status_or_none, fan_out_context, run)`` where the first
    element is a terminal status string when the walk completes without
    fan-out, or None when a fan-out signal was hit (fan_out_context then holds
    the signal plus captured canvas nodes/edges for phase 2/3/4); ``run`` is
    the (possibly reloaded, e.g. after a debug resume) WorkflowRun to keep
    using in the caller.
    """
    canvas_nodes: list[dict[str, Any]] = wf.canvas_nodes or []
    canvas_edges: list[dict[str, Any]] = wf.canvas_edges or []
    ordered_nodes = runner.build_execution_plan(canvas_nodes, canvas_edges)
    step_results = runner.create_pending_step_results(run_id=run.id, ordered_nodes=ordered_nodes)

    step_outcomes: dict[str, dict[str, Any]] = {}
    blocked_nodes: set[str] = set()
    failed = False
    any_reported_failure = False

    for node in ordered_nodes:
        node_id: str = node.get("id", "")
        step_result = step_results[node_id]

        if failed:
            run_repo.update_step_result(step_result, status="skipped")
            continue

        run = await _maybe_debug_pause_before_node(
            run_repo=run_repo, runner=runner, run=run, node=node, ctx=ctx
        )

        raised, indicates_failure = await runner.run_node_in_sequence(
            node=node,
            run=run,
            workflow=wf,
            edges=canvas_edges,
            step_outcomes=step_outcomes,
            step_result=step_result,
            blocked_nodes=blocked_nodes,
        )
        if raised:
            failed = True
            continue
        if indicates_failure:
            any_reported_failure = True

        fan_out = _fan_out_context_if_requested(
            node_id=node_id,
            step_outcomes=step_outcomes,
            canvas_nodes=canvas_nodes,
            canvas_edges=canvas_edges,
            run_id=run.id,
        )
        if fan_out is not None:
            return None, fan_out, run

    return ("success" if not (failed or any_reported_failure) else "failed"), None, run
```

---

## Step 42: `get_file_history` — 121 → ~55 lines

**File:** `backend/services/git/file_service.py`
**What:** Cache key, commit resolve, selected-commit prepend, change-type mapping.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_file_history_cache_key`
- `_resolve_commits_for_file`
- `_selected_commit_in_chain`
- `_maybe_prepend_selected_commit`
- `_history_entry_from_commit`
- `_change_type_for_file_at_commit`

### Code before — `backend/services/git/file_service.py` (`get_file_history`, 121 lines)

```python
    def get_file_history(
        self,
        repo_id: int,
        file_path: str,
        from_commit: str | None = None,
        cache_service=None,
        cache_enabled: bool = True,
        cache_ttl: int = 600,
    ) -> dict[str, Any]:
        """Return full commit chain for a file back to its creation."""
        try:
            repo = get_git_repo_by_id(repo_id)

            repo_scope = f"repo:{repo_id}"
            cache_key = "{}:filehistory:{}:{}".format(
                repo_scope,
                from_commit or "HEAD",
                file_path,
            )
            if cache_enabled and cache_service:
                cached = cache_service.get(cache_key)
                if cached is not None:
                    return cached

            start_commit = from_commit if from_commit else "HEAD"
            commits = list(repo.iter_commits(start_commit, paths=file_path))

            if not commits:
                try:
                    head_commit = repo.head.commit
                    head_commit.tree[file_path]
                    commits = list(repo.iter_commits("HEAD", paths=file_path))
                    if not commits:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"No commits found for file: {file_path}",
                        )
                except (KeyError, AttributeError):
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"File not found: {file_path}",
                    ) from None

            history_commits = []

            selected_commit_found = False
            if from_commit:
                for commit in commits:
                    if (
                        commit.hexsha == from_commit
                        or commit.hexsha.startswith(from_commit)
                        or from_commit.startswith(commit.hexsha)
                    ):
                        selected_commit_found = True
                        break

            if from_commit and not selected_commit_found:
                try:
                    commit_obj = repo.commit(from_commit)
                    try:
                        commit_obj.tree[file_path]
                        history_commits.append(
                            {
                                "hash": commit_obj.hexsha,
                                "short_hash": commit_obj.hexsha[:8],
                                "message": commit_obj.message.strip(),
                                "author": {
                                    "name": commit_obj.author.name,
                                    "email": commit_obj.author.email,
                                },
                                "date": commit_obj.committed_datetime.isoformat(),
                                "change_type": "N",
                            }
                        )
                    except KeyError:
                        pass
                except Exception:
                    pass

            for i, commit in enumerate(commits):
                change_type = "M"

                if i == len(commits) - 1:
                    change_type = "A"
                else:
                    try:
                        commit.tree[file_path]
                    except KeyError:
                        change_type = "D"

                history_commits.append(
                    {
                        "hash": commit.hexsha,
                        "short_hash": commit.hexsha[:8],
                        "message": commit.message.strip(),
                        "author": {
                            "name": commit.author.name,
                            "email": commit.author.email,
                        },
                        "date": commit.committed_datetime.isoformat(),
                        "change_type": change_type,
                    }
                )

            result = {
                "file_path": file_path,
                "from_commit": start_commit,
                "total_commits": len(history_commits),
                "commits": history_commits,
            }
            if cache_enabled and cache_service:
                cache_service.set(cache_key, result, cache_ttl)
            return result

        except (InvalidGitRepositoryError, GitCommandError) as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Git repository not found or commit not found: {str(e)}",
            ) from e
        except Exception as e:
            raise_internal_server_error(logger, "Git file complete history error", e)
```

### Code after — planned (`get_file_history`, ~55 lines)

```python
def get_file_history(
    self,
    repo_id: int,
    file_path: str,
    from_commit: str | None = None,
    cache_service=None,
    cache_enabled: bool = True,
    cache_ttl: int = 600,
) -> dict[str, Any]:
    """Return full commit chain for a file back to its creation."""
    try:
        repo = get_git_repo_by_id(repo_id)
        cache_key = _file_history_cache_key(repo_id, file_path, from_commit)
        if cache_enabled and cache_service:
            cached = cache_service.get(cache_key)
            if cached is not None:
                return cached

        start_commit = from_commit if from_commit else "HEAD"
        commits = _resolve_commits_for_file(repo, file_path, start_commit)

        history_commits: list[dict[str, Any]] = []
        if from_commit and not _selected_commit_in_chain(commits, from_commit):
            history_commits.extend(
                _maybe_prepend_selected_commit(repo, from_commit, file_path)
            )

        for i, commit in enumerate(commits):
            change_type = _change_type_for_file_at_commit(
                commit, file_path, is_oldest=(i == len(commits) - 1)
            )
            history_commits.append(_history_entry_from_commit(commit, change_type))

        result = {
            "file_path": file_path,
            "from_commit": start_commit,
            "total_commits": len(history_commits),
            "commits": history_commits,
        }
        if cache_enabled and cache_service:
            cache_service.set(cache_key, result, cache_ttl)
        return result

    except (InvalidGitRepositoryError, GitCommandError) as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Git repository not found or commit not found: {str(e)}",
        ) from e
    except Exception as e:
        raise_internal_server_error(logger, "Git file complete history error", e)
```

---

## Step 43: `_dispatch_with_approval` — 120 → ~70 lines

**File:** `backend/hatchet/workflows/workflow_run.py`
**What:** Batch approval gate + wait/resume helpers; keep SessionLocal boundaries around durable wait.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_batch_needs_approval_gate`
- `_wait_and_resume_batch_approval`
- `_device_names_for_groups`
- `_tally_batch_failures`

### Code before — `backend/hatchet/workflows/workflow_run.py` (`_dispatch_with_approval`, 120 lines)

```python
async def _dispatch_with_approval(
    signal: Any,
    *,
    parent_run_id: int,
    ctx: DurableContext,
    run_uuid: str,
    canvas_nodes: list[dict[str, Any]],
    canvas_edges: list[dict[str, Any]],
    plan: _FanOutDispatchPlan,
) -> list[dict[str, Any] | BaseException]:
    from core.database import SessionLocal
    from repositories.run_repository import RunRepository

    approval_cfg = plan.approval_cfg
    batch_size = max(1, int(approval_cfg.get("batch_size", 1)))
    first_batch_auto = bool(approval_cfg.get("first_batch_auto", True))
    batches = [plan.groups[i : i + batch_size] for i in range(0, len(plan.groups), batch_size)]
    total_batches = len(batches)

    all_results: list[dict[str, Any] | BaseException] = []
    auto_approve_remaining = False
    devices_completed = 0
    devices_failed = 0
    group_index_offset = 0

    for batch_index, batch_groups in enumerate(batches):
        gate_needed = not auto_approve_remaining and not (batch_index == 0 and first_batch_auto)

        if gate_needed:
            batch_device_names = [
                plan.all_devices[did].name for group in batch_groups for did in group
            ]
            state = _build_approval_state(
                awaiting=True,
                next_batch_index=batch_index,
                total_batches=total_batches,
                batches_completed=batch_index,
                devices_total=len(plan.device_ids),
                devices_completed=devices_completed,
                devices_failed=devices_failed,
                next_batch_device_names=batch_device_names,
            )
            message = _format_approval_pause_message(
                batches_completed=batch_index,
                total_batches=total_batches,
                devices_completed=devices_completed,
                devices_failed=devices_failed,
                next_batch_index=batch_index,
                next_batch_device_names=batch_device_names,
            )

            with SessionLocal() as db:
                run_repo = RunRepository(db)
                run_result = run_repo.get_run_by_id(parent_run_id)
                if run_result is None:
                    raise ValueError(f"WorkflowRun {parent_run_id} not found (approval gate)")
                run, _ = run_result
                run_repo.update_run_status(
                    run,
                    status="paused",
                    current_node_id=signal.inventory_node_id,
                    debug_message=message,
                    approval_state=state,
                )

            event_key = batch_approval_event_key(run_uuid, batch_index)
            logger.info(
                "Approval pause run_id=%s batch=%d/%d",
                parent_run_id,
                batch_index + 1,
                total_batches,
            )
            await ctx.aio_wait_for_event(
                event_key, scope=event_key, lookback_window=STEP_EVENT_LOOKBACK
            )

            with SessionLocal() as db:
                run_repo = RunRepository(db)
                run_result = run_repo.get_run_by_id(parent_run_id)
                if run_result is None:
                    raise ValueError(f"WorkflowRun {parent_run_id} not found (approval resume)")
                run, _ = run_result
                auto_approve_remaining = bool(
                    (run.approval_state or {}).get("auto_approve_remaining")
                )
                run_repo.update_run_status(
                    run,
                    status="running",
                    approval_state={**(run.approval_state or {}), "awaiting": False},
                )

        batch_results = await _run_groups(
            signal,
            parent_run_id=parent_run_id,
            all_devices=plan.all_devices,
            max_concurrency=plan.max_concurrency,
            group_list=batch_groups,
            index_offset=group_index_offset,
        )
        group_index_offset += len(batch_groups)
        all_results.extend(batch_results)

        batch_device_count, batch_failed_count = _tally_batch_failures(
            batch_groups, batch_results
        )
        devices_completed += batch_device_count
        devices_failed += batch_failed_count

        with SessionLocal() as db:
            _aggregate_and_persist(
                run_repo=RunRepository(db),
                run_id=parent_run_id,
                signal=signal,
                canvas_nodes=canvas_nodes,
                canvas_edges=canvas_edges,
                child_results=all_results,
                final=False,
            )

    return all_results
```

### Code after — planned (`_dispatch_with_approval`, ~70 lines)

```python
async def _dispatch_with_approval(
    signal: Any,
    *,
    parent_run_id: int,
    ctx: DurableContext,
    run_uuid: str,
    canvas_nodes: list[dict[str, Any]],
    canvas_edges: list[dict[str, Any]],
    plan: _FanOutDispatchPlan,
) -> list[dict[str, Any] | BaseException]:
    from core.database import SessionLocal
    from repositories.run_repository import RunRepository

    approval_cfg = plan.approval_cfg
    batch_size = max(1, int(approval_cfg.get("batch_size", 1)))
    first_batch_auto = bool(approval_cfg.get("first_batch_auto", True))
    batches = [plan.groups[i : i + batch_size] for i in range(0, len(plan.groups), batch_size)]
    total_batches = len(batches)

    all_results: list[dict[str, Any] | BaseException] = []
    auto_approve_remaining = False
    devices_completed = 0
    devices_failed = 0
    group_index_offset = 0

    for batch_index, batch_groups in enumerate(batches):
        if _batch_needs_approval_gate(
            batch_index=batch_index,
            first_batch_auto=first_batch_auto,
            auto_approve_remaining=auto_approve_remaining,
        ):
            auto_approve_remaining = await _wait_and_resume_batch_approval(
                signal=signal,
                parent_run_id=parent_run_id,
                ctx=ctx,
                run_uuid=run_uuid,
                batch_index=batch_index,
                total_batches=total_batches,
                devices_completed=devices_completed,
                devices_failed=devices_failed,
                batch_device_names=_device_names_for_groups(plan, batch_groups),
                devices_total=len(plan.device_ids),
                SessionLocal=SessionLocal,
                RunRepository=RunRepository,
            )

        batch_results = await _run_groups(
            signal,
            parent_run_id=parent_run_id,
            all_devices=plan.all_devices,
            max_concurrency=plan.max_concurrency,
            group_list=batch_groups,
            index_offset=group_index_offset,
        )
        group_index_offset += len(batch_groups)
        all_results.extend(batch_results)

        batch_device_count, batch_failed_count = _tally_batch_failures(
            batch_groups, batch_results
        )
        devices_completed += batch_device_count
        devices_failed += batch_failed_count

        with SessionLocal() as db:
            _aggregate_and_persist(
                run_repo=RunRepository(db),
                run_id=parent_run_id,
                signal=signal,
                canvas_nodes=canvas_nodes,
                canvas_edges=canvas_edges,
                child_results=all_results,
                final=False,
            )

    return all_results
```

---

## Step 44: `update_interface_ip` — 119 → ~55 lines

**File:** `backend/services/nautobot/managers/interface_manager.py`
**What:** Dedupe Loopback fallback; shrink oversized docstring; keep multi-IP assign semantics.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_fallback_ensure_loopback_with_ip`

### Code before — `backend/services/nautobot/managers/interface_manager.py` (`update_interface_ip`, 119 lines)

```python
    async def update_interface_ip(
        self,
        device_id: str,
        device_name: str,
        old_ip: str | None,
        new_ip: str,
        namespace: str,
        add_prefixes_automatically: bool = False,
        use_assigned_ip_if_exists: bool = False,
    ) -> str:
        """
        Update an existing interface's IP address (instead of creating a new interface).

        This is a reusable utility that:
        1. Finds the interface that currently has the old IP address
        2. Creates/gets the new IP address in Nautobot
        3. Assigns the new IP to the existing interface

        This method can be used by both DeviceUpdateService and DeviceImportService.

        Args:
            device_id: Device UUID
            device_name: Device name (for GraphQL lookup)
            old_ip: Current IP address (to find the interface to update)
            new_ip: New IP address to assign
            namespace: IP namespace name (will be resolved to UUID)
            add_prefixes_automatically: Automatically create missing prefix (default: False)
            use_assigned_ip_if_exists: Use existing IP if it exists with different netmask
                (default: False)

        Returns:
            UUID of the new IP address

        Note:
            - If interface cannot be found, falls back to creating a new interface
            - Old IP will remain on the interface (Nautobot allows multiple IPs)
        """
        from ..resolvers.device_resolver import DeviceResolver

        logger.info(
            "Updating interface IP from %s to %s on device %s",
            old_ip,
            new_ip,
            device_name,
        )

        # Import device resolver to find interface with IP
        device_resolver = DeviceResolver(self.nautobot)

        # Step 1: Find the interface that currently has the old IP
        if old_ip:
            interface_info = await device_resolver.find_interface_with_ip(
                device_name=device_name, ip_address=old_ip
            )

            if interface_info:
                interface_id, interface_name = interface_info
                logger.info(
                    "Found interface '%s' (ID: %s) with IP %s",
                    interface_name,
                    interface_id,
                    old_ip,
                )
            else:
                logger.warning(
                    "Could not find interface with IP %s, creating new interface",
                    old_ip,
                )
                # Fallback: create new interface
                return await self.ensure_interface_with_ip(
                    device_id=device_id,
                    ip_address=new_ip,
                    interface_name="Loopback",
                    interface_type="virtual",
                    interface_status="active",
                    ip_namespace=namespace,
                    add_prefixes_automatically=add_prefixes_automatically,
                    use_assigned_ip_if_exists=use_assigned_ip_if_exists,
                )
        else:
            logger.warning("No old IP provided, creating new interface with new IP")
            # Fallback: create new interface
            return await self.ensure_interface_with_ip(
                device_id=device_id,
                ip_address=new_ip,
                interface_name="Loopback",
                interface_type="virtual",
                interface_status="active",
                ip_namespace=namespace,
                add_prefixes_automatically=add_prefixes_automatically,
                use_assigned_ip_if_exists=use_assigned_ip_if_exists,
            )

        # Step 2: Resolve namespace name to UUID
        logger.info("Resolving namespace '%s'", namespace)
        namespace_id = await self.network_resolver.resolve_namespace_id(namespace)

        # Step 3: Create or get the new IP address in Nautobot
        # (with automatic prefix creation if enabled)
        logger.info("Ensuring IP address %s exists in namespace %s", new_ip, namespace)
        new_ip_id = await self.ip_manager.ensure_ip_address_exists(
            ip_address=new_ip,
            namespace_id=namespace_id,
            add_prefixes_automatically=add_prefixes_automatically,
            use_assigned_ip_if_exists=use_assigned_ip_if_exists,
        )

        # Step 4: Assign the new IP to the existing interface
        logger.info("Assigning IP %s to interface %s", new_ip, interface_name)
        await self.ip_manager.assign_ip_to_interface(ip_id=new_ip_id, interface_id=interface_id)

        logger.info(
            "✓ Successfully updated interface %s from %s to %s",
            interface_name,
            old_ip,
            new_ip,
        )

        return new_ip_id
```

### Code after — planned (`update_interface_ip`, ~55 lines)

```python
async def update_interface_ip(
    self,
    device_id: str,
    device_name: str,
    old_ip: str | None,
    new_ip: str,
    namespace: str,
    add_prefixes_automatically: bool = False,
    use_assigned_ip_if_exists: bool = False,
) -> str:
    """Update an interface IP: find by old_ip, ensure new IP, assign; else create Loopback."""
    from ..resolvers.device_resolver import DeviceResolver

    logger.info(
        "Updating interface IP from %s to %s on device %s",
        old_ip,
        new_ip,
        device_name,
    )

    interface_info = None
    if old_ip:
        interface_info = await DeviceResolver(self.nautobot).find_interface_with_ip(
            device_name=device_name, ip_address=old_ip
        )
        if not interface_info:
            logger.warning(
                "Could not find interface with IP %s, creating new interface",
                old_ip,
            )
    else:
        logger.warning("No old IP provided, creating new interface with new IP")

    if not interface_info:
        return await self._fallback_ensure_loopback_with_ip(
            device_id=device_id,
            new_ip=new_ip,
            namespace=namespace,
            add_prefixes_automatically=add_prefixes_automatically,
            use_assigned_ip_if_exists=use_assigned_ip_if_exists,
        )

    interface_id, interface_name = interface_info
    logger.info("Found interface '%s' (ID: %s) with IP %s", interface_name, interface_id, old_ip)

    namespace_id = await self.network_resolver.resolve_namespace_id(namespace)
    new_ip_id = await self.ip_manager.ensure_ip_address_exists(
        ip_address=new_ip,
        namespace_id=namespace_id,
        add_prefixes_automatically=add_prefixes_automatically,
        use_assigned_ip_if_exists=use_assigned_ip_if_exists,
    )
    await self.ip_manager.assign_ip_to_interface(ip_id=new_ip_id, interface_id=interface_id)
    logger.info("✓ Successfully updated interface %s from %s to %s", interface_name, old_ip, new_ip)
    return new_ip_id
```

---

## Step 45: `search_files` — 117 → ~52 lines

**File:** `backend/services/git/file_service.py`
**What:** Walk / filter / sort / soft-fail envelope helpers.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_empty_file_search_data`
- `_walk_repository_files`
- `_filter_files_by_query`
- `_sort_files_for_search`
- `_file_search_success`

### Code before — `backend/services/git/file_service.py` (`search_files`, 117 lines)

```python
    def search_files(
        self,
        repo_id: int,
        query: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Scan directory, filter by query, sort by relevance, paginate."""
        try:
            repository = git_repo_manager.get_repository(repo_id)
            if not repository:
                raise HTTPException(status_code=404, detail="Repository not found")

            repo_path = str(git_repo_path(repository))

            if not os.path.exists(repo_path):
                return {
                    "success": True,
                    "data": {
                        "files": [],
                        "total_count": 0,
                        "filtered_count": 0,
                        "query": query,
                        "repository_name": repository["name"],
                    },
                }

            structured_files = []

            for root, _dirs, files in os.walk(repo_path):
                if ".git" in root:
                    continue

                rel_root = os.path.relpath(root, repo_path)
                if rel_root == ".":
                    rel_root = ""

                for file in files:
                    if file.startswith("."):
                        continue

                    full_path = os.path.join(rel_root, file) if rel_root else file
                    file_info = {
                        "name": file,
                        "path": full_path,
                        "directory": rel_root,
                        "size": os.path.getsize(os.path.join(root, file))
                        if os.path.exists(os.path.join(root, file))
                        else 0,
                    }
                    structured_files.append(file_info)

            filtered_files = structured_files
            if query:
                query_lower = query.lower()
                filtered_files = []

                for file_info in structured_files:
                    if (
                        query_lower in file_info["name"].lower()
                        or query_lower in file_info["path"].lower()
                        or query_lower in file_info["directory"].lower()
                    ):
                        filtered_files.append(file_info)
                    elif fnmatch.fnmatch(
                        file_info["name"].lower(), f"*{query_lower}*"
                    ) or fnmatch.fnmatch(file_info["path"].lower(), f"*{query_lower}*"):
                        filtered_files.append(file_info)

            if query:

                def sort_key(item):
                    name_lower = item["name"].lower()
                    item["path"].lower()
                    query_lower = query.lower()

                    if name_lower == query_lower:
                        return (0, item["path"])
                    elif name_lower.startswith(query_lower):
                        return (1, item["path"])
                    elif query_lower in name_lower:
                        return (2, item["path"])
                    else:
                        return (3, item["path"])

                filtered_files.sort(key=sort_key)
            else:
                filtered_files.sort(key=lambda x: x["path"])

            paginated_files = filtered_files[:limit]

            return {
                "success": True,
                "data": {
                    "files": paginated_files,
                    "total_count": len(structured_files),
                    "filtered_count": len(filtered_files),
                    "query": query,
                    "repository_name": repository["name"],
                    "has_more": len(filtered_files) > limit,
                },
            }

        except HTTPException:
            raise
        except Exception:
            error_id = str(uuid.uuid4())
            logger.error(
                "Error searching repository files (error_id=%s)",
                error_id,
                exc_info=True,
                extra={"error_id": error_id},
            )
            return {
                "success": False,
                "message": "File search failed",
                "error_id": error_id,
            }
```

### Code after — planned (`search_files`, ~52 lines)

```python
def search_files(
    self,
    repo_id: int,
    query: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """Scan directory, filter by query, sort by relevance, paginate."""
    try:
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise HTTPException(status_code=404, detail="Repository not found")

        repo_path = str(git_repo_path(repository))
        if not os.path.exists(repo_path):
            return {
                "success": True,
                "data": _empty_file_search_data(query, repository["name"]),
            }

        structured_files = _walk_repository_files(repo_path)
        filtered_files = _filter_files_by_query(structured_files, query)
        _sort_files_for_search(filtered_files, query)

        return {
            "success": True,
            "data": _file_search_success(
                files=filtered_files[:limit],
                total_count=len(structured_files),
                filtered_count=len(filtered_files),
                query=query,
                repository_name=repository["name"],
                has_more=len(filtered_files) > limit,
            ),
        }

    except HTTPException:
        raise
    except Exception:
        error_id = str(uuid.uuid4())
        logger.error(
            "Error searching repository files (error_id=%s)",
            error_id,
            exc_info=True,
            extra={"error_id": error_id},
        )
        return {
            "success": False,
            "message": "File search failed",
            "error_id": error_id,
        }
```

---

## Step 46: `sync_repository` — 117 → ~48 lines

**File:** `backend/services/git/operations.py`
**What:** Clone vs pull branch helpers inside existing auth context manager.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_sync_needs_clone`
- `_clone_repository_at_path`
- `_pull_repository_at_path`
- `_map_clone_error_message`
- `_cleanup_failed_clone_dir`

### Code before — `backend/services/git/operations.py` (`sync_repository`, 117 lines)

```python
    def sync_repository(self, repository: dict[str, Any], force_clone: bool = False) -> SyncResult:
        """Sync a repository (clone if not exists, pull if exists).

        Args:
            repository: Repository metadata dict
            force_clone: If True, remove existing repo and clone fresh

        Returns:
            SyncResult with success status and message

        Raises:
            Exception: If sync operation fails
        """
        repo_path = str(get_repo_path(repository))
        logger.info("Syncing repository '%s' to path: %s", repository["name"], repo_path)

        os.makedirs(os.path.dirname(repo_path), exist_ok=True)

        # Determine action: clone or pull
        repo_dir_exists = os.path.exists(repo_path)
        is_git_repo = os.path.isdir(os.path.join(repo_path, ".git"))
        needs_clone = force_clone or not is_git_repo

        success = False
        message = ""

        # Use authentication service for all auth operations
        with self._auth.setup_auth_environment(repository) as (
            clone_url,
            resolved_username,
            resolved_token,
            ssh_key_path,
        ):
            if needs_clone:
                # Backup non-repo directory if present
                if repo_dir_exists and not is_git_repo:
                    parent_dir = os.path.dirname(repo_path.rstrip(os.sep)) or os.path.dirname(
                        repo_path
                    )
                    base_name = os.path.basename(os.path.normpath(repo_path))
                    backup_path = os.path.join(parent_dir, f"{base_name}_backup_{int(time.time())}")
                    shutil.move(repo_path, backup_path)
                    logger.info("Backed up existing directory to %s", backup_path)

                # Clone repository
                try:
                    if not repository.get("verify_ssl", True):
                        logger.warning(
                            "Git SSL verification disabled - not recommended for production"
                        )
                    with set_ssl_env(repository):
                        logger.info("Cloning branch %s into %s", repository["branch"], repo_path)
                        Repo.clone_from(clone_url, repo_path, branch=repository["branch"])

                    if not os.path.isdir(os.path.join(repo_path, ".git")):
                        raise GitCommandError("clone", 1, b"", b".git not found after clone")

                    success = True
                    message = (
                        f"Repository '{repository['name']}' cloned successfully to {repo_path}"
                    )
                    logger.info(message)
                except GitCommandError as gce:
                    err = str(gce)
                    logger.error("Git clone failed: %s", err)
                    if "authentication" in err.lower():
                        message = "Authentication failed. Please check your Git credentials."
                    elif "not found" in err.lower():
                        message = (
                            f"Repository or branch not found. "
                            f"URL: {repository['url']} Branch: {repository['branch']}"
                        )
                    else:
                        message = f"Git clone failed: {err}"
                except Exception as e:
                    logger.error("Unexpected error during Git clone: %s", e)
                    message = f"Unexpected error: {str(e)}"
                finally:
                    # Cleanup empty directory after failed clone
                    try:
                        if not success and os.path.isdir(repo_path) and not os.listdir(repo_path):
                            shutil.rmtree(repo_path)
                            logger.info(
                                "Removed empty directory after failed clone: %s",
                                repo_path,
                            )
                    except Exception as ce:
                        logger.warning("Cleanup after failed clone skipped: %s", ce)
            else:
                # Pull latest
                try:
                    repo = Repo(repo_path)
                    origin = repo.remotes.origin

                    # Update remote URL with authenticated URL if using token auth
                    if resolved_token and "http" in repository["url"]:
                        try:
                            origin.set_url(clone_url)
                        except Exception as e:
                            logger.debug("Skipping remote URL update: %s", e)

                    with set_ssl_env(repository):
                        origin.pull(repository["branch"])
                        success = True
                        message = f"Repository '{repository['name']}' updated successfully"
                        logger.info(message)
                except Exception as e:
                    logger.error("Error during Git pull: %s", e)
                    message = f"Pull failed: {str(e)}"

        return SyncResult(
            success=success,
            message=message,
            commits_behind=0,  # Could be calculated if needed
            commits_ahead=0,
            repository_path=repo_path if success else None,
        )
```

### Code after — planned (`sync_repository`, ~48 lines)

```python
def sync_repository(self, repository: dict[str, Any], force_clone: bool = False) -> SyncResult:
    """Sync a repository (clone if not exists, pull if exists)."""
    repo_path = str(get_repo_path(repository))
    logger.info("Syncing repository '%s' to path: %s", repository["name"], repo_path)
    os.makedirs(os.path.dirname(repo_path), exist_ok=True)

    repo_dir_exists = os.path.exists(repo_path)
    is_git_repo = os.path.isdir(os.path.join(repo_path, ".git"))
    needs_clone = _sync_needs_clone(force_clone=force_clone, is_git_repo=is_git_repo)

    success = False
    message = ""

    with self._auth.setup_auth_environment(repository) as (
        clone_url,
        resolved_username,
        resolved_token,
        ssh_key_path,
    ):
        del resolved_username, ssh_key_path  # unused; keep unpack shape
        if needs_clone:
            success, message = _clone_repository_at_path(
                repository=repository,
                repo_path=repo_path,
                clone_url=clone_url,
                repo_dir_exists=repo_dir_exists,
                is_git_repo=is_git_repo,
            )
        else:
            success, message = _pull_repository_at_path(
                repository=repository,
                repo_path=repo_path,
                clone_url=clone_url,
                resolved_token=resolved_token,
            )

    return SyncResult(
        success=success,
        message=message,
        commits_behind=0,
        commits_ahead=0,
        repository_path=repo_path if success else None,
    )
```

---

## Step 47: `ensure_prefix_exists` — 117 → ~45 lines

**File:** `backend/services/nautobot/managers/prefix_manager.py`
**What:** Namespace resolve, prefix lookup, create-payload builder; shrink docstring.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_resolve_namespace_ref`
- `_find_prefix_id`
- `_build_prefix_create_payload`

### Code before — `backend/services/nautobot/managers/prefix_manager.py` (`ensure_prefix_exists`, 117 lines)

```python
    async def ensure_prefix_exists(
        self,
        prefix: str,
        namespace: str = "Global",
        status: str = "active",
        prefix_type: str = "network",
        location: str | None = None,
        description: str | None = None,
        **kwargs,
    ) -> str:
        """
        Ensure IP prefix exists in Nautobot.

        If prefix already exists in the namespace, returns its UUID.
        If not, creates it and returns the new UUID.

        Args:
            prefix: IP prefix in CIDR format (e.g., "192.168.1.0/24")
            namespace: Namespace name or UUID (default: "Global")
            status: Status name for the prefix (default: "active")
            prefix_type: Type of prefix - "network" or "container" (default: "network")
            location: Location name or UUID (optional)
            description: Description for the prefix (optional)
            **kwargs: Additional fields for prefix creation
                (role, parent, tenant, vlan, rir, tags, custom_fields)

        Returns:
            Prefix UUID

        Raises:
            Exception: If creation fails and prefix doesn't exist
        """
        logger.info("Ensuring prefix exists: %s in namespace %s", prefix, namespace)

        # Resolve namespace to UUID (or use directly if already UUID)
        if is_valid_uuid(namespace):
            logger.debug("Namespace is already a UUID: %s", namespace)
            namespace_id = namespace
        else:
            namespace_id = await self.network_resolver.resolve_namespace_id(namespace)

        # Check if prefix already exists in this namespace
        prefix_search_endpoint = (
            f"ipam/prefixes/?prefix={prefix}&namespace={namespace_id}&format=json"
        )
        prefix_result = await self.nautobot.rest_request(
            endpoint=prefix_search_endpoint, method="GET"
        )

        if prefix_result and prefix_result.get("count", 0) > 0:
            existing_prefix = prefix_result["results"][0]
            logger.info("Prefix already exists: %s", existing_prefix["id"])
            return existing_prefix["id"]

        # Prefix doesn't exist, create it
        logger.info("Creating new prefix: %s", prefix)

        # Resolve status to UUID
        status_id = await self.metadata_resolver.resolve_status_id(
            status, content_type="ipam.prefix"
        )

        # Build payload - Nautobot REST API expects UUID strings, not nested objects
        prefix_data = {
            "prefix": prefix,
            "namespace": namespace_id,
            "status": status_id,
            "type": prefix_type,
        }

        # Add optional description
        if description:
            prefix_data["description"] = description

        # Resolve location if provided
        if location:
            if is_valid_uuid(location):
                prefix_data["location"] = location
            else:
                location_id = await self.metadata_resolver.resolve_location_id(location)
                if location_id:
                    prefix_data["location"] = location_id
                else:
                    logger.warning(
                        "Location '%s' not found, prefix will be created without location",
                        location,
                    )

        # Add optional fields from kwargs
        optional_uuid_fields = ["role", "parent", "tenant", "vlan", "rir"]
        for field in optional_uuid_fields:
            if field in kwargs and kwargs[field]:
                value = kwargs[field]
                if is_valid_uuid(value):
                    prefix_data[field] = value
                else:
                    logger.warning("Field '%s' should be a UUID, got: %s", field, value)

        # Add tags if provided
        if "tags" in kwargs and kwargs["tags"]:
            prefix_data["tags"] = normalize_tags(kwargs["tags"])

        # Add custom_fields if provided
        if "custom_fields" in kwargs and kwargs["custom_fields"]:
            prefix_data["custom_fields"] = kwargs["custom_fields"]

        # Create the prefix
        result = await self.nautobot.rest_request(
            endpoint="ipam/prefixes/", method="POST", data=prefix_data
        )

        if not result or "id" not in result:
            raise NautobotAPIError(f"Failed to create prefix {prefix}: No ID returned")

        prefix_id = result["id"]
        logger.info("Created new prefix: %s with ID: %s", prefix, prefix_id)
        return prefix_id
```

### Code after — planned (`ensure_prefix_exists`, ~45 lines)

```python
async def ensure_prefix_exists(
    self,
    prefix: str,
    namespace: str = "Global",
    status: str = "active",
    prefix_type: str = "network",
    location: str | None = None,
    description: str | None = None,
    **kwargs,
) -> str:
    """Ensure IP prefix exists; return existing or newly created UUID."""
    logger.info("Ensuring prefix exists: %s in namespace %s", prefix, namespace)

    namespace_id = await _resolve_namespace_ref(self.network_resolver, namespace)
    existing_id = await _find_prefix_id(self.nautobot, prefix, namespace_id)
    if existing_id:
        logger.info("Prefix already exists: %s", existing_id)
        return existing_id

    logger.info("Creating new prefix: %s", prefix)
    status_id = await self.metadata_resolver.resolve_status_id(
        status, content_type="ipam.prefix"
    )
    prefix_data = await _build_prefix_create_payload(
        metadata_resolver=self.metadata_resolver,
        prefix=prefix,
        namespace_id=namespace_id,
        status_id=status_id,
        prefix_type=prefix_type,
        location=location,
        description=description,
        kwargs=kwargs,
    )

    result = await self.nautobot.rest_request(
        endpoint="ipam/prefixes/", method="POST", data=prefix_data
    )
    if not result or "id" not in result:
        raise NautobotAPIError(f"Failed to create prefix {prefix}: No ID returned")

    prefix_id = result["id"]
    logger.info("Created new prefix: %s with ID: %s", prefix, prefix_id)
    return prefix_id
```

---

## Step 48: `_execute_operation` — 116 → ~48 lines

**File:** `backend/services/sources/nautobot/evaluator.py`
**What:** Leaf conditions / nested ops / AND-OR-NOT combine helpers.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_execute_operation_conditions`
- `_execute_nested_operations`
- `_combine_logical_results`

### Code before — `backend/services/sources/nautobot/evaluator.py` (`_execute_operation`, 116 lines)

```python
    async def _execute_operation(
        self, operation: LogicalOperation
    ) -> tuple[set[str], int, dict[str, DeviceInfo]]:
        """
        Execute a single logical operation.

        Args:
            operation: The logical operation to execute

        Returns:
            Tuple of (device_ids_set, operations_count, devices_data)
        """
        logger.info(
            "Executing operation: type=%s, conditions=%s, nested=%s",
            operation.operation_type,
            len(operation.conditions),
            len(operation.nested_operations),
        )

        operations_count = 0
        all_devices_data: dict[str, DeviceInfo] = {}

        # Execute all conditions in this operation
        condition_results: list[set[str]] = []
        not_results: list[set[str]] = []  # Separate list for NOT operations

        for i, condition in enumerate(operation.conditions):
            logger.info(
                "  Executing condition %s: %s %s '%s'",
                i,
                condition.field,
                condition.operator,
                condition.value,
            )
            devices, op_count, devices_data = await self._execute_condition(condition)
            condition_results.append(devices)
            operations_count += op_count
            all_devices_data.update(devices_data)
            logger.info("  Condition %s result: %s devices", i, len(devices))

        # Execute nested operations
        for i, nested_op in enumerate(operation.nested_operations):
            logger.info("  Executing nested operation %s: type=%s", i, nested_op.operation_type)
            nested_result, nested_count, nested_data = await self._execute_operation(nested_op)
            operations_count += nested_count
            all_devices_data.update(nested_data)
            logger.info(
                "  Nested operation %s result: %s devices, type=%s",
                i,
                len(nested_result),
                nested_op.operation_type,
            )

            # Separate NOT operations from regular operations
            if nested_op.operation_type.upper() == "NOT":
                not_results.append(nested_result)
                logger.info("  Added to NOT results for subtraction")
            else:
                condition_results.append(nested_result)
                logger.info("  Added to regular results for combination")

        # Combine results based on operation type
        if operation.operation_type.upper() == "AND":
            result = self._intersect_sets(condition_results)
            logger.info("  AND operation result (before NOT): %s devices", len(result))

            # Subtract all NOT results
            for i, not_set in enumerate(not_results):
                old_count = len(result)
                result = result.difference(not_set)
                logger.info(
                    "  Subtracted NOT operation %s: %s - %s = %s devices",
                    i,
                    old_count,
                    len(not_set),
                    len(result),
                )

            logger.info("  AND operation final result: %s devices", len(result))
        elif operation.operation_type.upper() == "OR":
            result = self._union_sets(condition_results)
            logger.info("  OR operation result (before NOT): %s devices", len(result))

            # Subtract all NOT results
            for i, not_set in enumerate(not_results):
                old_count = len(result)
                result = result.difference(not_set)
                logger.info(
                    "  Subtracted NOT operation %s: %s - %s = %s devices",
                    i,
                    old_count,
                    len(not_set),
                    len(result),
                )

            logger.info("  OR operation final result: %s devices", len(result))
        elif operation.operation_type.upper() == "NOT":
            # For NOT operations, return the devices that match the conditions
            # The actual NOT logic will be applied in the main preview_inventory method
            if condition_results:
                result = self._union_sets(
                    condition_results
                )  # Get all devices that match the NOT conditions
            else:
                result = set()
            logger.info("  NOT operation devices to exclude: %s devices", len(result))
        else:
            logger.warning("Unknown operation type: %s", operation.operation_type)
            result = set()

        logger.info(
            "Operation completed: %s devices, %s total queries",
            len(result),
            operations_count,
        )
        return result, operations_count, all_devices_data
```

### Code after — planned (`_execute_operation`, ~48 lines)

```python
async def _execute_operation(
    self, operation: LogicalOperation
) -> tuple[set[str], int, dict[str, DeviceInfo]]:
    """Execute a single logical operation."""
    logger.info(
        "Executing operation: type=%s, conditions=%s, nested=%s",
        operation.operation_type,
        len(operation.conditions),
        len(operation.nested_operations),
    )

    operations_count = 0
    all_devices_data: dict[str, DeviceInfo] = {}

    condition_results, cond_count, cond_data = await self._execute_operation_conditions(
        operation.conditions
    )
    operations_count += cond_count
    all_devices_data.update(cond_data)

    nested_results, not_results, nested_count, nested_data = (
        await self._execute_nested_operations(operation.nested_operations)
    )
    operations_count += nested_count
    all_devices_data.update(nested_data)
    condition_results.extend(nested_results)

    result = _combine_logical_results(
        operation_type=operation.operation_type,
        condition_results=condition_results,
        not_results=not_results,
        intersect=self._intersect_sets,
        union=self._union_sets,
    )

    logger.info(
        "Operation completed: %s devices, %s total queries",
        len(result),
        operations_count,
    )
    return result, operations_count, all_devices_data
```

---

## Step 49: `execute` — 116 → ~48 lines

**File:** `backend/workflow_steps/list_contains/executor.py`
**What:** Parse config, classify membership buckets, build three StepOutcomes.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_parse_list_contains_config`
- `_classify_device_membership`
- `_enrich_membership_result`
- `_build_list_contains_outcomes`

### Code before — `backend/workflow_steps/list_contains/executor.py` (`execute`, 116 lines)

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
    del run, artifact_service

    if not context.devices:
        return [StepOutcome(name=name, context=context) for name in _OUTCOME_NAMES]

    list_path = str(config.get("list_path") or "").strip()
    if not list_path:
        raise ValueError("list-contains: list_path is required")

    field = str(config.get("field") or "").strip() or None
    value_expr = str(config.get("value") or "").strip()
    if not value_expr:
        raise ValueError("list-contains: value is required")

    case_sensitive = _parse_bool(config, "case_sensitive", default=False)

    logger.info(
        "list-contains started run_id=%s node_id=%s list_path=%s field=%s",
        context.run_id,
        node_id,
        list_path,
        field,
    )

    buckets: dict[str, dict[str, DeviceContext]] = {"match": {}, "mismatch": {}, "failure": {}}

    for device_id, device in context.devices.items():
        resolved_value = resolve_update_field_expression(
            device=device,
            field_key="value",
            raw_value=value_expr,
            run_id=context.run_id,
        )
        if resolved_value is None:
            buckets["failure"][device_id] = _device_failure(
                device,
                node_id=node_id,
                code="value_unresolved",
                message=f"value expression {value_expr!r} resolved to nothing for this device",
            )
            continue

        state, _ = resolve_device_attribute_state(device, list_path)
        if state in (AttributeState.ABSENT, AttributeState.NULL):
            buckets["failure"][device_id] = _device_failure(
                device,
                node_id=node_id,
                code="list_not_populated",
                message=(
                    f"list_path {list_path!r} is not populated on this device — "
                    "add an upstream step that produces it"
                ),
            )
            continue

        raw_list = resolve_device_value(device, list_path, run_id=context.run_id)
        if not isinstance(raw_list, list):
            got = "nothing" if raw_list is None else type(raw_list).__name__
            buckets["failure"][device_id] = _device_failure(
                device,
                node_id=node_id,
                code="not_a_list",
                message=f"list_path {list_path!r} did not resolve to a list (got {got})",
            )
            continue

        matched_item = _find_match(
            raw_list, field=field, target=resolved_value, case_sensitive=case_sensitive
        )
        matched = matched_item is not None

        parsed = dict(device.parsed)
        parsed[f"{node_id}.membership"] = {
            "kind": "membership_result",
            "matched": matched,
            "list_path": list_path,
            "field": field,
            "value": resolved_value,
            "matched_item": matched_item,
        }
        enriched = device.model_copy(
            update={
                "parsed": parsed,
                "capabilities": device.capabilities | {Capability.PARSED},
                "status": DeviceStatus.OK,
            }
        )
        buckets["match" if matched else "mismatch"][device_id] = enriched

    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    metadata = {**context.metadata, f"{node_id}.membership_counts": counts}

    logger.info(
        "list-contains finished run_id=%s counts=%s",
        context.run_id,
        counts,
    )

    return [
        StepOutcome(
            name=name,
            context=context.model_copy(
                update={"devices": dict(buckets[name]), "metadata": metadata}
            ),
        )
        for name in _OUTCOME_NAMES
    ]
```

### Code after — planned (`execute`, ~48 lines)

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
    del run, artifact_service, device_sessions

    if not context.devices:
        return [StepOutcome(name=name, context=context) for name in _OUTCOME_NAMES]

    list_path, field, value_expr, case_sensitive = _parse_list_contains_config(config)

    logger.info(
        "list-contains started run_id=%s node_id=%s list_path=%s field=%s",
        context.run_id,
        node_id,
        list_path,
        field,
    )

    buckets: dict[str, dict[str, DeviceContext]] = {"match": {}, "mismatch": {}, "failure": {}}

    for device_id, device in context.devices.items():
        bucket, enriched = _classify_device_membership(
            device=device,
            device_id=device_id,
            node_id=node_id,
            list_path=list_path,
            field=field,
            value_expr=value_expr,
            case_sensitive=case_sensitive,
            run_id=context.run_id,
        )
        buckets[bucket][device_id] = enriched

    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    logger.info("list-contains finished run_id=%s counts=%s", context.run_id, counts)
    return _build_list_contains_outcomes(
        context=context, node_id=node_id, buckets=buckets, counts=counts
    )
```

---

## Step 50: `execute_subgraph` — 112 → ~55 lines

**File:** `backend/services/execution/step_runner.py`
**What:** Blocked-node check, one-node execute, error fold — must not write WorkflowStepResult rows.
**Why:** Still ≥80 lines after passes 1–3; same decomposition discipline as
  prior TOO_LARGE_FUNCTIONS plans.

**Helpers to extract:**

- `_subgraph_node_blocked`
- `_execute_one_subgraph_node`
- `_record_subgraph_node_error`

### Code before — `backend/services/execution/step_runner.py` (`execute_subgraph`, 112 lines)

```python
    async def execute_subgraph(
        self,
        *,
        run: WorkflowRun,
        workflow: Workflow,
        initial_context: WorkflowContext,
        inventory_node_id: str,
        allowed_node_ids: set[str],
    ) -> tuple[dict[str, dict[str, WorkflowContext]], dict[str, dict[str, str]]]:
        """Run only the downstream subgraph without writing WorkflowStepResult records.

        Used by child workflows during fan-out. The parent aggregates and persists
        the returned step outcomes.

        Args:
            run: The parent WorkflowRun (read-only DB access via object_session).
            workflow: The workflow definition containing nodes and edges.
            initial_context: The WorkflowContext with the device subset for this child.
            inventory_node_id: The node_id of the inventory step that triggered fan-out.
            allowed_node_ids: Set of node IDs this child should execute.

        Returns:
            A tuple of:
            - Mapping of node_id → outcome_name → WorkflowContext for all executed nodes.
            - Mapping of node_id → {"message", "category", "error_id"} for nodes whose
              executor raised (see ``classify_step_exception``); the parent folds this
              into the persisted WorkflowStepResult.error_message/error_category/error_id.
        """
        nodes: list[dict[str, Any]] = workflow.canvas_nodes or []
        edges: list[dict[str, Any]] = workflow.canvas_edges or []
        ordered_nodes = self._topological_sort(nodes, edges)

        step_outcomes: dict[str, dict[str, WorkflowContext]] = {
            inventory_node_id: {"success": initial_context}
        }
        step_errors: dict[str, dict[str, str]] = {}
        blocked_nodes: set[str] = set()

        for node in ordered_nodes:
            node_id: str = node.get("id", "")
            if node_id not in allowed_node_ids:
                continue

            node_data: dict[str, Any] = node.get("data", {})
            step_type: str = node_data.get("kind", "unknown")
            step_config: dict[str, Any] = node_data.get("pluginConfig", {})

            if self._step_requires_devices(step_type) and self._blocked_by_upstream_failure(
                node_id, edges, step_outcomes, blocked_nodes
            ):
                blocked_nodes.add(node_id)
                logger.info(
                    "Subgraph step skipped (blocked by upstream device failure) "
                    "node_id=%s type=%s run_id=%s",
                    node_id,
                    step_type,
                    run.id,
                )
                continue

            logger.info(
                "Subgraph step started node_id=%s type=%s run_id=%s",
                node_id,
                step_type,
                run.id,
            )
            try:
                input_context = self._assemble_input_context(
                    run=run,
                    workflow=workflow,
                    node_id=node_id,
                    edges=edges,
                    step_outcomes=step_outcomes,
                )
                outcomes = await self._execute_step(
                    step_type=step_type,
                    config=step_config,
                    context=input_context,
                    run=run,
                    node_id=node_id,
                )
                self._store_step_outcomes(step_outcomes, node_id, outcomes)
                summaries = "; ".join(f"{o.name}: {o.summary}" for o in outcomes if o.summary)
                logger.info(
                    "Subgraph step finished node_id=%s type=%s%s",
                    node_id,
                    step_type,
                    f" summary={summaries}" if summaries else "",
                )
            except Exception as exc:
                error_id = str(uuid.uuid4())
                category, message = classify_step_exception(exc)
                logger.error(
                    "Subgraph step failed node_id=%s type=%s run_id=%s error_id=%s category=%s",
                    node_id,
                    step_type,
                    run.id,
                    error_id,
                    category,
                    exc_info=True,
                    extra={"error_id": error_id},
                )
                step_errors[node_id] = {
                    "message": message[:4000],
                    "category": category,
                    "error_id": error_id,
                }
                self._store_step_outcomes(
                    step_outcomes, node_id, [StepOutcome(name="failure", context=initial_context)]
                )

        return step_outcomes, step_errors
```

### Code after — planned (`execute_subgraph`, ~55 lines)

```python
async def execute_subgraph(
    self,
    *,
    run: WorkflowRun,
    workflow: Workflow,
    initial_context: WorkflowContext,
    inventory_node_id: str,
    allowed_node_ids: set[str],
) -> tuple[dict[str, dict[str, WorkflowContext]], dict[str, dict[str, str]]]:
    """Run only the downstream subgraph without writing WorkflowStepResult records."""
    nodes: list[dict[str, Any]] = workflow.canvas_nodes or []
    edges: list[dict[str, Any]] = workflow.canvas_edges or []
    ordered_nodes = self._topological_sort(nodes, edges)

    step_outcomes: dict[str, dict[str, WorkflowContext]] = {
        inventory_node_id: {"success": initial_context}
    }
    step_errors: dict[str, dict[str, str]] = {}
    blocked_nodes: set[str] = set()

    for node in ordered_nodes:
        node_id: str = node.get("id", "")
        if node_id not in allowed_node_ids:
            continue

        node_data: dict[str, Any] = node.get("data", {})
        step_type: str = node_data.get("kind", "unknown")
        step_config: dict[str, Any] = node_data.get("pluginConfig", {})

        if self._subgraph_node_blocked(
            node_id=node_id,
            step_type=step_type,
            edges=edges,
            step_outcomes=step_outcomes,
            blocked_nodes=blocked_nodes,
            run_id=run.id,
        ):
            continue

        try:
            await self._execute_one_subgraph_node(
                run=run,
                workflow=workflow,
                node_id=node_id,
                step_type=step_type,
                step_config=step_config,
                edges=edges,
                step_outcomes=step_outcomes,
            )
        except Exception as exc:
            self._record_subgraph_node_error(
                node_id=node_id,
                step_type=step_type,
                run_id=run.id,
                exc=exc,
                step_errors=step_errors,
                step_outcomes=step_outcomes,
                initial_context=initial_context,
            )

    return step_outcomes, step_errors
```

---

