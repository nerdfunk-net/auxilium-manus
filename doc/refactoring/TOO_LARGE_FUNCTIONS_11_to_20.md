# Refactoring Plan — Oversized Functions 11–20

**Date:** 2026-08-03
**Based on:** `doc/TOO_LARGE_FUNCTIONS.md` (post pass-1 remaining ≥80);
  `doc/FABLE-ANALYSIS.md` §5.2; prior plan `doc/refactoring/TOO_LARGE_FUNCTIONS_1_to_10.md`
**Pattern:** same as pass 1 — `_parse_*` / per-device helpers / `_build_outcomes`;
  exemplar `workflow_steps/update_nautobot_device/executor.py`
**Goal:** Bring each of the next 10 longest functions under the 80-line offender
  threshold (style rule remains `<50` lines).

> Status: **Implemented** in this pass. "Code before" was the live tree at plan time;
> actual after-line counts are recorded in the Summary table below (re-verified by AST
> after implementation). Full suite + four regression guards green.

## Target selection

Pass 1 closed the original top 10. A fresh AST rescan of `backend/` (excluding
`tests/` / `migrations/`) yields these as the next 10 ≥80-line offenders —
matching inventory ranks 11–20, with the nested `execute.deploy_on_device` now
appearing as the already-lifted module helper `_deploy_on_device` (174 lines).

## Summary

| Rank | Function | Before | After | File |
|---:|---|---:|---:|---|
| 11 | `update_device_interfaces` | 180 | 52 | `backend/services/nautobot/devices/interface_workflow.py` |
| 12 | `execute` | 176 | 61 | `backend/workflow_steps/get_device_configs/executor.py` |
| 13 | `execute` | 176 | 49 | `backend/workflow_steps/merge_content/executor.py` |
| 14 | `execute` | 176 | 75 | `backend/workflow_steps/store_artifact/executor.py` |
| 15 | `_deploy_on_device` | 174 | 70 | `backend/workflow_steps/deploy_rendered_template/executor.py` |
| 16 | `execute` | 169 | 60 | `backend/workflow_steps/login_successful/executor.py` |
| 17 | `execute` | 168 | 49 | `backend/workflow_steps/filter_output/executor.py` |
| 18 | `execute` | 166 | 36 | `backend/workflow_steps/route_on_content/executor.py` |
| 19 | `execute` | 164 | 63 | `backend/workflow_steps/update_ise_tacacs_key/executor.py` |
| 20 | `execute` | 163 | 47 | `backend/workflow_steps/get_nautobot_attributes/executor.py` |

## Implementation order

| Order | Rank | Risk | Notes |
|---:|---:|---|---|
| 1 | 12 | low | Same SSH fan-out pattern as `run_command` (already done) |
| 2 | 16 | low | Same SSH fan-out pattern; already has `_device_failure` |
| 3 | 20 | low | Nautobot read path; lift nested `enrich_device` |
| 4 | 17 | low | Pure filter; lift nested `filter_device` |
| 5 | 18 | low | Control-flow routing; lift nested `process_device` |
| 6 | 13 | low | Lift nested `merge_device` + merge-mode helpers |
| 7 | 15 | medium | Artifact-store side effects inside deploy path |
| 8 | 14 | medium | Git prepare/finalize side effects |
| 9 | 19 | medium | ISE write + abort-vs-continue semantics (mirror `add_to_ise`) |
| 10 | 11 | medium | Nautobot mutation orchestration; preserve primary-IP rules |

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

## Step 11: `update_device_interfaces` — 180 → ~44 lines

**File:** `backend/services/nautobot/devices/interface_workflow.py`
**What:** Extract per-interface processing + mutable state holder; thin orchestration.
**Why:** Still ≥80 lines after pass 1; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md`.

**Helpers to extract:**

- `_InterfaceUpdateState`
- `_process_one_interface`
- `_assign_ips_for_interface`
- `_track_primary_ipv4`
- `InterfaceUpdateState.to_result`

### Code before — `backend/services/nautobot/devices/interface_workflow.py` (`update_device_interfaces`, 180 lines)

```python
    async def update_device_interfaces(
        self,
        device_id: str,
        interfaces: list[dict[str, Any]],
        add_prefixes_automatically: bool = False,
        sync_interfaces: bool = False,
    ) -> InterfaceUpdateResult:
        """
        Create or update multiple interfaces for a device.

        This method handles:
        1. Creating IP addresses in IPAM
        2. Creating interfaces on the device
        3. Assigning IP addresses to interfaces
        4. Setting primary IPv4 if specified

        Args:
            device_id: Device UUID
            interfaces: List of interface dicts (can be InterfaceSpec or plain dicts)
            add_prefixes_automatically: Auto-create missing prefix if IP creation fails
                (default: False)

        Returns:
            InterfaceUpdateResult with operation statistics and warnings
        """
        logger.info(
            "Creating/updating %s interface(s) for device %s",
            len(interfaces),
            device_id,
        )

        created_interfaces: list[str] = []
        updated_interfaces: list[str] = []
        failed_interfaces: list[str] = []
        ip_address_map = {}
        primary_ipv4_id = None
        warnings = []
        cleaned_interfaces: set[str] = set()
        interfaces_deleted = 0

        desired_names = {
            (iface.get("name") or "").strip()
            for iface in interfaces
            if (iface.get("name") or "").strip()
        }

        if sync_interfaces:
            interfaces_deleted = await self._delete_orphan_device_interfaces(
                device_id=device_id,
                desired_names=desired_names,
                warnings=warnings,
            )

        # Step 1: Create IP addresses first
        ip_address_map = await self._create_ip_addresses(
            interfaces=interfaces,
            warnings=warnings,
            add_prefixes_automatically=add_prefixes_automatically,
        )

        # Step 2: Create or update interfaces
        logger.info("\n" + "=" * 80)
        logger.info("==== STEP 2: CREATE OR UPDATE INTERFACES ====")
        logger.info("=" * 80)
        for interface in interfaces:
            try:
                logger.info("\n--- Processing interface: %s ---", interface["name"])
                interface_id, was_updated = await self._create_or_update_interface(
                    device_id=device_id,
                    interface=interface,
                    warnings=warnings,
                )
                logger.info("Interface ID returned: %s", interface_id)

                if interface_id:
                    iface_name = interface["name"]
                    if was_updated:
                        if iface_name not in updated_interfaces:
                            updated_interfaces.append(iface_name)
                    elif iface_name not in created_interfaces:
                        created_interfaces.append(iface_name)

                    # Clean existing IP assignments (once per interface)
                    if interface_id not in cleaned_interfaces:
                        logger.info("Cleaning existing IPs from interface %s", interface["name"])
                        await self._clean_interface_ips(
                            interface_id=interface_id,
                            interface_name=interface["name"],
                            warnings=warnings,
                        )
                        cleaned_interfaces.add(interface_id)
                    else:
                        logger.info("Interface %s already cleaned", interface["name"])

                    # Assign IP addresses - handle both array and single formats
                    logger.info(
                        "\n==== STEP 3: ASSIGN IP(S) TO INTERFACE %s ====",
                        interface["name"],
                    )
                    logger.info("Interface ID: %s", interface_id)

                    # Get IP addresses in array format
                    ip_addresses = interface.get("ip_addresses", [])
                    if not ip_addresses and interface.get("ip_address"):
                        # Backwards compatibility: single ip_address
                        ip_addresses = [
                            {
                                "address": interface["ip_address"],
                                "is_primary": interface.get("is_primary_ipv4", False),
                            }
                        ]

                    logger.info("Found %s IP(s) to assign", len(ip_addresses))

                    # Assign each IP address
                    for idx, ip_data in enumerate(ip_addresses):
                        ip_address = ip_data.get("address")
                        if not ip_address:
                            continue

                        logger.info("\n  >> Assigning IP #%s: %s", idx + 1, ip_address)

                        # Create a temporary interface dict for the assignment call
                        temp_interface = interface.copy()
                        temp_interface["ip_address"] = ip_address

                        ip_assigned = await self._assign_ip_to_interface(
                            interface=temp_interface,
                            interface_id=interface_id,
                            ip_address_map=ip_address_map,
                            warnings=warnings,
                        )
                        logger.info("  IP assignment result: %s", ip_assigned)

                        # Track if this should be primary IPv4
                        if ip_assigned:
                            is_ipv4 = ip_address and ":" not in ip_address
                            if is_ipv4:
                                # Check if this IP is marked as primary
                                if ip_data.get("is_primary"):
                                    primary_ipv4_id = ip_assigned
                                    logger.info(
                                        "  ✓ Interface %s IP %s marked as primary IPv4 (explicit)",
                                        interface["name"],
                                        ip_address,
                                    )
                                elif primary_ipv4_id is None:
                                    primary_ipv4_id = ip_assigned
                                    logger.info(
                                        "  ✓ Interface %s IP %s set as primary IPv4"
                                        " (first IPv4 found)",
                                        interface["name"],
                                        ip_address,
                                    )

            except Exception as e:
                error_msg = str(e)
                failed_interfaces.append(interface["name"])
                warnings.append(
                    f"Interface {interface['name']}: Failed to process interface: {error_msg}"
                )
                logger.error("Error processing interface %s: %s", interface["name"], error_msg)

        # Step 3: Set primary IPv4 if found
        if primary_ipv4_id:
            await self._set_primary_ipv4(
                device_id=device_id,
                primary_ipv4_id=primary_ipv4_id,
                warnings=warnings,
            )

        return InterfaceUpdateResult(
            interfaces_created=len(created_interfaces),
            interfaces_updated=len(updated_interfaces),
            interfaces_failed=len(failed_interfaces),
            interfaces_deleted=interfaces_deleted,
            ip_addresses_created=len(ip_address_map),
            primary_ip4_id=primary_ipv4_id,
            warnings=warnings,
        )
