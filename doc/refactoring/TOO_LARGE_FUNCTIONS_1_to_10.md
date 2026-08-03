# Refactoring Plan — Top 10 Oversized Functions

**Date:** 2026-08-03
**Based on:** `doc/FABLE-ANALYSIS.md` §5.2; inventory `doc/TOO_LARGE_FUNCTIONS.md`
**Pattern:** `workflow_steps/update_nautobot_device/executor.py` and `get_ise_tacacs_key/executor.py`
**Goal:** Bring each of the 10 longest functions under the 80-line offender threshold
  (style rule remains `<50` lines; remaining debt is opportunistic).

> Status: **Implemented** in this pass. "Code before" is from `git show HEAD:…`
> at plan time; "Code after" is the live working tree after decomposition.

## Summary

| Rank | Function | Before | After | File |
|---:|---|---:|---:|---|
| 1 | `execute` | 288 | 74 | `backend/workflow_steps/deploy_rendered_template/executor.py` |
| 2 | `test_push` | 243 | 54 | `backend/services/git/debug_service.py` |
| 3 | `update_device` | 240 | 76 | `backend/services/nautobot/devices/update.py` |
| 4 | `execute` | 238 | 75 | `backend/workflow_steps/add_to_ise/executor.py` |
| 5 | `execute` | 219 | 70 | `backend/workflow_steps/compare_data/executor.py` |
| 6 | `ensure_ip_address_exists` | 216 | 31 | `backend/services/nautobot/managers/ip_manager.py` |
| 7 | `execute` | 202 | 75 | `backend/workflow_steps/run_command/executor.py` |
| 8 | `execute` | 197 | 63 | `backend/workflow_steps/add_to_nautobot/executor.py` |
| 9 | `_dispatch_children` | 196 | 55 | `backend/hatchet/workflows/workflow_run.py` |
| 10 | `_execute_condition` | 186 | 75 | `backend/services/sources/nautobot/evaluator.py` |

## Verification

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

## Step 1: `execute` — 288 → 74 lines

**File:** `backend/workflow_steps/deploy_rendered_template/executor.py`
**What:** Lift nested deploy helpers; thin orchestrator.
**Why:** `FABLE-ANALYSIS.md` §5.2 — functions over 80 lines are systematic offenders;
  decompose into `_parse_*` / per-item / `_build_outcomes` helpers.

**Helpers extracted:**

- `_ParsedDeployConfig`
- `_parse_deploy_config`
- `_fail_device`
- `_deploy_on_device`
- `_deploy_on_device_logged`
- `_partition_device_results`
- `_build_deploy_outcomes`

### Code before — `backend/workflow_steps/deploy_rendered_template/executor.py` (`execute`, 288 lines)

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
    source_step_node_id = str(config.get("source_step_node_id") or "").strip()
    parsed_output_key = str(config.get("parsed_output_key") or "").strip() or None
    network_driver_override = str(config.get("network_driver_override") or "").strip() or None
    execution_mode = _parse_execution_mode(config)
    write_config_after_execution = _parse_write_config(config)
    read_timeout = _parse_read_timeout(config)
    auto_confirm_prompts = _parse_auto_confirm_prompts(config)

    if not source_step_node_id:
        raise ValueError("deploy-rendered-template: source_step_node_id is required")

    db = object_session(run)
    if db is None:
        raise RuntimeError("deploy-rendered-template: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(
        db, credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)

    logger.info(
        "deploy-rendered-template started run_id=%s node_id=%s devices=%d credential=%s "
        "source=%s mode=%s write_config=%s override=%s read_timeout=%d "
        "auto_confirm_prompts=%s",
        run.id,
        node_id,
        len(context.devices),
        credential_reference,
        source_step_node_id,
        execution_mode,
        write_config_after_execution,
        network_driver_override,
        read_timeout,
        auto_confirm_prompts,
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    def _fail(
        device: DeviceContext, device_id: str, code: str, message: str
    ) -> tuple[str, DeviceContext, bool]:
        err = DeviceError(
            node_id=node_id,
            step_id="deploy-rendered-template",
            code=code,
            message=message,
        )
        failed = device.model_copy(
            update={
                "status": DeviceStatus.FAILED,
                "errors": [*device.errors, err],
            }
        )
        return device_id, failed, False

    async def deploy_on_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        host = bare_hostname(device.primary_ip4, device.hostname)
        if not host:
            return _fail(
                device,
                device_id,
                "missing_host",
                f"Device {device_id} has no hostname or primary IP",
            )

        items = list_exportable_content(
            device,
            content_source="rendered_template",
            source_step_node_id=source_step_node_id,
            parsed_output_key=parsed_output_key,
        )
        if not items:
            return _fail(
                device,
                device_id,
                "rendered_template_missing",
                "No rendered template found for the configured source step",
            )

        rendered_text = await artifact_service.resolve(items[0].artifact_ref)
        commands = [line for line in rendered_text.splitlines() if line.strip()]
        if not commands:
            return _fail(
                device,
                device_id,
                "empty_rendered_template",
                "Rendered template produced no commands",
            )

        device_type = resolve_connection_device_type(
            network_driver=device.network_driver,
            platform=device.platform,
            override=network_driver_override,
        )

        try:
            result = await netmiko.deploy_config(
                host=host,
                network_driver=device.network_driver,
                platform=device.platform,
                username=username,
                password=password,
                commands=commands,
                mode=execution_mode,
                write_config=write_config_after_execution,
                device_type=device_type,
                read_timeout=read_timeout,
                auto_confirm_prompts=auto_confirm_prompts,
                credential_reference=credential_reference,
            )

            if result.confirmed_prompts:
                logger.warning(
                    "deploy-rendered-template auto-confirmed %d prompt(s) run_id=%s "
                    "node_id=%s device_id=%s commands=%s",
                    len(result.confirmed_prompts),
                    run.id,
                    node_id,
                    device_id,
                    result.confirmed_prompts,
                )

            step_results: list[CommandResult] = []
            output_ref = await artifact_service.store(
                content=result.config_output,
                kind="command_output",
                device_id=device_id,
                run_id=context.run_id,
            )
            summary = f"{len(commands)} line(s) deployed ({execution_mode})"
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
                    run_id=context.run_id,
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
                    run_id=context.run_id,
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
                    step_id="deploy-rendered-template",
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
            return _fail(device, device_id, type(exc).__name__.lower(), str(exc))

    async def deploy_on_device_logged(
        index: int, device_id: str, device: DeviceContext
    ) -> tuple[str, DeviceContext, bool]:
        host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
        total = len(context.devices)
        logger.info(
            "deploy-rendered-template device %d/%d id=%s host=%s: connecting run_id=%s",
            index,
            total,
            device_id,
            host,
            run.id,
        )
        result = await deploy_on_device(device_id, device)
        _, _, ok = result
        logger.info(
            "deploy-rendered-template device %d/%d id=%s host=%s: %s run_id=%s",
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
            deploy_on_device_logged(index, device_id, device)
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    logger.info(
        "deploy-rendered-template finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        run.id,
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
            summary=f"deployed rendered template to {len(success_devices)} device(s)",
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices}),
                summary=f"{len(failed_devices)} device(s) failed",
            )
        )
    return outcomes
```

### Code after — `backend/workflow_steps/deploy_rendered_template/executor.py` (`execute`, 74 lines)

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

    parsed = _parse_deploy_config(config)

    db = object_session(run)
    if db is None:
        raise RuntimeError("deploy-rendered-template: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(
        db, parsed.credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)
    total = len(context.devices)

    logger.info(
        "deploy-rendered-template started run_id=%s node_id=%s devices=%d credential=%s "
        "source=%s mode=%s write_config=%s override=%s read_timeout=%d "
        "auto_confirm_prompts=%s",
        run.id,
        node_id,
        total,
        parsed.credential_reference,
        parsed.source_step_node_id,
        parsed.execution_mode,
        parsed.write_config_after_execution,
        parsed.network_driver_override,
        parsed.read_timeout,
        parsed.auto_confirm_prompts,
    )

    results = await asyncio.gather(
        *[
            _deploy_on_device_logged(
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
                netmiko=netmiko,
                artifact_service=artifact_service,
            )
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )

    success_devices, failed_devices = _partition_device_results(results)

    logger.info(
        "deploy-rendered-template finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        run.id,
    )

    return _build_deploy_outcomes(
        context=context,
        success_devices=success_devices,
        failed_devices=failed_devices,
    )
```

---

## Step 2: `test_push` — 243 → 54 lines

**File:** `backend/services/git/debug_service.py`
**What:** Split auth/stage/commit/push phases; unify origin URL restore.
**Why:** `FABLE-ANALYSIS.md` §5.2 — functions over 80 lines are systematic offenders;
  decompose into `_parse_*` / per-item / `_build_outcomes` helpers.

**Helpers extracted:**

- `_debug_result`
- `_require_push_auth`
- `_stage_debug_sentinel`
- `_commit_debug_change`
- `_push_error_suggestion`
- `_restore_origin_url`
- `_push_debug_commit`

### Code before — `backend/services/git/debug_service.py` (`test_push`, 243 lines)