```

### Code after — `backend/services/nautobot/devices/interface_workflow.py` (`update_device_interfaces`, ~44 lines)

```python
async def update_device_interfaces(
    self,
    device_id: str,
    interfaces: list[dict[str, Any]],
    add_prefixes_automatically: bool = False,
    sync_interfaces: bool = False,
) -> InterfaceUpdateResult:
    """Create or update interfaces: IPs → interfaces → assign → optional primary."""
    logger.info(
        "Creating/updating %s interface(s) for device %s",
        len(interfaces),
        device_id,
    )
    state = _InterfaceUpdateState()
    desired_names = {
        (iface.get("name") or "").strip()
        for iface in interfaces
        if (iface.get("name") or "").strip()
    }
    if sync_interfaces:
        state.interfaces_deleted = await self._delete_orphan_device_interfaces(
            device_id=device_id,
            desired_names=desired_names,
            warnings=state.warnings,
        )
    state.ip_address_map = await self._create_ip_addresses(
        interfaces=interfaces,
        warnings=state.warnings,
        add_prefixes_automatically=add_prefixes_automatically,
    )
    logger.info("==== STEP 2: CREATE OR UPDATE INTERFACES ====")
    for interface in interfaces:
        await self._process_one_interface(
            device_id=device_id,
            interface=interface,
            state=state,
        )
    if state.primary_ipv4_id:
        await self._set_primary_ipv4(
            device_id=device_id,
            primary_ipv4_id=state.primary_ipv4_id,
            warnings=state.warnings,
        )
    return state.to_result()
```

### Code after — key helpers for step 11

```python
@dataclass
class _InterfaceUpdateState:
    created_interfaces: list[str] = field(default_factory=list)
    updated_interfaces: list[str] = field(default_factory=list)
    failed_interfaces: list[str] = field(default_factory=list)
    ip_address_map: dict[str, Any] = field(default_factory=dict)
    primary_ipv4_id: str | None = None
    warnings: list[str] = field(default_factory=list)
    cleaned_interfaces: set[str] = field(default_factory=set)
    interfaces_deleted: int = 0

    def to_result(self) -> InterfaceUpdateResult:
        return InterfaceUpdateResult(
            interfaces_created=len(self.created_interfaces),
            interfaces_updated=len(self.updated_interfaces),
            interfaces_failed=len(self.failed_interfaces),
            interfaces_deleted=self.interfaces_deleted,
            ip_addresses_created=len(self.ip_address_map),
            primary_ip4_id=self.primary_ipv4_id,
            warnings=self.warnings,
        )


async def _process_one_interface(
    self,
    *,
    device_id: str,
    interface: dict[str, Any],
    state: _InterfaceUpdateState,
) -> None:
    try:
        logger.info("--- Processing interface: %s ---", interface["name"])
        interface_id, was_updated = await self._create_or_update_interface(
            device_id=device_id,
            interface=interface,
            warnings=state.warnings,
        )
        if not interface_id:
            return
        iface_name = interface["name"]
        if was_updated:
            if iface_name not in state.updated_interfaces:
                state.updated_interfaces.append(iface_name)
        elif iface_name not in state.created_interfaces:
            state.created_interfaces.append(iface_name)

        if interface_id not in state.cleaned_interfaces:
            await self._clean_interface_ips(
                interface_id=interface_id,
                interface_name=iface_name,
                warnings=state.warnings,
            )
            state.cleaned_interfaces.add(interface_id)

        await self._assign_ips_for_interface(
            interface=interface,
            interface_id=interface_id,
            state=state,
        )
    except Exception as e:
        state.failed_interfaces.append(interface["name"])
        state.warnings.append(
            f"Interface {interface['name']}: Failed to process interface: {e}"
        )
        logger.error("Error processing interface %s: %s", interface["name"], e)


async def _assign_ips_for_interface(
    self,
    *,
    interface: dict[str, Any],
    interface_id: str,
    state: _InterfaceUpdateState,
) -> None:
    ip_addresses = interface.get("ip_addresses", [])
    if not ip_addresses and interface.get("ip_address"):
        ip_addresses = [
            {
                "address": interface["ip_address"],
                "is_primary": interface.get("is_primary_ipv4", False),
            }
        ]
    for idx, ip_data in enumerate(ip_addresses):
        ip_address = ip_data.get("address")
        if not ip_address:
            continue
        temp_interface = interface.copy()
        temp_interface["ip_address"] = ip_address
        ip_assigned = await self._assign_ip_to_interface(
            interface=temp_interface,
            interface_id=interface_id,
            ip_address_map=state.ip_address_map,
            warnings=state.warnings,
        )
        if ip_assigned and ":" not in ip_address:
            if ip_data.get("is_primary") or state.primary_ipv4_id is None:
                state.primary_ipv4_id = ip_assigned
```

---

## Step 12: `execute` — 176 → ~61 lines

**File:** `backend/workflow_steps/get_device_configs/executor.py`
**What:** Lift nested fetch helpers; config dataclass + partition/outcomes.
**Why:** Still ≥80 lines after pass 1; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md`.

**Helpers to extract:**

- `_ParsedConfig`
- `_parse_config`
- `_fail_device`
- `_fetch_device`
- `_fetch_device_logged`
- `_partition_device_results`
- `_build_outcomes`

### Code before — `backend/workflow_steps/get_device_configs/executor.py` (`execute`, 176 lines)

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

    credential_reference = str(config.get("credential_reference") or "").strip()
    config_format = str(config.get("config_format") or "both").strip().lower()
    if config_format not in _CONFIG_FORMATS:
        raise ValueError(
            f"get-device-configs: config_format must be one of {sorted(_CONFIG_FORMATS)}"
        )

    db = object_session(run)
    if db is None:
        raise RuntimeError("get-device-configs: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(
        db, credential_reference, acting_user_id=run.triggered_by_id
    )
    include_running, include_startup = _config_targets(config_format)
    netmiko = NetmikoService(pool=device_sessions)

    logger.info(
        "get-device-configs run_id=%s devices=%d credential=%s format=%s",
        run.id,
        len(context.devices),
        credential_reference,
        config_format,
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def fetch_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        host = bare_hostname(device.primary_ip4, device.hostname)
        if not host:
            err = DeviceError(
                node_id=node_id,
                step_id="get-device-configs",
                code="missing_host",
                message=f"Device {device_id} has no hostname or primary IP",
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                }
            )
            return device_id, failed, False

        try:
            result = await netmiko.get_configs(
                host=host,
                network_driver=device.network_driver,
                platform=device.platform,
                username=username,
                password=password,
                include_running=include_running,
                include_startup=include_startup,
                credential_reference=credential_reference,
            )
            if not result.success:
                raise RuntimeError(result.error or "Config retrieval failed")

            updates: dict[str, Any] = {
                "status": DeviceStatus.OK,
                "capabilities": set(device.capabilities),
            }

            if include_running and result.running_config is not None:
                running_ref = await artifact_service.store(
                    content=result.running_config,
                    kind="running_config",
                    device_id=device_id,
                    run_id=context.run_id,
                )
                updates["running_config_ref"] = running_ref
                updates["capabilities"] = updates["capabilities"] | {Capability.RUNNING_CONFIG}

            if include_startup and result.startup_config is not None:
                startup_ref = await artifact_service.store(
                    content=result.startup_config,
                    kind="startup_config",
                    device_id=device_id,
                    run_id=context.run_id,
                )
                updates["startup_config_ref"] = startup_ref
                updates["capabilities"] = updates["capabilities"] | {Capability.STARTUP_CONFIG}

            enriched = device.model_copy(update=updates)
            return device_id, enriched, True
        except Exception as exc:
            err = DeviceError(
                node_id=node_id,
                step_id="get-device-configs",
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

    async def fetch_device_logged(
        index: int, device_id: str, device: DeviceContext
    ) -> tuple[str, DeviceContext, bool]:
        host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
        total = len(context.devices)
        logger.info(
            "get-device-configs device %d/%d id=%s host=%s: connecting run_id=%s",
            index,
            total,
            device_id,
            host,
            run.id,
        )
        result = await fetch_device(device_id, device)
        _, _, ok = result
        logger.info(
            "get-device-configs device %d/%d id=%s host=%s: %s run_id=%s",
            index,
            total,
            device_id,
            host,
            "ok" if ok else "failed",
            run.id,
        )
        return result

    results = await asyncio.gather(
        *[
            fetch_device_logged(index, device_id, device)
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    logger.info(
        "get-device-configs returning %d/%d devices run_id=%s",
        len(success_devices),
        len(context.devices),
        run.id,
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices}),
            )
        )
    return outcomes
```

### Code after — `backend/workflow_steps/get_device_configs/executor.py` (`execute`, ~61 lines)

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

    parsed = _parse_config(config)
    db = object_session(run)
    if db is None:
        raise RuntimeError("get-device-configs: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(
        db, parsed.credential_reference, acting_user_id=run.triggered_by_id
    )
    include_running, include_startup = _config_targets(parsed.config_format)
    netmiko = NetmikoService(pool=device_sessions)
    total = len(context.devices)

    logger.info(
        "get-device-configs run_id=%s devices=%d credential=%s format=%s",
        run.id,
        total,
        parsed.credential_reference,
        parsed.config_format,
    )

    results = await asyncio.gather(
        *[
            _fetch_device_logged(
                index=index,
                device_id=device_id,
                device=device,
                total=total,
                run_id=run.id,
                node_id=node_id,
                context_run_id=context.run_id,
                parsed=parsed,
                username=username,
                password=password,
                include_running=include_running,
                include_startup=include_startup,
                netmiko=netmiko,
                artifact_service=artifact_service,
            )
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )
    success_devices, failed_devices = _partition_device_results(results)
    logger.info(
        "get-device-configs returning %d/%d devices run_id=%s",
        len(success_devices),
        total,
        run.id,
    )
    return _build_outcomes(context, success_devices, failed_devices)
```

---

## Step 13: `execute` — 176 → ~49 lines

**File:** `backend/workflow_steps/merge_content/executor.py`
**What:** Lift merge_device; extract collect/merge helpers + outcomes.
**Why:** Still ≥80 lines after pass 1; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md`.

**Helpers to extract:**

- `_ParsedMergeConfig`
- `_parse_merge_config`
- `_collect_merge_items`
- `_merge_items_to_string`
- `_merge_device`
- `_partition_device_results`
- `_build_merge_outcomes`

### Code before — `backend/workflow_steps/merge_content/executor.py` (`execute`, 176 lines)

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

    content_source = _parse_content_source(config)
    source_node_ids = _parse_source_step_node_ids(config)
    merge_mode = _parse_merge_mode(config)
    section_separator = str(config.get("section_separator") or _DEFAULT_SEPARATOR)
    include_command_header = _parse_include_command_header(config)

    if content_source != "command_output" and not source_node_ids:
        raise ValueError(
            "merge-content: source_step_node_ids is required when "
            f"content_source={content_source!r}"
        )

    logger.info(
        "merge-content run_id=%s devices=%d mode=%s content_source=%s sources=%r",
        run.id,
        len(context.devices),
        merge_mode,
        content_source,
        source_node_ids or "all",
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def merge_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        try:
            items: list[tuple[str, str, str]] = []

            if content_source == "command_output":
                if source_node_ids:
                    node_ids_to_use = [n for n in source_node_ids if n in device.command_results]
                else:
                    node_ids_to_use = list(device.command_results.keys())

                for src_node_id in node_ids_to_use:
                    for result in device.command_results.get(src_node_id, []):
                        if result.output_ref is None:
                            continue
                        text = await artifact_service.resolve(result.output_ref)
                        items.append((result.command, text, result.output_ref.media_type))
            else:
                for src_node_id in source_node_ids:
                    export_items = list_exportable_content(
                        device,
                        content_source=content_source,
                        source_step_node_id=src_node_id,
                    )
                    for export_item in export_items:
                        text = await artifact_service.resolve(export_item.artifact_ref)
                        items.append((src_node_id, text, export_item.media_type))

            if merge_mode == "text_sectioned":
                blocks: list[str] = []
                for command, text, _ in items:
                    if include_command_header:
                        blocks.append(f"=== {command} ===\n{text}")
                    else:
                        blocks.append(text)
                merged_str = section_separator.join(blocks)
                merged_media_type = "text/plain"

            elif merge_mode == "text_plain":
                merged_str = section_separator.join(text for _, text, _ in items)
                merged_media_type = "text/plain"

            else:  # json_merged
                merged_obj: dict[str, Any] = {}
                for command, text, media_type in items:
                    if media_type == "application/json":
                        try:
                            merged_obj[command] = json.loads(text)
                        except json.JSONDecodeError:
                            merged_obj[command] = text
                    else:
                        merged_obj[command] = text
                merged_str = json.dumps(merged_obj, indent=2)
                merged_media_type = "application/json"

            if not merged_str.endswith("\n"):
                merged_str += "\n"

            artifact_ref = await artifact_service.store(
                content=merged_str,
                kind="merged_content",
                device_id=device_id,
                run_id=context.run_id,
                media_type=merged_media_type,
            )

            size_bytes = len(merged_str.encode("utf-8"))
            updated_parsed = dict(device.parsed)
            updated_parsed[f"{node_id}.merged_content"] = _merged_content_entry(
                artifact_ref=artifact_ref,
                node_id=node_id,
                size_bytes=size_bytes,
            )

            enriched = device.model_copy(
                update={
                    "parsed": updated_parsed,
                    "capabilities": device.capabilities | {Capability.PARSED},
                    "status": DeviceStatus.OK,
                }
            )
            return device_id, enriched, True

        except Exception as exc:
            err = DeviceError(
                node_id=node_id,
                step_id="merge-content",
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
        *[merge_device(device_id, device) for device_id, device in context.devices.items()]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    logger.info(
        "merge-content returning %d/%d devices run_id=%s",
        len(success_devices),
        len(context.devices),
        run.id,
    )

    metadata = {
        **context.metadata,
        f"{node_id}.merged_content_mode": merge_mode,
        f"{node_id}.merged_success_count": len(success_devices),
        f"{node_id}.merged_failure_count": len(failed_devices),
    }

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

### Code after — `backend/workflow_steps/merge_content/executor.py` (`execute`, ~49 lines)

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

    parsed = _parse_merge_config(config)
    logger.info(
        "merge-content run_id=%s devices=%d mode=%s content_source=%s sources=%r",
        run.id,
        len(context.devices),
        parsed.merge_mode,
        parsed.content_source,
        parsed.source_node_ids or "all",
    )

    results = await asyncio.gather(
        *[
            _merge_device(
                device_id=device_id,
                device=device,
                parsed=parsed,
                node_id=node_id,
                run_id=context.run_id,
                artifact_service=artifact_service,
            )
            for device_id, device in context.devices.items()
        ]
    )
    success_devices, failed_devices = _partition_device_results(results)
    logger.info(
        "merge-content returning %d/%d devices run_id=%s",
        len(success_devices),
        len(context.devices),
        run.id,
    )
    return _build_merge_outcomes(
        context=context,
        node_id=node_id,
        merge_mode=parsed.merge_mode,
        success_devices=success_devices,
        failed_devices=failed_devices,
    )
```