```python
    def test_push(self, repo_id: int, git_auth_service) -> dict[str, Any]:
        """Test pushing a commit to the remote repository."""
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        repo = get_git_repo_by_id(repo_id)
        repo_path = Path(repo.working_dir)
        test_file_path = repo_path / ".cockpit_debug_test.txt"

        username, token, ssh_key_path = git_auth_service.resolve_credentials(repository)
        auth_type = repository.get("auth_type", "token")
        has_token_auth = bool(username and token)
        has_ssh_auth = bool(ssh_key_path)

        if auth_type == "ssh_key" and not has_ssh_auth:
            return {
                "success": False,
                "message": "SSH key authentication configured but no SSH key found",
                "details": {
                    "error": "Push requires SSH key credential",
                    "error_type": "AuthenticationRequired",
                    "suggestion": (
                        "Configure an SSH key credential for this repository"
                        " to enable push operations"
                    ),
                },
            }
        elif auth_type == "token" and not has_token_auth:
            return {
                "success": False,
                "message": "No credentials configured for push",
                "details": {
                    "error": "Push requires authentication credentials",
                    "error_type": "AuthenticationRequired",
                    "suggestion": (
                        "Configure a token credential for this repository to enable push operations"
                    ),
                },
            }
        elif auth_type == "none":
            return {
                "success": False,
                "message": "Authentication is disabled for this repository",
                "details": {
                    "error": "Push requires authentication",
                    "error_type": "AuthenticationRequired",
                    "suggestion": (
                        "Set authentication type to 'Token' or 'SSH Key' to enable push operations"
                    ),
                },
            }

        try:
            test_content = (
                f"Cockpit Debug Push Test\n"
                f"Timestamp: {datetime.now(UTC).isoformat()}\n"
                f"Repository: {repository['name']}\n"
            )
            test_file_path.write_text(test_content)

            try:
                repo.index.add([".cockpit_debug_test.txt"])
            except Exception as add_error:
                return {
                    "success": False,
                    "message": f"Failed to stage file: {str(add_error)}",
                    "details": {
                        "error": str(add_error),
                        "error_type": type(add_error).__name__,
                        "stage": "git_add",
                    },
                }

            commit_sha = None
            try:
                commit_message = f"Debug push test - {datetime.now(UTC).isoformat()}"
                with set_git_author(repository, repo):
                    commit = repo.index.commit(commit_message)
                commit_sha = commit.hexsha[:8]
            except Exception as commit_error:
                if "nothing to commit" in str(commit_error).lower():
                    return {
                        "success": False,
                        "message": "No changes to push (test file unchanged)",
                        "details": {
                            "error": str(commit_error),
                            "error_type": "NoChanges",
                            "suggestion": (
                                "The test file already exists with the same content."
                                " Use Write test first."
                            ),
                        },
                    }
                return {
                    "success": False,
                    "message": f"Failed to commit changes: {str(commit_error)}",
                    "details": {
                        "error": str(commit_error),
                        "error_type": type(commit_error).__name__,
                        "stage": "git_commit",
                    },
                }

            original_url = None
            try:
                origin = repo.remote("origin")
                original_url = list(origin.urls)[0]

                with set_ssl_env(repository):
                    with git_auth_service.setup_auth_environment(repository) as (
                        auth_url,
                        _username,
                        _token,
                        _ssh_key_path,
                    ):
                        if auth_type != "ssh_key":
                            origin.set_url(auth_url)

                        try:
                            push_info = origin.push(
                                refspec=f"{repository['branch']}:{repository['branch']}"
                            )

                            if auth_type != "ssh_key" and original_url:
                                try:
                                    origin.set_url(original_url)
                                except Exception:
                                    pass

                            if push_info and len(push_info) > 0:
                                push_result = push_info[0]
                                if push_result.flags & push_result.ERROR:
                                    return {
                                        "success": False,
                                        "message": f"Push failed: {push_result.summary}",
                                        "details": {
                                            "error": push_result.summary,
                                            "error_type": "PushError",
                                            "commit_sha": commit_sha,
                                            "suggestion": (
                                                "Check repository permissions and credentials"
                                            ),
                                        },
                                    }
                                return {
                                    "success": True,
                                    "message": "Push test successful - changes pushed to remote",
                                    "details": {
                                        "commit_sha": commit_sha,
                                        "commit_message": commit_message,
                                        "branch": repository["branch"],
                                        "remote": "origin",
                                        "file_path": str(test_file_path),
                                        "push_summary": push_result.summary,
                                        "verified": True,
                                    },
                                }
                            return {
                                "success": False,
                                "message": "Push completed but no feedback received",
                                "details": {
                                    "error": "No push info returned",
                                    "error_type": "UnknownPushResult",
                                    "commit_sha": commit_sha,
                                },
                            }

                        except Exception as push_error:
                            if auth_type != "ssh_key" and original_url:
                                try:
                                    origin.set_url(original_url)
                                except Exception:
                                    pass

                            error_message = str(push_error)
                            if (
                                "permission denied" in error_message.lower()
                                or "403" in error_message
                            ):
                                suggestion = (
                                    "Authentication failed or insufficient permissions."
                                    " Check that the token has write access."
                                )
                            elif "could not resolve host" in error_message.lower():
                                suggestion = (
                                    "Network error: Cannot reach remote repository."
                                    " Check network connectivity."
                                )
                            elif "authentication failed" in error_message.lower():
                                suggestion = (
                                    "Credentials are invalid."
                                    " Update the token in credential settings."
                                )
                            else:
                                suggestion = (
                                    "Check repository configuration and network connectivity"
                                )

                            return {
                                "success": False,
                                "message": f"Failed to push: {error_message}",
                                "details": {
                                    "error": error_message,
                                    "error_type": type(push_error).__name__,
                                    "stage": "git_push",
                                    "commit_sha": commit_sha,
                                    "suggestion": suggestion,
                                },
                            }

            except Exception as remote_error:
                return {
                    "success": False,
                    "message": f"Failed to configure remote: {str(remote_error)}",
                    "details": {
                        "error": str(remote_error),
                        "error_type": type(remote_error).__name__,
                        "stage": "configure_remote",
                    },
                }

        except PermissionError as e:
            return {
                "success": False,
                "message": "Permission denied for file operations",
                "details": {
                    "error": str(e),
                    "file_path": str(test_file_path),
                    "error_type": "PermissionError",
                    "suggestion": "Check file system permissions for the repository directory",
                },
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Unexpected error during push test: {str(e)}",
                "details": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "file_path": str(test_file_path),
                },
            }
```

### Code after — `backend/services/git/debug_service.py` (`test_push`, 54 lines)

```python
    def test_push(self, repo_id: int, git_auth_service) -> dict[str, Any]:
        """Test pushing a commit to the remote repository."""
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        repo = get_git_repo_by_id(repo_id)
        repo_path = Path(repo.working_dir)
        test_file_path = repo_path / ".cockpit_debug_test.txt"

        username, token, ssh_key_path = git_auth_service.resolve_credentials(repository)
        auth_type = repository.get("auth_type", "token")

        auth_error = _require_push_auth(repository, username, token, ssh_key_path)
        if auth_error is not None:
            return auth_error

        try:
            stage_error = _stage_debug_sentinel(repo, test_file_path, repository)
            if stage_error is not None:
                return stage_error

            commit_result = _commit_debug_change(repo, repository)
            if isinstance(commit_result, dict):
                return commit_result
            commit_sha, commit_message = commit_result

            return _push_debug_commit(
                repo=repo,
                repository=repository,
                auth_type=auth_type,
                commit_sha=commit_sha,
                commit_message=commit_message,
                test_file_path=test_file_path,
                git_auth_service=git_auth_service,
            )

        except PermissionError as e:
            return _debug_result(
                False,
                "Permission denied for file operations",
                error=str(e),
                file_path=str(test_file_path),
                error_type="PermissionError",
                suggestion="Check file system permissions for the repository directory",
            )
        except Exception as e:
            return _debug_result(
                False,
                f"Unexpected error during push test: {str(e)}",
                error=str(e),
                error_type=type(e).__name__,
                file_path=str(test_file_path),
            )
```

---

## Step 3: `update_device` — 240 → 76 lines

**File:** `backend/services/nautobot/devices/update.py`
**What:** Extract resolve/apply/finalize helpers; shorten docstring.
**Why:** `FABLE-ANALYSIS.md` §5.2 — functions over 80 lines are systematic offenders;
  decompose into `_parse_*` / per-item / `_build_outcomes` helpers.

**Helpers extracted:**

- `_empty_update_result`
- `_apply_interface_updates`
- `_compute_field_changes`
- `_collect_verification_warnings`
- `_success_update_result`
- `_resolve_device_for_update`
- `_apply_property_updates`
- `_finalize_device_update`