---

## Step 14: `execute` — 176 → ~70 lines

**File:** `backend/workflow_steps/store_artifact/executor.py`
**What:** Lift store_for_device; extract git prepare/finalize + outcomes.
**Why:** Still ≥80 lines after pass 1; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md`.

**Helpers to extract:**

- `_ParsedStoreConfig`
- `_parse_store_config`
- `_prepare_git_sink_or_fail`
- `_store_for_device`
- `_partition_store_results`
- `_finalize_git_sink`
- `_build_store_outcomes`

### Code before — `backend/workflow_steps/store_artifact/executor.py` (`execute`, 176 lines)

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

    content_source = parse_content_source(config)
    source_step_node_id = str(config.get("source_step_node_id") or "").strip() or None
    parsed_output_key = str(config.get("parsed_output_key") or "").strip() or None
    sink = _build_sink(config)
    git_sink = sink if isinstance(sink, GitArtifactSink) else None
    metadata = dict(context.metadata)

    logger.info(
        "store-artifact run_id=%s devices=%d source=%s destination=%s",
        run.id,
        len(context.devices),
        content_source,
        sink.destination,
    )

    if git_sink is not None:
        try:
            await git_sink.prepare()
        except Exception as exc:
            logger.error("store-artifact git prepare failed run_id=%s: %s", run.id, exc)
            failed_devices = {
                device_id: _device_failure(device=device, node_id=node_id, exc=exc)
                for device_id, device in context.devices.items()
            }
            return [
                StepOutcome(
                    name="success",
                    context=context.model_copy(update={"devices": {}}),
                ),
                StepOutcome(
                    name="failure",
                    context=context.model_copy(update={"devices": failed_devices}),
                ),
            ]

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def store_for_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool, list[dict[str, Any]]]:
        export_items = list_exportable_content(
            device,
            content_source=content_source,
            source_step_node_id=source_step_node_id,
            parsed_output_key=parsed_output_key,
        )
        if not export_items:
            err = DeviceError(
                node_id=node_id,
                step_id="store-artifact",
                code="missing_content",
                message=(
                    f"No {content_source!r} content available for device {device_id}. "
                    "Ensure an upstream step produced the selected data."
                ),
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                }
            )
            return device_id, failed, False, []

        stored_records: list[dict[str, Any]] = []
        try:
            for index, item in enumerate(export_items):
                content = await artifact_service.resolve(item.artifact_ref)
                relative_path = _relative_export_path(
                    device=device,
                    item=item,
                    config=config,
                    index=index,
                    run_id=context.run_id,
                )
                export: StoredExport = await sink.write_text(
                    relative_path=relative_path,
                    content=content,
                    workflow_id=context.workflow_id,
                    run_id=context.run_id,
                )
                stored_records.append(
                    {
                        "device_id": device_id,
                        "content_source": content_source,
                        "kind": item.kind,
                        "path": export.path,
                        "destination": export.destination,
                        "size_bytes": export.size_bytes,
                        "sha256": export.sha256,
                        **item.extra,
                    }
                )

            enriched = device.model_copy(update={"status": DeviceStatus.OK})
            return device_id, enriched, True, stored_records
        except Exception as exc:
            failed = _device_failure(device=device, node_id=node_id, exc=exc)
            return device_id, failed, False, stored_records

    results = await asyncio.gather(
        *[store_for_device(device_id, device) for device_id, device in context.devices.items()]
    )

    all_stored: list[dict[str, Any]] = []
    for device_id, updated_device, ok, stored_records in results:
        all_stored.extend(stored_records)
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    if git_sink is not None and git_sink.has_writes and success_devices:
        try:
            finalize_result = await git_sink.finalize(_render_commit_message(config, context))
            if finalize_result is not None:
                metadata[f"{node_id}.git_export"] = {
                    "git_source_id": git_sink.repository_ref,
                    "committed": finalize_result.committed,
                    "pushed": finalize_result.pushed,
                    "commit_sha": finalize_result.commit_sha,
                    "files_changed": finalize_result.files_changed,
                    "message": finalize_result.message,
                }
        except Exception as exc:
            logger.error("store-artifact git finalize failed run_id=%s: %s", run.id, exc)
            for device_id in list(success_devices):
                device = success_devices.pop(device_id)
                failed_devices[device_id] = _device_failure(
                    device=device,
                    node_id=node_id,
                    exc=exc,
                )

    if all_stored:
        metadata_key = f"{node_id}.stored_artifacts"
        metadata[metadata_key] = all_stored

    logger.info(
        "store-artifact wrote %d file(s) for %d/%d devices run_id=%s",
        len(all_stored),
        len(success_devices),
        len(context.devices),
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

### Code after — `backend/workflow_steps/store_artifact/executor.py` (`execute`, ~70 lines)

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

    parsed = _parse_store_config(config)
    sink = _build_sink(config)
    git_sink = sink if isinstance(sink, GitArtifactSink) else None
    metadata = dict(context.metadata)

    logger.info(
        "store-artifact run_id=%s devices=%d source=%s destination=%s",
        run.id,
        len(context.devices),
        parsed.content_source,
        sink.destination,
    )

    prepare_failure = await _prepare_git_sink_or_fail(
        git_sink=git_sink,
        context=context,
        node_id=node_id,
        run_id=run.id,
    )
    if prepare_failure is not None:
        return prepare_failure

    results = await asyncio.gather(
        *[
            _store_for_device(
                device_id=device_id,
                device=device,
                parsed=parsed,
                sink=sink,
                config=config,
                node_id=node_id,
                context=context,
                artifact_service=artifact_service,
            )
            for device_id, device in context.devices.items()
        ]
    )
    success_devices, failed_devices, all_stored = _partition_store_results(results)
    await _finalize_git_sink(
        git_sink=git_sink,
        config=config,
        context=context,
        node_id=node_id,
        run_id=run.id,
        metadata=metadata,
        success_devices=success_devices,
        failed_devices=failed_devices,
    )
    if all_stored:
        metadata[f"{node_id}.stored_artifacts"] = all_stored
    logger.info(
        "store-artifact wrote %d file(s) for %d/%d devices run_id=%s",
        len(all_stored),
        len(success_devices),
        len(context.devices),
        run.id,
    )
    return _build_store_outcomes(context, success_devices, failed_devices, metadata)
```

---

## Step 15: `_deploy_on_device` — 174 → ~62 lines

**File:** `backend/workflow_steps/deploy_rendered_template/executor.py`
**What:** Split load-commands / run-deploy / store-artifacts / apply-result (pass-1 leftover).
**Why:** Still ≥80 lines after pass 1; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md`.

**Helpers to extract:**

- `_load_deploy_commands`
- `_run_deploy_config`
- `_store_deploy_command_results`
- `_apply_deploy_result`

### Code before — `backend/workflow_steps/deploy_rendered_template/executor.py` (`_deploy_on_device`, 174 lines)

```python
async def _deploy_on_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    run_id: Any,
    context_run_id: str | None,
    parsed: _ParsedDeployConfig,
    username: str,
    password: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool]:
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="missing_host",
            message=f"Device {device_id} has no hostname or primary IP",
        )

    items = list_exportable_content(
        device,
        content_source="rendered_template",
        source_step_node_id=parsed.source_step_node_id,
        parsed_output_key=parsed.parsed_output_key,
    )
    if not items:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="rendered_template_missing",
            message="No rendered template found for the configured source step",
        )

    rendered_text = await artifact_service.resolve(items[0].artifact_ref)
    commands = [line for line in rendered_text.splitlines() if line.strip()]
    if not commands:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="empty_rendered_template",
            message="Rendered template produced no commands",
        )

    device_type = resolve_connection_device_type(
        network_driver=device.network_driver,
        platform=device.platform,
        override=parsed.network_driver_override,
    )

    try:
        result = await netmiko.deploy_config(
            host=host,
            network_driver=device.network_driver,
            platform=device.platform,
            username=username,
            password=password,
            commands=commands,
            mode=parsed.execution_mode,
            write_config=parsed.write_config_after_execution,
            device_type=device_type,
            read_timeout=parsed.read_timeout,
            auto_confirm_prompts=parsed.auto_confirm_prompts,
            credential_reference=parsed.credential_reference,
        )

        if result.confirmed_prompts:
            logger.warning(
                "deploy-rendered-template auto-confirmed %d prompt(s) run_id=%s "
                "node_id=%s device_id=%s commands=%s",
                len(result.confirmed_prompts),
                run_id,
                node_id,
                device_id,
                result.confirmed_prompts,
            )

        step_results: list[CommandResult] = []
        output_ref = await artifact_service.store(
            content=result.config_output,
            kind="command_output",
            device_id=device_id,
            run_id=context_run_id,
        )
        summary = f"{len(commands)} line(s) deployed ({parsed.execution_mode})"
        if result.confirmed_prompts:
            summary += (
                f" · {len(result.confirmed_prompts)} confirmation prompt(s) auto-confirmed"
            )
        step_results.append(
            CommandResult(
                node_id=node_id,
                command="deploy-rendered-template",
                success=result.success,
                output_ref=output_ref,
                summary=summary,
            )
        )
        if result.session_log:
            session_log_ref = await artifact_service.store(
                content=result.session_log,
                kind="netmiko_session_log",
                device_id=device_id,
                run_id=context_run_id,
            )
            step_results.append(
                CommandResult(
                    node_id=node_id,
                    command="netmiko-session-log",
                    success=False,
                    output_ref=session_log_ref,
                    summary=(
                        "Raw Netmiko session log captured up to the failure — inspect "
                        "for confirmation prompts or unexpected CLI output that stalled "
                        "pattern detection"
                    ),
                )
            )
        if result.save_output is not None:
            save_ref = await artifact_service.store(
                content=result.save_output,
                kind="command_output",
                device_id=device_id,
                run_id=context_run_id,
            )
            step_results.append(
                CommandResult(
                    node_id=node_id,
                    command="copy running-config startup-config",
                    success=True,
                    output_ref=save_ref,
                    summary="running-config saved to startup-config",
                )
            )

        updated_command_results = dict(device.command_results)
        updated_command_results[node_id] = step_results

        if not result.success:
            err = DeviceError(
                node_id=node_id,
                step_id=_STEP_ID,
                code="deploy_failed",
                message=result.error or "Deploying rendered template failed",
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                    "command_results": updated_command_results,
                }
            )
            return device_id, failed, False

        enriched = device.model_copy(
            update={
                "status": DeviceStatus.OK,
                "command_results": updated_command_results,
            }
        )
        return device_id, enriched, True
    except Exception as exc:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code=type(exc).__name__.lower(),
            message=str(exc),
        )
```

### Code after — `backend/workflow_steps/deploy_rendered_template/executor.py` (`_deploy_on_device`, ~62 lines)

```python
async def _deploy_on_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    run_id: Any,
    context_run_id: str | None,
    parsed: _ParsedDeployConfig,
    username: str,
    password: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool]:
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="missing_host",
            message=f"Device {device_id} has no hostname or primary IP",
        )

    loaded = await _load_deploy_commands(
        device=device,
        device_id=device_id,
        node_id=node_id,
        parsed=parsed,
        artifact_service=artifact_service,
    )
    if isinstance(loaded, tuple):
        return loaded

    try:
        result = await _run_deploy_config(
            host=host,
            device=device,
            device_id=device_id,
            node_id=node_id,
            run_id=run_id,
            parsed=parsed,
            username=username,
            password=password,
            commands=loaded,
            netmiko=netmiko,
        )
        step_results = await _store_deploy_command_results(
            result=result,
            commands=loaded,
            device_id=device_id,
            node_id=node_id,
            context_run_id=context_run_id,
            parsed=parsed,
            artifact_service=artifact_service,
        )
        return _apply_deploy_result(
            device=device,
            device_id=device_id,
            node_id=node_id,
            result=result,
            step_results=step_results,
        )
    except Exception as exc:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code=type(exc).__name__.lower(),
            message=str(exc),
        )
```

### Code after — key helpers for step 15

```python
async def _load_deploy_commands(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    parsed: _ParsedDeployConfig,
    artifact_service: ArtifactService,
) -> list[str] | tuple[str, DeviceContext, bool]:
    items = list_exportable_content(
        device,
        content_source="rendered_template",
        source_step_node_id=parsed.source_step_node_id,
        parsed_output_key=parsed.parsed_output_key,
    )
    if not items:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="rendered_template_missing",
            message="No rendered template found for the configured source step",
        )
    rendered_text = await artifact_service.resolve(items[0].artifact_ref)
    commands = [line for line in rendered_text.splitlines() if line.strip()]
    if not commands:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="empty_rendered_template",
            message="Rendered template produced no commands",
        )
    return commands


async def _run_deploy_config(
    *,
    host: str,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    run_id: Any,
    parsed: _ParsedDeployConfig,
    username: str,
    password: str,
    commands: list[str],
    netmiko: NetmikoService,
) -> Any:
    device_type = resolve_connection_device_type(
        network_driver=device.network_driver,
        platform=device.platform,
        override=parsed.network_driver_override,
    )
    result = await netmiko.deploy_config(
        host=host,
        network_driver=device.network_driver,
        platform=device.platform,
        username=username,
        password=password,
        commands=commands,
        mode=parsed.execution_mode,
        write_config=parsed.write_config_after_execution,
        device_type=device_type,
        read_timeout=parsed.read_timeout,
        auto_confirm_prompts=parsed.auto_confirm_prompts,
        credential_reference=parsed.credential_reference,
    )
    if result.confirmed_prompts:
        logger.warning(
            "deploy-rendered-template auto-confirmed %d prompt(s) run_id=%s "
            "node_id=%s device_id=%s commands=%s",
            len(result.confirmed_prompts),
            run_id,
            node_id,
            device_id,
            result.confirmed_prompts,
        )
    return result


async def _store_deploy_command_results(
    *,
    result: Any,
    commands: list[str],
    device_id: str,
    node_id: str,
    context_run_id: str | None,
    parsed: _ParsedDeployConfig,
    artifact_service: ArtifactService,
) -> list[CommandResult]:
    step_results: list[CommandResult] = []
    output_ref = await artifact_service.store(
        content=result.config_output,
        kind="command_output",
        device_id=device_id,
        run_id=context_run_id,
    )
    summary = f"{len(commands)} line(s) deployed ({parsed.execution_mode})"
    if result.confirmed_prompts:
        summary += (
            f" · {len(result.confirmed_prompts)} confirmation prompt(s) auto-confirmed"
        )
    step_results.append(
        CommandResult(
            node_id=node_id,
            command="deploy-rendered-template",
            success=result.success,
            output_ref=output_ref,
            summary=summary,
        )
    )
    if result.session_log:
        session_log_ref = await artifact_service.store(
            content=result.session_log,
            kind="netmiko_session_log",
            device_id=device_id,
            run_id=context_run_id,
        )
        step_results.append(
            CommandResult(
                node_id=node_id,
                command="netmiko-session-log",
                success=False,
                output_ref=session_log_ref,
                summary=(
                    "Raw Netmiko session log captured up to the failure — inspect "
                    "for confirmation prompts or unexpected CLI output that stalled "
                    "pattern detection"
                ),
            )
        )
    if result.save_output is not None:
        save_ref = await artifact_service.store(
            content=result.save_output,
            kind="command_output",
            device_id=device_id,
            run_id=context_run_id,
        )
        step_results.append(
            CommandResult(
                node_id=node_id,
                command="copy running-config startup-config",
                success=True,
                output_ref=save_ref,
                summary="running-config saved to startup-config",
            )
        )
    return step_results


def _apply_deploy_result(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    result: Any,
    step_results: list[CommandResult],
) -> tuple[str, DeviceContext, bool]:
    updated_command_results = dict(device.command_results)
    updated_command_results[node_id] = step_results
    if not result.success:
        err = DeviceError(
            node_id=node_id,
            step_id=_STEP_ID,
            code="deploy_failed",
            message=result.error or "Deploying rendered template failed",
        )
        failed = device.model_copy(
            update={
                "status": DeviceStatus.FAILED,
                "errors": [*device.errors, err],
                "command_results": updated_command_results,
            }
        )
        return device_id, failed, False
    enriched = device.model_copy(
        update={
            "status": DeviceStatus.OK,
            "command_results": updated_command_results,
        }
    )
    return device_id, enriched, True
```

---

## Step 16: `execute` — 169 → ~55 lines

**File:** `backend/workflow_steps/login_successful/executor.py`
**What:** Lift try_login helpers; build_login_outcomes.
**Why:** Still ≥80 lines after pass 1; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md`.