### Code before — `backend/services/nautobot/devices/update.py` (`update_device`, 240 lines)

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

        warnings = []
        details = {
            "before": None,
            "after": None,
            "changes": {},
        }

        try:
            # Step 1: Resolve device ID
            logger.info("Step 1: Resolving device ID")
            device_id, device_name = await self._resolve_device_id(
                device_identifier, matching_strategy=matching_strategy
            )

            if not device_id:
                if create_if_missing:
                    # TODO: Call DeviceImportService to create device
                    # For now, raise error
                    raise ValueError("Device not found and create_if_missing not yet implemented")
                else:
                    raise ValueError(f"Device not found with identifier: {device_identifier}")

            # Get device state before update (with depth=1 to get full primary_ip4 object)
            details["before"] = await self.common.get_device_details(device_id=device_id, depth=1)

            # Extract current primary_ip4 for updating existing interface
            current_primary_ip4 = await self.common.extract_primary_ip_address(details["before"])

            # Step 2: Validate and resolve update data
            logger.info("Step 2: Validating and resolving update data")
            validated_data, ip_namespace = await self.validate_update_data(
                device_id, update_data, interface_config, rack_location=rack_location
            )

            # Only return early if BOTH validated_data AND interfaces are empty
            if not validated_data and not interfaces:
                logger.info("No fields to update and no interfaces for device %s", device_name)
                return {
                    "success": True,
                    "device_id": device_id,
                    "device_name": device_name,
                    "message": f"Device '{device_name}' - no fields to update and no interfaces",
                    "updated_fields": [],
                    "warnings": ["No fields to update and no interfaces"],
                    "details": details,
                }

            # Log what we're going to process
            if not validated_data and interfaces:
                logger.info(
                    "No device fields to update, but processing %s interface(s)",
                    len(interfaces),
                )

            # Step 3: Update device properties (if any)
            updated_fields = []
            if validated_data:
                logger.info(
                    "Step 3: Updating device %s with %s field(s)",
                    device_name,
                    len(validated_data),
                )
                updated_fields = await self._update_device_properties(
                    device_id=device_id,
                    validated_data=validated_data,
                    interface_config=interface_config,
                    ip_namespace=ip_namespace,
                    device_name=device_name,
                    current_primary_ip4=current_primary_ip4,
                )
            else:
                logger.info("Step 3: Skipping device property updates (no fields to update)")

            # Step 3.5: Create/update interfaces if provided
            interfaces_created = 0
            interfaces_updated = 0
            interfaces_failed = 0
            if interfaces:
                logger.info("Step 3.5: Creating/updating %s interface(s)", len(interfaces))
                logger.info("Prefix auto-creation enabled: %s", add_prefix)
                interface_result = await self.interface_manager.update_device_interfaces(
                    device_id=device_id,
                    interfaces=interfaces,
                    add_prefixes_automatically=add_prefix,
                    sync_interfaces=sync_interfaces,
                )
                interfaces_created = interface_result.interfaces_created
                interfaces_updated = interface_result.interfaces_updated
                interfaces_failed = interface_result.interfaces_failed
                warnings.extend(interface_result.warnings)
                logger.info(
                    "Interface update complete: %s created, %s updated, %s failed",
                    interfaces_created,
                    interfaces_updated,
                    interfaces_failed,
                )

            # Get device state after update
            details["after"] = await self.common.get_device_details(device_id=device_id, depth=0)

            # Track changes
            details["changes"] = {
                field: {
                    "from": details["before"].get(field),
                    "to": details["after"].get(field),
                }
                for field in updated_fields
            }

            # Step 4: Verify updates (optional)
            logger.info("Step 4: Verifying updates")
            verification_passed, mismatches = await self.common.verify_device_updates(
                device_id, validated_data, details["after"]
            )

            if not verification_passed:
                warnings.append("Some updates may not have been applied correctly")
                # Add detailed mismatch info to warnings
                for mismatch in mismatches:
                    warnings.append(
                        f"{mismatch['field']}: expected {mismatch['expected']}, "
                        f"got {mismatch['actual']}"
                    )

            # Success!
            success_message = f"Device '{device_name}' updated successfully"
            if interfaces_created > 0 or interfaces_updated > 0:
                success_message += (
                    f" ({interfaces_created} interface(s) created, {interfaces_updated} updated)"
                )

            return {
                "success": True,
                "device_id": device_id,
                "device_name": device_name,
                "message": success_message,
                "updated_fields": updated_fields,
                "warnings": warnings,
                "interfaces_created": interfaces_created,
                "interfaces_updated": interfaces_updated,
                "interfaces_failed": interfaces_failed,
                "details": details,
            }

        except Exception as e:
            error_msg = f"Failed to update device {device_identifier}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            # Re-raise exception - let caller handle HTTP response conversion
            raise
```

### Code after — `backend/services/nautobot/devices/update.py` (`update_device`, 76 lines)

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
        """Resolve, validate, PATCH, optionally update interfaces, then verify."""
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

## Step 4: `execute` — 238 → 75 lines

**File:** `backend/workflow_steps/add_to_ise/executor.py`
**What:** Config parse + per-device create with abort vs continue.
**Why:** `FABLE-ANALYSIS.md` §5.2 — functions over 80 lines are systematic offenders;
  decompose into `_parse_*` / per-item / `_build_outcomes` helpers.

**Helpers extracted:**

- `_ParsedConfig`
- `_parse_config`
- `_build_ise_device_service`
- `_resolve_device_fields`
- `_build_create_payload`
- `_enrich_device_after_create`
- `_create_one_device`
- `_build_success_outcome`

### Code before — `backend/workflow_steps/add_to_ise/executor.py` (`execute`, 238 lines)

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

    raw_device_name = (config.get("device_name") or "").strip()
    if not raw_device_name:
        raise ValueError(f"{_STEP_ID}: device_name is not configured")

    raw_ip_address = (config.get("ip_address") or "").strip()
    if not raw_ip_address:
        raise ValueError(f"{_STEP_ID}: ip_address is not configured")

    raw_new_key = (config.get("new_key") or "").strip()
    if not raw_new_key:
        raise ValueError(f"{_STEP_ID}: new_key is not configured")

    description = str(config.get("description") or "").strip()
    device_groups = _parse_device_groups(config.get("device_groups"))

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
    created_count = 0
    failed_count = 0

    for device_id, device in context.devices.items():
        resolved_name = resolve_update_field_expression(
            device=device,
            field_key="device_name",
            raw_value=raw_device_name,
            run_id=context.run_id,
        )
        if not resolved_name:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="device_name_unresolved",
                message=(
                    f"device_name expression '{raw_device_name}' did not resolve to a "
                    f"value for '{device.name}'"
                ),
            )
            failed_count += 1
            continue

        resolved_ip = resolve_update_field_expression(
            device=device,
            field_key="ip_address",
            raw_value=raw_ip_address,
            run_id=context.run_id,
        )
        if not resolved_ip and "primary_ip4" in raw_ip_address:
            resolved_ip = _effective_primary_ip4(device)

        if not resolved_ip:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="ip_address_unresolved",
                message=(
                    f"ip_address expression '{raw_ip_address}' did not resolve to a "
                    f"value for '{device.name}' (device.primary_ip4={device.primary_ip4!r}, "
                    f"available attribute bags: {sorted(device.attribute_bags)})"
                ),
            )
            failed_count += 1
            continue

        ip_host = _extract_ip_host(resolved_ip)
        if not ip_host:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="ip_address_invalid",
                message=(
                    f"ip_address resolved to '{resolved_ip}' for '{device.name}', which is "
                    "not a valid IP address"
                ),
            )
            failed_count += 1
            continue

        resolved_key = resolve_update_field_expression(
            device=device,
            field_key="new_key",
            raw_value=raw_new_key,
            run_id=context.run_id,
        )
        if not resolved_key:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="tacacs_key_unresolved",
                message=(
                    f"new_key expression '{raw_new_key}' did not resolve to a value for "
                    f"'{device.name}' (available attribute bags: {sorted(device.attribute_bags)})"
                ),
            )
            failed_count += 1
            continue

        device_payload: dict[str, Any] = {
            "name": resolved_name,
            "NetworkDeviceIPList": [{"ipaddress": ip_host, "mask": _HOST_MASK}],
            "tacacsSettings": {"sharedSecret": resolved_key, "connectModeOptions": "OFF"},
        }
        if description:
            device_payload["description"] = description
        if device_groups:
            device_payload["NetworkDeviceGroupList"] = device_groups

        try:
            created = await device_service.create_device(device_payload)
        except ISEValidationError as exc:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="ise_device_create_rejected",
                message=f"ISE rejected creating device '{resolved_name}': {exc}",
            )
            failed_count += 1
            continue
        except ISEAPIError as exc:
            logger.warning(
                "%s: lost connection to ISE source '%s' while creating device '%s': %s",
                _STEP_ID,
                source_id,
                resolved_name,
                exc,
            )
            return [
                StepOutcome(
                    name="failure",
                    context=context,
                    summary=f"lost connection to ISE source '{source_id}': {exc}",
                )
            ]

        sealed_ise_payload = {
            **device_payload,
            "tacacsSettings": {
                **device_payload["tacacsSettings"],
                "sharedSecret": seal_secret(resolved_key),
            },
        }
        attribute_bags = {
            **device.attribute_bags,
            "ise": {**sealed_ise_payload, "id": created.get("id"), "is_group_or_prefix": False},
            "tacacs": {"shared_secret": seal_secret(resolved_key)},
        }
        updated_devices[device_id] = device.model_copy(
            update={
                "attribute_bags": attribute_bags,
                "capabilities": device.capabilities | {Capability.ATTRIBUTES},
            }
        )
        created_count += 1
        logger.info("%s: created device=%s ise_id=%s", _STEP_ID, resolved_name, created.get("id"))

    metadata = {
        **context.metadata,
        f"{node_id}.total": len(context.devices),
        f"{node_id}.created_count": created_count,
        f"{node_id}.failed_count": failed_count,
    }

    if failed_count:
        logger.warning(
            "%s: %d/%d device(s) failed for node_id=%s — see the per-device warnings above "
            "for the reason each one failed",
            _STEP_ID,
            failed_count,
            len(context.devices),
            node_id,
        )

    logger.info(
        "%s finished node_id=%s created=%d failed=%d run_id=%s",
        _STEP_ID,
        node_id,
        created_count,
        failed_count,
        context.run_id,
    )

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": updated_devices, "metadata": metadata}),
            summary=f"created {created_count}, failed {failed_count}",
        )
    ]
```

### Code after — `backend/workflow_steps/add_to_ise/executor.py` (`execute`, 75 lines)

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

    try:
        await device_service.test_connection()
    except ISEAPIError as exc:
        logger.warning("%s: could not reach ISE source '%s': %s", _STEP_ID, parsed.source_id, exc)
        return [
            StepOutcome(
                name="failure",
                context=context,
                summary=f"could not reach ISE source '{parsed.source_id}': {exc}",
            )
        ]

    updated_devices: dict[str, DeviceContext] = {}
    created_count = 0
    failed_count = 0

    for device_id, device in context.devices.items():
        result = await _create_one_device(
            device_id=device_id,
            device=device,
            cfg=parsed,
            device_service=device_service,
            source_id=parsed.source_id,
            node_id=node_id,
            context=context,
        )

        if result.kind == "abort":
            assert result.abort_outcome is not None
            return [result.abort_outcome]

        assert result.device is not None
        if result.kind == "failed":
            updated_devices[device_id] = result.device
            failed_count += 1
            continue

        updated_devices[device_id] = result.device
        created_count += 1

    return [
        _build_success_outcome(
            context=context,
            updated_devices=updated_devices,
            node_id=node_id,
            created_count=created_count,
            failed_count=failed_count,
        )
    ]
```

---

## Step 5: `execute` — 219 → 70 lines

**File:** `backend/workflow_steps/compare_data/executor.py`
**What:** Lift compare_for_device; config dataclass + outcome builder.
**Why:** `FABLE-ANALYSIS.md` §5.2 — functions over 80 lines are systematic offenders;
  decompose into `_parse_*` / per-item / `_build_outcomes` helpers.

**Helpers extracted:**

- `_ParsedCompareConfig`
- `_parse_compare_config`
- `_compare_for_device`
- `_build_compare_outcomes`

### Code before — `backend/workflow_steps/compare_data/executor.py` (`execute`, 219 lines)

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
        return [
            StepOutcome(
                name=outcome_name,
                context=context,
            )
            for outcome_name in _OUTCOME_NAMES
        ]

    content_source = parse_content_source(config)
    source_step_node_id = str(config.get("source_step_node_id") or "").strip() or None
    parsed_output_key = str(config.get("parsed_output_key") or "").strip() or None
    reference_location = (
        str(
            config.get("reference_location")
            or _default_config().get("reference_location")
            or "filesystem"
        )
        .strip()
        .lower()
    )
    normalize_line_endings = _parse_bool(config, "normalize_line_endings", default=True)
    ignore_trailing_whitespace = _parse_bool(config, "ignore_trailing_whitespace", default=False)
    diff_service = GitDiffService()

    logger.info(
        "compare-data run_id=%s devices=%d source=%s reference=%s",
        run.id,
        len(context.devices),
        content_source,
        reference_location,
    )

    buckets: dict[str, dict[str, DeviceContext]] = {
        "match": {},
        "mismatch": {},
        "failure": {},
    }
    comparison_records: list[dict[str, Any]] = []

    async def compare_for_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, str, dict[str, Any] | None]:
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
            return device_id, failed, "failure", None

        item = export_items[0]
        if len(export_items) > 1:
            logger.warning(
                "compare-data device=%s source=%s has %d export items; using first only",
                device_id,
                content_source,
                len(export_items),
            )

        try:
            source_content = await artifact_service.resolve(item.artifact_ref)
            reference_path = _render_reference_path(
                device=device,
                item=item,
                config=config,
                run_id=context.run_id,
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
            normalize_line_endings=normalize_line_endings,
            ignore_trailing_whitespace=ignore_trailing_whitespace,
        )
        normalized_reference = _normalize_text(
            reference_content,
            normalize_line_endings=normalize_line_endings,
            ignore_trailing_whitespace=ignore_trailing_whitespace,
        )
        matched = normalized_source == normalized_reference

        parsed = dict(device.parsed)
        capabilities = set(device.capabilities)
        record: dict[str, Any] = {
            "device_id": device_id,
            "content_source": content_source,
            "reference_location": reference_location,
            "reference_path": reference_path,
            "matched": matched,
            **item.extra,
        }

        if matched:
            parsed[f"{node_id}.comparison"] = _comparison_result_entry(
                matched=True,
                content_source=content_source,
                reference_path=reference_path,
                reference_location=reference_location,
                node_id=node_id,
                item_extra=item.extra,
            )
            capabilities.add(Capability.PARSED)
            enriched = device.model_copy(
                update={
                    "parsed": parsed,
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
            run_id=context.run_id,
            media_type="text/plain",
        )
        diff_stats = {
            "additions": diff_result.stats.additions,
            "deletions": diff_result.stats.deletions,
        }
        comparison_diff_key = f"{node_id}.comparison_diff"
        parsed[comparison_diff_key] = _comparison_diff_entry(
            artifact_ref=diff_ref,
            content_source=content_source,
            reference_path=reference_path,
            reference_location=reference_location,
            node_id=node_id,
            item_extra=item.extra,
            diff_stats=diff_stats,
        )
        parsed[f"{node_id}.comparison"] = _comparison_result_entry(
            matched=False,
            content_source=content_source,
            reference_path=reference_path,
            reference_location=reference_location,
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
                "parsed": parsed,
                "capabilities": capabilities,
                "status": DeviceStatus.OK,
            }
        )
        return device_id, enriched, "mismatch", record

    results = await asyncio.gather(
        *[compare_for_device(device_id, device) for device_id, device in context.devices.items()]
    )

    for device_id, updated_device, bucket_name, record in results:
        buckets[bucket_name][device_id] = updated_device
        if record is not None:
            comparison_records.append(record)

    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    metadata = dict(context.metadata)
    metadata[f"{node_id}.comparison_counts"] = counts
    if comparison_records:
        metadata[f"{node_id}.comparisons"] = comparison_records

    logger.info(
        "compare-data run_id=%s counts=%s",
        run.id,
        counts,
    )

    return [
        StepOutcome(
            name=outcome_name,
            context=context.model_copy(
                update={
                    "devices": dict(buckets[outcome_name]),
                    "metadata": metadata,
                }
            ),
        )
        for outcome_name in _OUTCOME_NAMES
    ]
```

### Code after — `backend/workflow_steps/compare_data/executor.py` (`execute`, 70 lines)

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
        return [
            StepOutcome(
                name=outcome_name,
                context=context,
            )
            for outcome_name in _OUTCOME_NAMES
        ]

    parsed = _parse_compare_config(config)
    diff_service = GitDiffService()

    logger.info(
        "compare-data run_id=%s devices=%d source=%s reference=%s",
        run.id,
        len(context.devices),
        parsed.content_source,
        parsed.reference_location,
    )

    buckets: dict[str, dict[str, DeviceContext]] = {
        "match": {},
        "mismatch": {},
        "failure": {},
    }
    comparison_records: list[dict[str, Any]] = []

    results = await asyncio.gather(
        *[
            _compare_for_device(
                device_id=device_id,
                device=device,
                node_id=node_id,
                config=config,
                context_run_id=context.run_id,
                parsed=parsed,
                artifact_service=artifact_service,
                diff_service=diff_service,
            )
            for device_id, device in context.devices.items()
        ]
    )

    for device_id, updated_device, bucket_name, record in results:
        buckets[bucket_name][device_id] = updated_device
        if record is not None:
            comparison_records.append(record)

    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    metadata = dict(context.metadata)
    metadata[f"{node_id}.comparison_counts"] = counts
    if comparison_records:
        metadata[f"{node_id}.comparisons"] = comparison_records

    logger.info(
        "compare-data run_id=%s counts=%s",
        run.id,
        counts,
    )

    return _build_compare_outcomes(context=context, buckets=buckets, metadata=metadata)