**Helpers to extract:**

- `_try_login`
- `_try_login_logged`
- `_build_login_outcomes`

### Code before — `backend/workflow_steps/login_successful/executor.py` (`execute`, 169 lines)

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

    if not context.devices:
        return [StepOutcome(name=name, context=context) for name in _OUTCOME_NAMES]

    credential_reference = str(config.get("credential_reference") or "").strip()
    network_driver_override = str(config.get("network_driver_override") or "").strip() or None

    db = object_session(run)
    if db is None:
        raise RuntimeError("login-successful: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(
        db, credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)

    logger.info(
        "login-successful started run_id=%s node_id=%s devices=%d credential=%s override=%s",
        run.id,
        node_id,
        len(context.devices),
        credential_reference,
        network_driver_override,
    )

    async def try_login(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext]:
        host = bare_hostname(device.primary_ip4, device.hostname)
        if not host:
            failed = _device_failure(
                device,
                node_id=node_id,
                code="missing_host",
                message=f"Device {device_id} has no hostname or primary IP",
            )
            return "failure", _with_login_parsed(
                failed,
                node_id=node_id,
                login_ok=False,
                host="",
                credential_reference=credential_reference,
                error="missing_host",
            )

        device_type = resolve_connection_device_type(
            network_driver=device.network_driver,
            platform=device.platform,
            override=network_driver_override,
        )

        try:
            # Disposable probe login — does not touch any pooled session, so a
            # prior deploy session remains available for rollback on failure.
            alive = await netmiko.test_login(
                host=host,
                network_driver=device.network_driver,
                platform=device.platform,
                username=username,
                password=password,
                credential_reference=credential_reference,
                device_type=device_type,
            )
            if not alive:
                failed = _device_failure(
                    device,
                    node_id=node_id,
                    code="login_failed",
                    message="SSH session opened but is not alive",
                )
                return "failure", _with_login_parsed(
                    failed,
                    node_id=node_id,
                    login_ok=False,
                    host=host,
                    credential_reference=credential_reference,
                    error="session_not_alive",
                )

            enriched = device.model_copy(update={"status": DeviceStatus.OK})
            return "success", _with_login_parsed(
                enriched,
                node_id=node_id,
                login_ok=True,
                host=host,
                credential_reference=credential_reference,
            )
        except Exception as exc:
            failed = _device_failure(
                device,
                node_id=node_id,
                code=type(exc).__name__.lower(),
                message=str(exc),
            )
            return "failure", _with_login_parsed(
                failed,
                node_id=node_id,
                login_ok=False,
                host=host,
                credential_reference=credential_reference,
                error=str(exc),
            )

    async def try_login_logged(
        index: int, device_id: str, device: DeviceContext
    ) -> tuple[str, DeviceContext]:
        host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
        total = len(context.devices)
        logger.info(
            "login-successful device %d/%d id=%s host=%s: connecting run_id=%s",
            index,
            total,
            device_id,
            host,
            run.id,
        )
        outcome_name, updated = await try_login(device_id, device)
        logger.info(
            "login-successful device %d/%d id=%s host=%s: %s run_id=%s",
            index,
            total,
            device_id,
            host,
            outcome_name,
            run.id,
        )
        return outcome_name, updated

    results = await asyncio.gather(
        *[
            try_login_logged(index, device_id, device)
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )

    buckets: dict[str, dict[str, DeviceContext]] = {"success": {}, "failure": {}}
    for device_id, (outcome_name, device) in zip(context.devices.keys(), results, strict=True):
        buckets[outcome_name][device_id] = device

    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    metadata = {**context.metadata, f"{node_id}.login_counts": counts}

    logger.info(
        "login-successful finished success=%d failure=%d run_id=%s",
        counts["success"],
        counts["failure"],
        run.id,
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

### Code after — `backend/workflow_steps/login_successful/executor.py` (`execute`, ~55 lines)

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

    if not context.devices:
        return [StepOutcome(name=name, context=context) for name in _OUTCOME_NAMES]

    credential_reference = str(config.get("credential_reference") or "").strip()
    network_driver_override = str(config.get("network_driver_override") or "").strip() or None

    db = object_session(run)
    if db is None:
        raise RuntimeError("login-successful: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(
        db, credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)
    total = len(context.devices)

    logger.info(
        "login-successful started run_id=%s node_id=%s devices=%d credential=%s override=%s",
        run.id,
        node_id,
        total,
        credential_reference,
        network_driver_override,
    )

    results = await asyncio.gather(
        *[
            _try_login_logged(
                index=index,
                device_id=device_id,
                device=device,
                total=total,
                run_id=run.id,
                node_id=node_id,
                credential_reference=credential_reference,
                network_driver_override=network_driver_override,
                username=username,
                password=password,
                netmiko=netmiko,
            )
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )
    return _build_login_outcomes(context=context, node_id=node_id, results=results)
```

---

## Step 17: `execute` — 168 → ~49 lines

**File:** `backend/workflow_steps/filter_output/executor.py`
**What:** Lift filter_device; config dataclass + outcomes.
**Why:** Still ≥80 lines after pass 1; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md`.

**Helpers to extract:**

- `_ParsedFilterConfig`
- `_parse_filter_config`
- `_select_export_item`
- `_filter_and_store`
- `_filter_device`
- `_partition_device_results`
- `_build_filter_outcomes`

### Code before — `backend/workflow_steps/filter_output/executor.py` (`execute`, 168 lines)

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

    content_source = str(config.get("content_source") or "command_output").strip().lower()
    source_step_node_id = str(config.get("source_step_node_id") or "").strip()
    source_command = str(config.get("source_command") or "").strip()

    if content_source not in _SUPPORTED_SOURCES:
        raise ValueError(
            f"filter-output: content_source {content_source!r} must be one of "
            f"{sorted(_SUPPORTED_SOURCES)}"
        )
    if not source_step_node_id:
        raise ValueError("filter-output: source_step_node_id is required")

    rules = _parse_filter_rules(config)
    if not rules:
        raise ValueError("filter-output: at least one rule in filter_rules is required")

    logger.info(
        "filter-output run_id=%s devices=%d source=%s source_node=%s source_command=%r rules=%d",
        run.id,
        len(context.devices),
        content_source,
        source_step_node_id,
        source_command or "(all)",
        len(rules),
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def filter_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        try:
            export_items = list_exportable_content(
                device,
                content_source=content_source,
                source_step_node_id=source_step_node_id,
            )
            if not export_items:
                raise ValueError(
                    f"No content found for content_source={content_source!r} "
                    f"source_step_node_id={source_step_node_id!r}"
                )

            if source_command and content_source == "command_output":
                matched = [i for i in export_items if i.extra.get("command") == source_command]
                if not matched:
                    available = [i.extra.get("command", "") for i in export_items]
                    raise ValueError(
                        f"Command {source_command!r} not found in step "
                        f"{source_step_node_id!r}. Available: {available}"
                    )
                item = matched[0]
            else:
                item = export_items[0]
            raw_content = await artifact_service.resolve(item.artifact_ref)
            media_type = item.media_type

            if media_type == "application/json":
                try:
                    data = json.loads(raw_content)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Content is not valid JSON: {exc}") from exc
                filtered_data = _filter_json(data, rules)
                filtered_content = json.dumps(filtered_data, indent=2)
                if not filtered_content.endswith("\n"):
                    filtered_content += "\n"
            else:
                filtered_content = _filter_text(raw_content, rules)
                media_type = "text/plain"

            artifact_ref = await artifact_service.store(
                content=filtered_content,
                kind="filtered_output",
                device_id=device_id,
                run_id=context.run_id,
                media_type=media_type,
            )

            size_bytes = len(filtered_content.encode("utf-8"))
            updated_parsed = {
                **device.parsed,
                f"{node_id}.filtered_output": {
                    "artifact_ref": artifact_ref.model_dump(mode="json"),
                    "step_node_id": node_id,
                    "output_key": "filtered_output",
                    "size_bytes": size_bytes,
                    "kind": "filtered_output",
                },
            }

            enriched = device.model_copy(
                update={
                    "parsed": updated_parsed,
                    "capabilities": device.capabilities | {Capability.PARSED},
                    "status": DeviceStatus.OK,
                }
            )
            return device_id, enriched, True

        except Exception as exc:
            logger.warning("filter-output device=%s error=%s", device_id, exc)
            err = DeviceError(
                node_id=node_id,
                step_id="filter-output",
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
        *[filter_device(device_id, device) for device_id, device in context.devices.items()]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    logger.info(
        "filter-output returning %d/%d devices run_id=%s",
        len(success_devices),
        len(context.devices),
        run.id,
    )

    metadata = {
        **context.metadata,
        f"{node_id}.filter_success_count": len(success_devices),
        f"{node_id}.filter_failure_count": len(failed_devices),
    }

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

### Code after — `backend/workflow_steps/filter_output/executor.py` (`execute`, ~49 lines)

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

    parsed = _parse_filter_config(config)
    logger.info(
        "filter-output run_id=%s devices=%d source=%s source_node=%s source_command=%r rules=%d",
        run.id,
        len(context.devices),
        parsed.content_source,
        parsed.source_step_node_id,
        parsed.source_command or "(all)",
        len(parsed.rules),
    )

    results = await asyncio.gather(
        *[
            _filter_device(
                device_id=device_id,
                device=device,
                parsed=parsed,
                node_id=node_id,
                run_id=context.run_id,
                artifact_service=artifact_service,
            )
            for device_id, device in context.devices.items()
        ]
    )
    success_devices, failed_devices = _partition_device_results(results)
    logger.info(
        "filter-output returning %d/%d devices run_id=%s",
        len(success_devices),
        len(context.devices),
        run.id,
    )
    return _build_filter_outcomes(
        context=context,
        node_id=node_id,
        success_devices=success_devices,
        failed_devices=failed_devices,
    )
```

---

## Step 18: `execute` — 166 → ~36 lines

**File:** `backend/workflow_steps/route_on_content/executor.py`
**What:** Lift process_device; config dataclass + outcomes.
**Why:** Still ≥80 lines after pass 1; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md`.

**Helpers to extract:**

- `_ParsedRouteConfig`
- `_parse_route_config`
- `_process_device`
- `_build_route_outcomes`

### Code before — `backend/workflow_steps/route_on_content/executor.py` (`execute`, 166 lines)

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
    del run

    if not context.devices:
        return [StepOutcome(name=name, context=context) for name in _OUTCOME_NAMES]

    content_source = parse_content_source(
        {"content_source": str(config.get("content_source") or _default_config()["content_source"])}
    )
    source_step_node_id = str(config.get("source_step_node_id") or "").strip() or None
    parsed_output_key = str(config.get("parsed_output_key") or "").strip() or None

    match_mode = str(config.get("match_mode") or _default_config()["match_mode"]).strip().lower()
    if match_mode not in _MATCH_MODES:
        raise ValueError(
            f"route-on-content: match_mode {match_mode!r} must be one of {sorted(_MATCH_MODES)}"
        )

    pattern = str(config.get("pattern") or "").strip()
    if not pattern:
        raise ValueError("route-on-content: pattern is required")

    case_sensitive = _parse_bool(config, "case_sensitive", default=False)
    multiline = _parse_bool(config, "multiline", default=False)

    logger.info(
        "route-on-content started run_id=%s node_id=%s content_source=%s match_mode=%s",
        context.run_id,
        node_id,
        content_source,
        match_mode,
    )

    async def process_device(
        device_id: str, device: DeviceContext
    ) -> tuple[str, DeviceContext, str]:
        export_items = list_exportable_content(
            device,
            content_source=content_source,
            source_step_node_id=source_step_node_id,
            parsed_output_key=parsed_output_key,
        )
        if not export_items:
            failed = _device_failure(
                device=device,
                node_id=node_id,
                code="missing_content",
                message=(
                    f"No {content_source!r} content available for device {device_id}. "
                    "Ensure an upstream step produced the selected data."
                ),
            )
            return device_id, failed, "failure"

        item = export_items[0]
        if len(export_items) > 1:
            logger.warning(
                "route-on-content device=%s source=%s has %d export items; using first only",
                device_id,
                content_source,
                len(export_items),
            )

        try:
            content_text = await artifact_service.resolve(item.artifact_ref)
        except Exception as exc:  # noqa: BLE001 - surfaced as a per-device failure below
            failed = _device_failure(
                device=device,
                node_id=node_id,
                code="content_unavailable",
                message=str(exc),
            )
            return device_id, failed, "failure"

        rendered_pattern = render_placeholder_template(
            pattern,
            device,
            value_transform=re.escape if match_mode == "regex" else None,
        )
        if not rendered_pattern:
            failed = _device_failure(
                device=device,
                node_id=node_id,
                code="pattern_unresolved",
                message=(
                    "pattern rendered to an empty string for this device — a "
                    "{path.to.attribute} placeholder may not have resolved"
                ),
            )
            return device_id, failed, "failure"

        try:
            if match_mode == "fixed_text":
                matched, matched_text = _match_fixed_text(
                    content_text, rendered_pattern, case_sensitive=case_sensitive
                )
            else:
                matched, matched_text = _match_regex(
                    content_text,
                    rendered_pattern,
                    case_sensitive=case_sensitive,
                    multiline=multiline,
                )
        except re.error as exc:
            failed = _device_failure(
                device=device,
                node_id=node_id,
                code="invalid_regex",
                message=f"invalid regular expression {rendered_pattern!r}: {exc}",
            )
            return device_id, failed, "failure"

        parsed = dict(device.parsed)
        parsed[f"{node_id}.content_match"] = {
            "kind": "content_match_result",
            "matched": matched,
            "content_source": content_source,
            "match_mode": match_mode,
            "case_sensitive": case_sensitive,
            "multiline": multiline,
            **({"matched_text": matched_text} if matched_text is not None else {}),
        }
        enriched = device.model_copy(
            update={
                "parsed": parsed,
                "capabilities": device.capabilities | {Capability.PARSED},
                "status": DeviceStatus.OK,
            }
        )
        return device_id, enriched, "match" if matched else "mismatch"

    results = await asyncio.gather(
        *[process_device(device_id, device) for device_id, device in context.devices.items()]
    )

    buckets: dict[str, dict[str, DeviceContext]] = {name: {} for name in _OUTCOME_NAMES}
    for device_id, updated_device, bucket_name in results:
        buckets[bucket_name][device_id] = updated_device

    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    metadata = {**context.metadata, f"{node_id}.content_match_counts": counts}

    logger.info(
        "route-on-content finished run_id=%s node_id=%s counts=%s",
        context.run_id,
        node_id,
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

### Code after — `backend/workflow_steps/route_on_content/executor.py` (`execute`, ~36 lines)

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
    del run

    if not context.devices:
        return [StepOutcome(name=name, context=context) for name in _OUTCOME_NAMES]

    parsed = _parse_route_config(config)
    logger.info(
        "route-on-content started run_id=%s node_id=%s content_source=%s match_mode=%s",
        context.run_id,
        node_id,
        parsed.content_source,
        parsed.match_mode,
    )

    results = await asyncio.gather(
        *[
            _process_device(
                device_id=device_id,
                device=device,
                parsed=parsed,
                node_id=node_id,
                artifact_service=artifact_service,
            )
            for device_id, device in context.devices.items()
        ]
    )
    return _build_route_outcomes(context=context, node_id=node_id, results=results)
```

---

## Step 19: `execute` — 164 → ~55 lines

**File:** `backend/workflow_steps/update_ise_tacacs_key/executor.py`
**What:** Mirror add_to_ise: parse/preflight/update_one/outcome.
**Why:** Still ≥80 lines after pass 1; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md`.

**Helpers to extract:**

- `_ParsedConfig`
- `_parse_config`
- `_build_ise_device_service`
- `_preflight_ise`
- `_update_one_device`
- `_build_success_outcome`

### Code before — `backend/workflow_steps/update_ise_tacacs_key/executor.py` (`execute`, 164 lines)

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

    raw_new_key = (config.get("new_key") or "").strip()
    if not raw_new_key:
        raise ValueError(f"{_STEP_ID}: new_key is not configured")

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
    updated_count = 0
    failed_count = 0

    for device_id, device in context.devices.items():
        new_key_value = resolve_update_field_expression(
            device=device,
            field_key="new_key",
            raw_value=raw_new_key,
            run_id=context.run_id,
        )
        if not new_key_value:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="tacacs_key_unresolved",
                message=f"new_key expression did not resolve to a value for '{device.name}'",
            )
            failed_count += 1
            continue

        try:
            ise_device_id = await _resolve_ise_device_id(device, device_service)
        except ISEAPIError as exc:
            logger.warning(
                "%s: lost connection to ISE source '%s' while resolving device '%s': %s",
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

        if not ise_device_id:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="ise_device_not_found",
                message=f"could not locate device '{device.name}' in ISE source '{source_id}'",
            )
            failed_count += 1
            continue

        try:
            current = await device_service.get_device(ise_device_id)
            current_tacacs = current.get("NetworkDevice", {}).get("tacacsSettings") or {}
            merged_tacacs = {**current_tacacs, "sharedSecret": new_key_value}
            await device_service.update_device(ise_device_id, {"tacacsSettings": merged_tacacs})
        except (ISENotFoundError, ISEValidationError) as exc:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="tacacs_key_update_rejected",
                message=f"ISE rejected the TACACS+ key update for '{device.name}': {exc}",
            )
            failed_count += 1
            continue
        except ISEAPIError as exc:
            logger.warning(
                "%s: lost connection to ISE source '%s' while updating device '%s': %s",
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

        updated_devices[device_id] = set_device_attribute(
            device, "tacacs.shared_secret", seal_secret(new_key_value)
        )
        updated_count += 1
        logger.info("%s: updated tacacs key for device=%s", _STEP_ID, device.name)

    metadata = {
        **context.metadata,
        f"{node_id}.total": len(context.devices),
        f"{node_id}.updated_count": updated_count,
        f"{node_id}.failed_count": failed_count,
    }

    logger.info(
        "%s finished node_id=%s updated=%d failed=%d run_id=%s",
        _STEP_ID,
        node_id,
        updated_count,
        failed_count,
        context.run_id,
    )

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": updated_devices, "metadata": metadata}),
            summary=f"updated {updated_count}, failed {failed_count}",
        )
    ]
```

### Code after — `backend/workflow_steps/update_ise_tacacs_key/executor.py` (`execute`, ~55 lines)

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

    parsed = _parse_config(config)
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    device_service = _build_ise_device_service(run, parsed.source_id)
    logger.info(
        "%s started run_id=%s node_id=%s devices=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        len(context.devices),
    )

    preflight = await _preflight_ise(device_service, parsed.source_id, context)
    if preflight is not None:
        return preflight

    updated_devices: dict[str, DeviceContext] = {}
    updated_count = 0
    failed_count = 0
    for device_id, device in context.devices.items():
        result = await _update_one_device(
            device_id=device_id,
            device=device,
            device_service=device_service,
            parsed=parsed,
            node_id=node_id,
            run_id=context.run_id,
        )
        if result.kind == "abort":
            return [result.outcome]
        updated_devices[device_id] = result.device
        if result.ok:
            updated_count += 1
        else:
            failed_count += 1

    return [_build_success_outcome(
        context=context,
        node_id=node_id,
        updated_devices=updated_devices,
        updated_count=updated_count,
        failed_count=failed_count,
    )]
```

---

## Step 20: `execute` — 163 → ~47 lines

**File:** `backend/workflow_steps/get_nautobot_attributes/executor.py`
**What:** Bind credentials; lift enrich_device; partition/outcomes.
**Why:** Still ≥80 lines after pass 1; same decomposition discipline as
  `TOO_LARGE_FUNCTIONS_1_to_10.md`.

**Helpers to extract:**

- `_ParsedConfig`
- `_parse_config`
- `_bind_nautobot`
- `_fail_device`
- `_enrich_device`
- `_partition_device_results`
- `_build_outcomes`

### Code before — `backend/workflow_steps/get_nautobot_attributes/executor.py` (`execute`, 163 lines)

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

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    source_id = config.get("nautobot_source_id", "").strip()
    if not source_id:
        raise ValueError("get-nautobot-attributes: nautobot_source_id is not configured")

    list_of_attributes: list[str] = config.get("list_of_attributes") or []

    db = object_session(run)
    if db is None:
        raise RuntimeError("get-nautobot-attributes: WorkflowRun has no active DB session")

    setting_key = build_source_key("nautobot", source_id)
    setting = SettingsRepository(db).get_by_key(setting_key)
    if setting is None:
        raise ValueError(
            f"get-nautobot-attributes: Nautobot source '{source_id}' not found in settings"
        )

    nautobot_url = (setting.value or {}).get("url", "").strip()
    nautobot_token = (setting.value or {}).get("token", "").strip()
    nautobot_verify_ssl = bool((setting.value or {}).get("verify_ssl", True))
    if not nautobot_url or not nautobot_token:
        raise ValueError(
            f"get-nautobot-attributes: Nautobot source '{source_id}' is missing url or token"
        )

    credentials = service_factory.credentials_from_connection(
        nautobot_url, nautobot_token, verify_ssl=nautobot_verify_ssl
    )
    nautobot_service = service_factory.get_nautobot_app_service()

    variables = build_attribute_variables(list_of_attributes)

    logger.info(
        "get-nautobot-attributes run_id=%s source_id=%s devices=%d attributes=%s",
        run.id,
        source_id,
        len(context.devices),
        list_of_attributes,
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def enrich_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        try:
            nautobot_device_id = await resolve_nautobot_device_id(
                nautobot_service=nautobot_service,
                credentials=credentials,
                device=device,
            )
            if nautobot_device_id is None:
                err = DeviceError(
                    node_id=node_id,
                    step_id="get-nautobot-attributes",
                    code="not_found",
                    message=(
                        f"No Nautobot device found for workflow device {device_id} "
                        f"(name={device.name!r}, ip={device.primary_ip4!r})"
                    ),
                )
                failed = device.model_copy(
                    update={
                        "status": DeviceStatus.FAILED,
                        "errors": [*device.errors, err],
                    }
                )
                return device_id, failed, False

            detail = await _fetch_device(
                nautobot_service, credentials, nautobot_device_id, variables
            )
            if detail is None:
                err = DeviceError(
                    node_id=node_id,
                    step_id="get-nautobot-attributes",
                    code="not_found",
                    message=f"No Nautobot data returned for device {device_id}",
                )
                failed = device.model_copy(
                    update={
                        "status": DeviceStatus.FAILED,
                        "errors": [*device.errors, err],
                    }
                )
                return device_id, failed, False

            platform_raw = detail.get("platform")
            platform = platform_raw if isinstance(platform_raw, dict) else {}
            attribute_bags = dict(device.attribute_bags)
            attribute_bags["nautobot"] = attributes_from_detail(detail)
            enriched = device.model_copy(
                update={
                    "attribute_bags": attribute_bags,
                    "platform": platform.get("name") or device.platform,
                    "network_driver": platform.get("network_driver") or device.network_driver,
                    "capabilities": device.capabilities | {Capability.ATTRIBUTES},
                    "status": DeviceStatus.OK,
                }
            )
            return device_id, enriched, True
        except Exception as exc:
            err = DeviceError(
                node_id=node_id,
                step_id="get-nautobot-attributes",
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
        *[enrich_device(device_id, device) for device_id, device in context.devices.items()]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    logger.info(
        "get-nautobot-attributes returning %d/%d devices run_id=%s",
        len(success_devices),
        len(context.devices),
        run.id,
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices}),
            )
        )
    return outcomes
```

### Code after — `backend/workflow_steps/get_nautobot_attributes/executor.py` (`execute`, ~47 lines)

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

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    parsed = _parse_config(config)
    credentials, nautobot_service = _bind_nautobot(run, parsed.source_id)
    variables = build_attribute_variables(parsed.list_of_attributes)

    logger.info(
        "get-nautobot-attributes run_id=%s source_id=%s devices=%d attributes=%s",
        run.id,
        parsed.source_id,
        len(context.devices),
        parsed.list_of_attributes,
    )

    results = await asyncio.gather(
        *[
            _enrich_device(
                device_id=device_id,
                device=device,
                node_id=node_id,
                nautobot_service=nautobot_service,
                credentials=credentials,
                variables=variables,
            )
            for device_id, device in context.devices.items()
        ]
    )
    success_devices, failed_devices = _partition_device_results(results)
    logger.info(
        "get-nautobot-attributes returning %d/%d devices run_id=%s",
        len(success_devices),
        len(context.devices),
        run.id,
    )
    return _build_outcomes(context, success_devices, failed_devices)
```

---