```

---

## Step 6: `ensure_ip_address_exists` — 216 → 31 lines

**File:** `backend/services/nautobot/managers/ip_manager.py`
**What:** Lookup/create/error-recovery helpers.
**Why:** `FABLE-ANALYSIS.md` §5.2 — functions over 80 lines are systematic offenders;
  decompose into `_parse_*` / per-item / `_build_outcomes` helpers.

**Helpers extracted:**

- `_is_duplicate_host_error`
- `_is_missing_prefix_error`
- `_find_ip_by_address`
- `_build_ip_create_payload`
- `_create_ip_address`
- `_find_existing_ip_by_host`
- `_ensure_parent_prefix_and_retry`
- `_handle_ip_create_error`

### Code before — `backend/services/nautobot/managers/ip_manager.py` (`ensure_ip_address_exists`, 216 lines)

```python
    async def ensure_ip_address_exists(
        self,
        ip_address: str,
        namespace_id: str,
        status_name: str = "active",
        add_prefixes_automatically: bool = False,
        use_assigned_ip_if_exists: bool = False,
        **kwargs,
    ) -> str:
        """
        Ensure IP address exists in Nautobot.

        If IP already exists, returns its UUID.
        If not, creates it and returns the new UUID.
        If creation fails due to missing prefix and add_prefixes_automatically is True,
        creates the prefix and retries IP creation.
        If creation fails due to duplicate IP with different netmask and
        use_assigned_ip_if_exists is True, finds and returns the existing IP UUID.

        Args:
            ip_address: IP address in CIDR format (e.g., "192.168.1.1/24")
            namespace_id: UUID of the namespace
            status_name: Status name for the IP (default: "active")
            add_prefixes_automatically: Auto-create missing prefix if IP creation fails
                (default: False)
            use_assigned_ip_if_exists: Use existing IP if it exists with different netmask
                (default: False)
            **kwargs: Additional fields for IP creation

        Returns:
            IP address UUID

        Raises:
            Exception: If creation fails and IP doesn't exist (or auto-features are disabled)
        """
        logger.info("Ensuring IP address exists: %s", ip_address)

        # Check if IP already exists
        ip_search_endpoint = (
            f"ipam/ip-addresses/?address={ip_address}&namespace={namespace_id}&format=json"
        )
        ip_result = await self.nautobot.rest_request(endpoint=ip_search_endpoint, method="GET")

        if ip_result and ip_result.get("count", 0) > 0:
            existing_ip = ip_result["results"][0]
            logger.info("IP address already exists: %s", existing_ip["id"])
            return existing_ip["id"]

        # IP doesn't exist, create it
        logger.info("Creating new IP address: %s", ip_address)

        # Resolve status to UUID
        status_id = await self.metadata_resolver.resolve_status_id(
            status_name, content_type="ipam.ipaddress"
        )

        ip_create_data = {
            "address": ip_address,
            "status": status_id,
            "namespace": namespace_id,
            **kwargs,  # Additional fields from caller
        }

        try:
            ip_create_result = await self.nautobot.rest_request(
                endpoint="ipam/ip-addresses/?format=json",
                method="POST",
                data=ip_create_data,
            )

            ip_id = ip_create_result["id"]
            logger.info("Created IP address: %s", ip_id)
            return ip_id

        except NautobotAPIError as e:
            error_message = str(e)

            # Check if error is due to duplicate IP with different netmask
            if (
                "IP address with this Parent and Host already exists" in error_message
                and use_assigned_ip_if_exists
            ):
                logger.warning(
                    "IP creation failed: IP %s already exists with different netmask. "
                    "Attempting to find existing IP...",
                    ip_address,
                )

                # Extract the host IP without netmask (e.g., "192.168.1.1/24" -> "192.168.1.1")
                try:
                    ip_obj = ipaddress.ip_interface(ip_address)
                    host_ip = str(ip_obj.ip)

                    logger.info("Searching for existing IP with host address: %s", host_ip)

                    # Search for IP by host address (without netmask) in the namespace
                    # Nautobot's address filter accepts IP without netmask and returns
                    # all IPs with that host
                    ip_search_endpoint = (
                        f"ipam/ip-addresses/?address={host_ip}&namespace={namespace_id}&format=json"
                    )
                    existing_ip_result = await self.nautobot.rest_request(
                        endpoint=ip_search_endpoint, method="GET"
                    )

                    if existing_ip_result and existing_ip_result.get("count", 0) > 0:
                        # Found at least one IP with this host address
                        existing_ip = existing_ip_result["results"][0]
                        logger.info(
                            "Found existing IP: %s with UUID %s",
                            existing_ip["address"],
                            existing_ip["id"],
                        )

                        # If multiple IPs found with same host, log a warning
                        if existing_ip_result.get("count", 0) > 1:
                            logger.warning(
                                "Multiple IPs found with host %s (%s total), using first: %s",
                                host_ip,
                                existing_ip_result["count"],
                                existing_ip["address"],
                            )

                        return existing_ip["id"]
                    else:
                        logger.error("Could not find existing IP for host %s", host_ip)
                        raise NautobotAPIError(
                            f"IP {host_ip} reported as duplicate but not found in namespace"
                        )

                except (ValueError, NautobotAPIError, KeyError) as lookup_error:
                    logger.error(
                        "Failed to find existing IP for %s: %s",
                        ip_address,
                        lookup_error,
                    )
                    raise NautobotAPIError(
                        f"Failed to create IP {ip_address} and could not find "
                        f"existing IP: {lookup_error}"
                    ) from lookup_error

            # Check if error is due to missing prefix
            elif "No suitable parent Prefix" in error_message:
                if add_prefixes_automatically:
                    logger.warning(
                        "IP creation failed due to missing prefix. "
                        "Attempting to create prefix automatically..."
                    )

                    # Extract the network prefix from the IP address
                    # (e.g., "192.168.1.1/24" -> "192.168.1.0/24")
                    try:
                        ip_obj = ipaddress.ip_interface(ip_address)
                        network_prefix = str(ip_obj.network)

                        logger.info("Creating missing prefix: %s", network_prefix)

                        # Import here to avoid circular dependency
                        from .prefix_manager import PrefixManager

                        prefix_manager = PrefixManager(
                            self.nautobot, self.network_resolver, self.metadata_resolver
                        )

                        # Create the prefix using ensure_prefix_exists
                        # Use the namespace_id directly since we already have it as UUID
                        await prefix_manager.ensure_prefix_exists(
                            prefix=network_prefix,
                            namespace=namespace_id,  # Pass UUID directly
                            status="active",
                            prefix_type="network",
                            description=f"Auto-created for IP {ip_address}",
                        )

                        logger.info(
                            "Successfully created prefix %s, retrying IP creation...",
                            network_prefix,
                        )

                        # Retry IP creation
                        ip_create_result = await self.nautobot.rest_request(
                            endpoint="ipam/ip-addresses/?format=json",
                            method="POST",
                            data=ip_create_data,
                        )

                        ip_id = ip_create_result["id"]
                        logger.info("Created IP address after prefix creation: %s", ip_id)
                        return ip_id

                    except (ValueError, NautobotAPIError) as prefix_error:
                        logger.error(
                            "Failed to auto-create prefix for %s: %s",
                            ip_address,
                            prefix_error,
                        )
                        raise NautobotAPIError(
                            f"Failed to create IP {ip_address} and could not "
                            f"auto-create prefix: {prefix_error}"
                        ) from prefix_error
                else:
                    # User has disabled automatic prefix creation - stop and raise clear error
                    logger.error(
                        "IP creation failed: No suitable parent prefix exists for %s. "
                        "Automatic prefix creation is disabled. Error: %s",
                        ip_address,
                        error_message,
                    )
                    raise NautobotAPIError(
                        f"Cannot create IP address {ip_address}: No suitable parent "
                        "prefix exists. Please either create the parent prefix manually "
                        "or enable automatic prefix creation in the form."
                    ) from e
            else:
                # Re-raise the original error if not a handled error type
                raise
```

### Code after — `backend/services/nautobot/managers/ip_manager.py` (`ensure_ip_address_exists`, 31 lines)

```python
    async def ensure_ip_address_exists(
        self,
        ip_address: str,
        namespace_id: str,
        status_name: str = "active",
        add_prefixes_automatically: bool = False,
        use_assigned_ip_if_exists: bool = False,
        **kwargs,
    ) -> str:
        """Return existing IP UUID or create the address (optionally auto-creating prefix)."""
        logger.info("Ensuring IP address exists: %s", ip_address)

        existing_id = await self._find_ip_by_address(ip_address, namespace_id)
        if existing_id is not None:
            return existing_id

        logger.info("Creating new IP address: %s", ip_address)
        ip_create_data = await self._build_ip_create_payload(
            ip_address, namespace_id, status_name, **kwargs
        )
        try:
            return await self._create_ip_address(ip_create_data)
        except NautobotAPIError as e:
            return await self._handle_ip_create_error(
                error=e,
                ip_address=ip_address,
                namespace_id=namespace_id,
                ip_create_data=ip_create_data,
                add_prefixes_automatically=add_prefixes_automatically,
                use_assigned_ip_if_exists=use_assigned_ip_if_exists,
            )
```

---

## Step 7: `execute` — 202 → 75 lines

**File:** `backend/workflow_steps/run_command/executor.py`
**What:** Lift nested run_on_device helpers.
**Why:** `FABLE-ANALYSIS.md` §5.2 — functions over 80 lines are systematic offenders;
  decompose into `_parse_*` / per-item / `_build_outcomes` helpers.

**Helpers extracted:**

- `_fail_device`
- `_run_on_device`
- `_run_on_device_logged`
- `_partition_device_results`
- `_build_outcomes`

### Code before — `backend/workflow_steps/run_command/executor.py` (`execute`, 202 lines)

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
    commands = _parse_commands(config)
    use_textfsm = _parse_use_textfsm(config)
    network_driver_override = str(config.get("network_driver_override") or "").strip() or None

    db = object_session(run)
    if db is None:
        raise RuntimeError("run-command: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(
        db, credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)

    logger.info(
        "run-command run_id=%s devices=%d credential=%s commands=%d textfsm=%s override=%s",
        run.id,
        len(context.devices),
        credential_reference,
        len(commands),
        use_textfsm,
        network_driver_override,
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def run_on_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        host = bare_hostname(device.primary_ip4, device.hostname)
        if not host:
            err = DeviceError(
                node_id=node_id,
                step_id="run-command",
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

        device_type = resolve_connection_device_type(
            network_driver=device.network_driver,
            platform=device.platform,
            override=network_driver_override,
        )

        try:
            result = await netmiko.send_commands(
                host=host,
                network_driver=device.network_driver,
                platform=device.platform,
                username=username,
                password=password,
                commands=commands,
                use_textfsm=use_textfsm,
                device_type=device_type,
                credential_reference=credential_reference,
            )

            step_results: list[CommandResult] = []
            media_type = "application/json" if use_textfsm else "text/plain"
            for command in commands:
                output = result.command_outputs.get(command, "")
                output_ref = await artifact_service.store(
                    content=output,
                    kind="command_output",
                    device_id=device_id,
                    run_id=context.run_id,
                    media_type=media_type,
                )
                step_results.append(
                    CommandResult(
                        node_id=node_id,
                        command=command,
                        success=result.success,
                        output_ref=output_ref,
                        summary=_build_summary(content=output, use_textfsm=use_textfsm),
                    )
                )

            updated_command_results = dict(device.command_results)
            updated_command_results[node_id] = step_results

            if not result.success:
                err = DeviceError(
                    node_id=node_id,
                    step_id="run-command",
                    code="command_failed",
                    message=result.error or "Command execution failed",
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
            err = DeviceError(
                node_id=node_id,
                step_id="run-command",
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

    async def run_on_device_logged(
        index: int, device_id: str, device: DeviceContext
    ) -> tuple[str, DeviceContext, bool]:
        host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
        total = len(context.devices)
        logger.info(
            "run-command device %d/%d id=%s host=%s: connecting run_id=%s",
            index,
            total,
            device_id,
            host,
            run.id,
        )
        result = await run_on_device(device_id, device)
        _, _, ok = result
        logger.info(
            "run-command device %d/%d id=%s host=%s: %s run_id=%s",
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
            run_on_device_logged(index, device_id, device)
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    logger.info(
        "run-command returning %d/%d devices run_id=%s",
        len(success_devices),
        len(context.devices),
        run.id,
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
            summary=f"ran {len(commands)} command(s) on {len(success_devices)} device(s)",
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices}),
                summary=f"{len(failed_devices)} device(s) failed",
            )
        )
    return outcomes
```

### Code after — `backend/workflow_steps/run_command/executor.py` (`execute`, 75 lines)

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
    commands = _parse_commands(config)
    use_textfsm = _parse_use_textfsm(config)
    network_driver_override = str(config.get("network_driver_override") or "").strip() or None

    db = object_session(run)
    if db is None:
        raise RuntimeError("run-command: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(
        db, credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)
    total = len(context.devices)

    logger.info(
        "run-command run_id=%s devices=%d credential=%s commands=%d textfsm=%s override=%s",
        run.id,
        total,
        credential_reference,
        len(commands),
        use_textfsm,
        network_driver_override,
    )

    results = await asyncio.gather(
        *[
            _run_on_device_logged(
                index=index,
                device_id=device_id,
                device=device,
                total=total,
                run_id=run.id,
                node_id=node_id,
                context_run_id=context.run_id,
                commands=commands,
                use_textfsm=use_textfsm,
                network_driver_override=network_driver_override,
                username=username,
                password=password,
                credential_reference=credential_reference,
                netmiko=netmiko,
                artifact_service=artifact_service,
            )
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )

    success_devices, failed_devices = _partition_device_results(results)

    logger.info(
        "run-command returning %d/%d devices run_id=%s",
        len(success_devices),
        total,
        run.id,
    )

    return _build_outcomes(
        context=context,
        success_devices=success_devices,
        failed_devices=failed_devices,
        command_count=len(commands),
    )
```

---

## Step 8: `execute` — 197 → 63 lines

**File:** `backend/workflow_steps/add_to_nautobot/executor.py`
**What:** Config parse + bind service + lift create_one.
**Why:** `FABLE-ANALYSIS.md` §5.2 — functions over 80 lines are systematic offenders;
  decompose into `_parse_*` / per-item / `_build_outcomes` helpers.

**Helpers extracted:**

- `_ParsedConfig`
- `_parse_config`
- `_bind_creation_service`
- `_fail_device`
- `_create_one_device`
- `_partition_and_build_outcomes`

### Code before — `backend/workflow_steps/add_to_nautobot/executor.py` (`execute`, 197 lines)

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

    source_id = str(config.get("nautobot_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is not configured")

    raw_device_fields = config.get("device_fields") or {}
    if not isinstance(raw_device_fields, dict):
        raise ValueError(f"{_STEP_ID}: device_fields must be an object")

    custom_fields_source = str(config.get("custom_fields_source") or "manual").strip().lower()
    if custom_fields_source not in _SOURCE_MODES:
        raise ValueError(
            f"{_STEP_ID}: custom_fields_source must be one of {sorted(_SOURCE_MODES)}, "
            f"got {custom_fields_source!r}"
        )

    interfaces_source = str(config.get("interfaces_source") or "manual").strip().lower()
    if interfaces_source not in _SOURCE_MODES:
        raise ValueError(
            f"{_STEP_ID}: interfaces_source must be one of {sorted(_SOURCE_MODES)}, "
            f"got {interfaces_source!r}"
        )

    default_prefix_length = str(config.get("default_prefix_length") or "/24")
    manual_interfaces = normalize_interfaces(
        build_interfaces_from_config(config, step_id=_STEP_ID),
        default_prefix_length,
    )

    if not context.devices:
        raise ValueError(
            f"{_STEP_ID}: no devices in workflow context; "
            "connect an inventory step upstream (e.g. get-from-list)"
        )

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    setting_key = build_source_key("nautobot", source_id)
    setting = SettingsRepository(db).get_by_key(setting_key)
    if setting is None:
        raise ValueError(f"{_STEP_ID}: Nautobot source '{source_id}' not found in settings")

    nautobot_url = (setting.value or {}).get("url", "").strip()
    nautobot_token = (setting.value or {}).get("token", "").strip()
    nautobot_verify_ssl = bool((setting.value or {}).get("verify_ssl", True))
    if not nautobot_url or not nautobot_token:
        raise ValueError(f"{_STEP_ID}: Nautobot source '{source_id}' is missing url or token")

    credentials = service_factory.credentials_from_connection(
        nautobot_url, nautobot_token, verify_ssl=nautobot_verify_ssl
    )
    nautobot_service = service_factory.get_nautobot_app_service()
    bound_client = CredentialsBoundNautobotClient(nautobot_service, credentials)
    creation_service = DeviceCreationService(bound_client)

    device_items = list(context.devices.items())
    run_id = str(context.run_id) if context.run_id else None

    logger.info(
        "%s started run_id=%s source_id=%s devices=%d custom_fields_source=%s interfaces_source=%s",
        _STEP_ID,
        run.id,
        source_id,
        len(device_items),
        custom_fields_source,
        interfaces_source,
    )

    async def create_one(device_key: str, device: DeviceContext) -> tuple[str, DeviceContext, bool]:
        try:
            resolved = build_resolved_update_data(
                device=device, raw_fields=raw_device_fields, run_id=run_id
            )

            if custom_fields_source == "nautobot_origin":
                all_custom_fields = _all_custom_fields_from_bag(device)
                if all_custom_fields:
                    resolved["custom_fields"] = all_custom_fields
                else:
                    resolved.pop("custom_fields", None)

            if interfaces_source == "nautobot_origin":
                interfaces = interfaces_from_nautobot_bag(
                    device.attribute_bags.get("nautobot"),
                    default_prefix_length=default_prefix_length,
                )
            else:
                interfaces = manual_interfaces

            missing = [key for key in _REQUIRED_FIELDS if not resolved.get(key)]
            if missing:
                err = DeviceError(
                    node_id=node_id,
                    step_id=_STEP_ID,
                    code="missing_required_field",
                    message=(f"Required field(s) could not be resolved: {', '.join(missing)}"),
                )
                failed = device.model_copy(
                    update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
                )
                return device_key, failed, False

            request = _build_request(resolved=resolved, config=config, interfaces=interfaces)
            result = await creation_service.create_device(request)

            if request.dry_run:
                if not result.get("success"):
                    err = DeviceError(
                        node_id=node_id,
                        step_id=_STEP_ID,
                        code="dry_run_validation_failed",
                        message="; ".join(result.get("errors") or ["dry run validation failed"]),
                    )
                    failed = device.model_copy(
                        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
                    )
                    return device_key, failed, False
                enriched = device.model_copy(
                    update={
                        "status": DeviceStatus.OK,
                        "capabilities": device.capabilities | {Capability.ATTRIBUTES},
                    }
                )
                return device_key, enriched, True

            enriched = device.model_copy(
                update={
                    "id": str(result["device_id"]),
                    "name": result.get("device_name") or device.name,
                    "source": "nautobot",
                    "status": DeviceStatus.OK,
                    "attribute_bags": {
                        **device.attribute_bags,
                        "nautobot": result.get("device") or {},
                    },
                    "capabilities": device.capabilities | {Capability.ATTRIBUTES},
                }
            )
            return device_key, enriched, True
        except Exception as exc:
            err = DeviceError(
                node_id=node_id,
                step_id=_STEP_ID,
                code=type(exc).__name__.lower(),
                message=str(exc),
            )
            failed = device.model_copy(
                update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
            )
            return device_key, failed, False

    results = await asyncio.gather(
        *[create_one(device_key, device) for device_key, device in device_items]
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    for device_key, updated_device, ok in results:
        if ok:
            success_devices[device_key] = updated_device
        else:
            failed_devices[device_key] = updated_device

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        len(success_devices),
        len(failed_devices),
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

### Code after — `backend/workflow_steps/add_to_nautobot/executor.py` (`execute`, 63 lines)

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
    del artifact_service, device_sessions

    parsed = _parse_config(config)

    if not context.devices:
        raise ValueError(
            f"{_STEP_ID}: no devices in workflow context; "
            "connect an inventory step upstream (e.g. get-from-list)"
        )

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    creation_service = _bind_creation_service(db, parsed.source_id)
    device_items = list(context.devices.items())
    run_id = str(context.run_id) if context.run_id else None

    logger.info(
        "%s started run_id=%s source_id=%s devices=%d custom_fields_source=%s interfaces_source=%s",
        _STEP_ID,
        run.id,
        parsed.source_id,
        len(device_items),
        parsed.custom_fields_source,
        parsed.interfaces_source,
    )

    results = await asyncio.gather(
        *[
            _create_one_device(
                device_key=device_key,
                device=device,
                node_id=node_id,
                config=config,
                run_id=run_id,
                parsed=parsed,
                creation_service=creation_service,
            )
            for device_key, device in device_items
        ]
    )

    success_count = sum(1 for _, _, ok in results if ok)
    failed_count = len(results) - success_count
    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        success_count,
        failed_count,
        run.id,
    )

    return _partition_and_build_outcomes(context=context, results=results)
```

---

## Step 9: `_dispatch_children` — 196 → 55 lines

**File:** `backend/hatchet/workflows/workflow_run.py`
**What:** Lift nested builders; extract approval dispatch path.
**Why:** `FABLE-ANALYSIS.md` §5.2 — functions over 80 lines are systematic offenders;
  decompose into `_parse_*` / per-item / `_build_outcomes` helpers.

**Helpers extracted:**

- `_FanOutDispatchPlan`
- `_parse_fan_out_dispatch`
- `_build_child_inputs`
- `_run_groups`
- `_tally_batch_failures`
- `_dispatch_with_approval`

### Code before — `backend/hatchet/workflows/workflow_run.py` (`_dispatch_children`, 196 lines)

```python
async def _dispatch_children(
    signal: Any,
    parent_run_id: int,
    *,
    ctx: DurableContext,
    run_uuid: str,
    canvas_nodes: list[dict[str, Any]],
    canvas_edges: list[dict[str, Any]],
) -> list[dict[str, Any] | BaseException]:
    """Split devices into groups and dispatch Hatchet child workflows.

    When the inventory step's fan-out config has ``approval.enabled``, groups
    are dispatched in sequential batches of ``approval.batch_size`` groups,
    durably pausing the run between batches until a
    ``POST /runs/{id}/approve-batch`` (or ``approve-all``) call pushes the
    batch's event — this is the Wait & Run gate. See doc/WAIT-AND-RUN.md.

    No StepRunner/DeviceSessionPool is held across this function: the
    orchestrator itself never opens device sessions during dispatch, so there
    is nothing to suspend before the approval-gate waits — children own their
    own pools (see doc/DURABLE_SSH_SESSION.md §3.5, §5.5 item 4).
    """
    from core.database import SessionLocal
    from repositories.run_repository import RunRepository
    from services.execution.step_runner import FanOutSignal

    assert isinstance(signal, FanOutSignal)

    fan_out_config = signal.fan_out_config
    mode = fan_out_config.get("mode", "per_device")
    chunk_size = max(1, int(fan_out_config.get("chunk_size", 1)))
    max_concurrency = max(0, int(fan_out_config.get("max_concurrency", 0)))
    approval_cfg: dict[str, Any] = fan_out_config.get("approval") or {}
    approval_enabled = bool(approval_cfg.get("enabled"))

    all_devices = signal.inventory_outcome.devices
    device_ids = list(all_devices.keys())

    if mode == "chunked":
        groups = [device_ids[i : i + chunk_size] for i in range(0, len(device_ids), chunk_size)]
    else:
        groups = [[did] for did in device_ids]

    if not groups:
        return []

    def _build_child_inputs(
        group_list: list[list[str]], *, index_offset: int
    ) -> list[DeviceGroupInput]:
        inputs: list[DeviceGroupInput] = []
        for offset, group_ids in enumerate(group_list):
            group_devices = {did: all_devices[did] for did in group_ids}
            group_context = signal.inventory_outcome.model_copy(update={"devices": group_devices})
            inputs.append(
                DeviceGroupInput(
                    parent_run_id=parent_run_id,
                    context_json=group_context.model_dump_json(),
                    start_node_id=signal.inventory_node_id,
                    child_index=index_offset + offset,
                    join_node_id=signal.join_node_id,
                )
            )
        return inputs

    async def _run_groups(
        group_list: list[list[str]], *, index_offset: int
    ) -> list[dict[str, Any] | BaseException]:
        child_inputs = _build_child_inputs(group_list, index_offset=index_offset)

        if max_concurrency <= 0:
            tasks = [child_workflow.aio_run(inp) for inp in child_inputs]
            return list(await asyncio.gather(*tasks, return_exceptions=True))

        # Batched execution: max_concurrency child workflows at a time
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _run_one(inp: DeviceGroupInput) -> dict[str, Any]:
            async with semaphore:
                return await child_workflow.aio_run(inp)

        tasks = [_run_one(inp) for inp in child_inputs]
        return list(await asyncio.gather(*tasks, return_exceptions=True))

    logger.info(
        "Dispatching %d child workflow group(s) parent_run_id=%s max_concurrency=%s "
        "approval_enabled=%s",
        len(groups),
        parent_run_id,
        max_concurrency,
        approval_enabled,
    )

    if not approval_enabled:
        return await _run_groups(groups, index_offset=0)

    batch_size = max(1, int(approval_cfg.get("batch_size", 1)))
    first_batch_auto = bool(approval_cfg.get("first_batch_auto", True))
    batches = [groups[i : i + batch_size] for i in range(0, len(groups), batch_size)]
    total_batches = len(batches)

    all_results: list[dict[str, Any] | BaseException] = []
    auto_approve_remaining = False
    devices_completed = 0
    devices_failed = 0
    group_index_offset = 0

    for batch_index, batch_groups in enumerate(batches):
        gate_needed = not auto_approve_remaining and not (batch_index == 0 and first_batch_auto)

        if gate_needed:
            batch_device_names = [all_devices[did].name for group in batch_groups for did in group]
            state = _build_approval_state(
                awaiting=True,
                next_batch_index=batch_index,
                total_batches=total_batches,
                batches_completed=batch_index,
                devices_total=len(device_ids),
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

        batch_results = await _run_groups(batch_groups, index_offset=group_index_offset)
        group_index_offset += len(batch_groups)
        all_results.extend(batch_results)

        batch_device_count = sum(len(group) for group in batch_groups)
        batch_failed_count = sum(
            len(group)
            for group, result in zip(batch_groups, batch_results, strict=True)
            if isinstance(result, BaseException)
        )
        devices_completed += batch_device_count
        devices_failed += batch_failed_count

        # Make finished batches inspectable while the next gate is up.
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

### Code after — `backend/hatchet/workflows/workflow_run.py` (`_dispatch_children`, 55 lines)

```python
async def _dispatch_children(
    signal: Any,
    parent_run_id: int,
    *,
    ctx: DurableContext,
    run_uuid: str,
    canvas_nodes: list[dict[str, Any]],
    canvas_edges: list[dict[str, Any]],
) -> list[dict[str, Any] | BaseException]:
    """Split devices into groups and dispatch Hatchet child workflows.

    When the inventory step's fan-out config has ``approval.enabled``, groups
    are dispatched in sequential batches of ``approval.batch_size`` groups,
    durably pausing the run between batches until a
    ``POST /runs/{id}/approve-batch`` (or ``approve-all``) call pushes the
    batch's event — this is the Wait & Run gate. See doc/WAIT-AND-RUN.md.

    No StepRunner/DeviceSessionPool is held across this function: the
    orchestrator itself never opens device sessions during dispatch, so there
    is nothing to suspend before the approval-gate waits — children own their
    own pools (see doc/DURABLE_SSH_SESSION.md §3.5, §5.5 item 4).
    """
    plan = _parse_fan_out_dispatch(signal)

    if not plan.groups:
        return []

    logger.info(
        "Dispatching %d child workflow group(s) parent_run_id=%s max_concurrency=%s "
        "approval_enabled=%s",
        len(plan.groups),
        parent_run_id,
        plan.max_concurrency,
        plan.approval_enabled,
    )

    if not plan.approval_enabled:
        return await _run_groups(
            signal,
            parent_run_id=parent_run_id,
            all_devices=plan.all_devices,
            max_concurrency=plan.max_concurrency,
            group_list=plan.groups,
            index_offset=0,
        )

    return await _dispatch_with_approval(
        signal,
        parent_run_id=parent_run_id,
        ctx=ctx,
        run_uuid=run_uuid,
        canvas_nodes=canvas_nodes,
        canvas_edges=canvas_edges,
        plan=plan,
    )
```

---

## Step 10: `_execute_condition` — 186 → 75 lines

**File:** `backend/services/sources/nautobot/evaluator.py`
**What:** Prefix/CF/native-not-equals/mapped-field helpers.
**Why:** `FABLE-ANALYSIS.md` §5.2 — functions over 80 lines are systematic offenders;
  decompose into `_parse_*` / per-item / `_build_outcomes` helpers.

**Helpers extracted:**

- `_operator_flags`
- `_pack_devices`
- `_query_prefix_field`
- `_query_custom_field_condition`
- `_query_native_not_equals`
- `_query_mapped_field`
- `_apply_client_negation`

### Code before — `backend/services/sources/nautobot/evaluator.py` (`_execute_condition`, 186 lines)

```python
    async def _execute_condition(
        self, condition: LogicalCondition
    ) -> tuple[set[str], int, dict[str, DeviceInfo]]:
        """
        Execute a single condition by calling the appropriate GraphQL query.

        Args:
            condition: The condition to execute

        Returns:
            Tuple of (device_ids_set, operations_count, devices_data)
        """
        try:
            # Validate condition values - prevent None/empty values from causing issues
            if not condition.field or condition.value is None or condition.value == "":
                logger.warning(
                    "Skipping condition with empty field or value: field=%s, value=%s",
                    condition.field,
                    condition.value,
                )
                return set(), 0, {}

            # Handle ip_prefix — operator is the GraphQL filter type (within_include/within/exact)
            if condition.field == "ip_prefix":
                devices_data = await self.query_service._query_devices_by_ip_prefix(
                    condition.value, condition.operator
                )
                device_ids = {device.id for device in devices_data}
                devices_dict = {device.id: device for device in devices_data}
                return device_ids, 1, devices_dict

            # Handle primary_prefix — matches devices whose primary_ip4 is in the CIDR
            if condition.field == "primary_prefix":
                devices_data = await self.query_service._query_devices_by_primary_prefix(
                    condition.value, condition.operator
                )
                device_ids = {device.id for device in devices_data}
                devices_dict = {device.id: device for device in devices_data}
                return device_ids, 1, devices_dict

            # Check if this is a custom field (starts with cf_)
            if condition.field.startswith("cf_"):
                # Keep the full field name with cf_ prefix for GraphQL query
                use_contains = condition.operator in ["contains", "not_contains"]
                is_negated = condition.operator in ["not_equals", "not_contains"]

                devices_data = await self.query_service._query_devices_by_custom_field(
                    condition.field, condition.value, use_contains
                )

                # Handle negation for custom fields
                if is_negated:
                    all_devices = await self.query_service._query_all_devices()
                    matched_ids = {device.id for device in devices_data}
                    devices_data = [d for d in all_devices if d.id not in matched_ids]

                device_ids = {device.id for device in devices_data}
                devices_dict = {device.id: device for device in devices_data}
                return device_ids, 1, devices_dict

            # Handle regular fields
            query_func = self.field_to_query_map.get(condition.field)
            if not query_func:
                logger.error("No query function found for field: %s", condition.field)
                return set(), 0, {}

            # Determine operator type
            use_contains = condition.operator in ["contains", "not_contains"]
            is_negated = condition.operator in ["not_equals", "not_contains"]

            # Special handling for location with not_equals - use GraphQL location__n filter
            if condition.field == "location" and condition.operator == "not_equals":
                devices_data = await self.query_service._query_devices_by_location(
                    condition.value, use_contains=False, use_negation=True
                )
                device_ids = {device.id for device in devices_data}
                devices_dict = {device.id: device for device in devices_data}
                logger.info(
                    "Condition %s %s '%s' returned %s devices (using GraphQL location__n)",
                    condition.field,
                    condition.operator,
                    condition.value,
                    len(devices_data),
                )
                return device_ids, len(devices_data), devices_dict

            # Special handling for device_type with not_equals - use GraphQL device_type__n filter
            if condition.field == "device_type" and condition.operator == "not_equals":
                devices_data = await self.query_service._query_devices_by_devicetype(
                    condition.value, use_negation=True
                )
                device_ids = {device.id for device in devices_data}
                devices_dict = {device.id: device for device in devices_data}
                logger.info(
                    "Condition %s %s '%s' returned %s devices (using GraphQL device_type__n)",
                    condition.field,
                    condition.operator,
                    condition.value,
                    len(devices_data),
                )
                return device_ids, 1, devices_dict

            # Special handling for manufacturer with not_equals - use GraphQL manufacturer__n filter
            if condition.field == "manufacturer" and condition.operator == "not_equals":
                devices_data = await self.query_service._query_devices_by_manufacturer(
                    condition.value, use_negation=True
                )
                device_ids = {device.id for device in devices_data}
                devices_dict = {device.id: device for device in devices_data}
                logger.info(
                    "Condition %s %s '%s' returned %s devices (using GraphQL manufacturer__n)",
                    condition.field,
                    condition.operator,
                    condition.value,
                    len(devices_data),
                )
                return device_ids, 1, devices_dict

            # Special handling for role with not_equals - use GraphQL role__n filter
            if condition.field == "role" and condition.operator == "not_equals":
                devices_data = await self.query_service._query_devices_by_role(
                    condition.value, use_negation=True
                )
                device_ids = {device.id for device in devices_data}
                devices_dict = {device.id: device for device in devices_data}
                logger.info(
                    "Condition %s %s '%s' returned %s devices (using GraphQL role__n)",
                    condition.field,
                    condition.operator,
                    condition.value,
                    len(devices_data),
                )
                return device_ids, 1, devices_dict

            # Only name and location support contains matching
            if condition.field in ["name", "location"] and use_contains:
                devices_data = await query_func(condition.value, use_contains=True)
            elif condition.field in ["name", "location"]:
                devices_data = await query_func(condition.value, use_contains=False)
            else:
                # Other fields only support exact matching
                if use_contains:
                    logger.warning(
                        "Field %s does not support 'contains' operator, using exact match",
                        condition.field,
                    )
                devices_data = await query_func(condition.value)

            # Handle negation (not_equals, not_contains)
            if is_negated:
                # Get all devices
                all_devices = await self.query_service._query_all_devices()

                # Filter out devices that match the condition
                matched_ids = {device.id for device in devices_data}
                devices_data = [d for d in all_devices if d.id not in matched_ids]

                logger.info(
                    "Negated condition %s %s '%s' returned %s devices",
                    condition.field,
                    condition.operator,
                    condition.value,
                    len(devices_data),
                )

            device_ids = {device.id for device in devices_data}
            devices_dict = {device.id: device for device in devices_data}

            logger.info(
                "Condition %s %s '%s' returned %s devices",
                condition.field,
                condition.operator,
                condition.value,
                len(devices_data),
            )

            return device_ids, 1, devices_dict

        except Exception as e:
            logger.error(
                "Error executing condition %s=%s: %s",
                condition.field,
                condition.value,
                e,
            )
            return set(), 0, {}
```

### Code after — `backend/services/sources/nautobot/evaluator.py` (`_execute_condition`, 75 lines)

```python
    async def _execute_condition(
        self, condition: LogicalCondition
    ) -> tuple[set[str], int, dict[str, DeviceInfo]]:
        """
        Execute a single condition by calling the appropriate GraphQL query.

        Args:
            condition: The condition to execute

        Returns:
            Tuple of (device_ids_set, operations_count, devices_data)
        """
        try:
            if not condition.field or condition.value is None or condition.value == "":
                logger.warning(
                    "Skipping condition with empty field or value: field=%s, value=%s",
                    condition.field,
                    condition.value,
                )
                return set(), 0, {}

            if condition.field in ("ip_prefix", "primary_prefix"):
                return await self._query_prefix_field(
                    condition.field, condition.value, condition.operator
                )

            if condition.field.startswith("cf_"):
                return await self._query_custom_field_condition(condition)

            query_func = self.field_to_query_map.get(condition.field)
            if not query_func:
                logger.error("No query function found for field: %s", condition.field)
                return set(), 0, {}

            use_contains, is_negated = _operator_flags(condition.operator)

            if condition.operator == "not_equals":
                native_result = await self._query_native_not_equals(
                    condition.field, condition.value
                )
                if native_result is not None:
                    return native_result

            devices_data = await self._query_mapped_field(
                condition.field, condition.value, use_contains
            )

            if is_negated:
                devices_data = await self._apply_client_negation(devices_data)
                logger.info(
                    "Negated condition %s %s '%s' returned %s devices",
                    condition.field,
                    condition.operator,
                    condition.value,
                    len(devices_data),
                )

            logger.info(
                "Condition %s %s '%s' returned %s devices",
                condition.field,
                condition.operator,
                condition.value,
                len(devices_data),
            )

            return _pack_devices(devices_data)

        except Exception as e:
            logger.error(
                "Error executing condition %s=%s: %s",
                condition.field,
                condition.value,
                e,
            )
            return set(), 0, {}
```

---

