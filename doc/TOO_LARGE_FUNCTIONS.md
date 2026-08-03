# Too-Large Functions — Inventory

**Date:** 2026-08-03
**Scope:** `backend/` Python (excluding `tests/`, `migrations/`, caches)
**Method:** AST scan of `FunctionDef` / `AsyncFunctionDef` bodies (`end_lineno - lineno + 1`)
**Rules:** `coding-style.md` / `FABLE-ANALYSIS.md` §5.2 — prefer functions **<50 lines**; flag **≥80 lines** as systematic offenders
**Related:** `doc/FABLE-ANALYSIS.md` §5.2; plan for top 10: `doc/refactoring/TOO_LARGE_FUNCTIONS_1_to_10.md`

## Summary

| Metric | Pre-pass | Post pass 1 |
|---|---:|---:|
| Functions ≥80 lines | 76 | 68 |
| Functions 50–79 lines | 87 | 100 |
| Distinct files with ≥1 function ≥80 lines | 46 | — |

Nested functions (e.g. `execute.deploy_on_device`) are included; they often dominate length inside already-large `execute()` entry points. Pass 1 thinned the 10 entry points below 80 lines; some lifted helpers (e.g. `_deploy_on_device` at 174) remain ≥80 and are candidates for a later pass.

The **"All functions ≥80 lines"** and **"50–79"** tables below are the **pre-pass** AST snapshot (2026-08-03) used to choose the top 10.

## Top 10 (≥80) — pass 1 targets (**✅ refactored**)

Plan + code before/after: `doc/refactoring/TOO_LARGE_FUNCTIONS_1_to_10.md`.

| Rank | Before | After | File | Function |
|---:|---:|---:|---|---|
| 1 | 288 | 74 | `backend/workflow_steps/deploy_rendered_template/executor.py` | `execute` |
| 2 | 243 | 54 | `backend/services/git/debug_service.py` | `GitDebugService.test_push` |
| 3 | 240 | 76 | `backend/services/nautobot/devices/update.py` | `DeviceUpdateService.update_device` |
| 4 | 238 | 75 | `backend/workflow_steps/add_to_ise/executor.py` | `execute` |
| 5 | 219 | 70 | `backend/workflow_steps/compare_data/executor.py` | `execute` |
| 6 | 216 | 31 | `backend/services/nautobot/managers/ip_manager.py` | `IPManager.ensure_ip_address_exists` |
| 7 | 202 | 75 | `backend/workflow_steps/run_command/executor.py` | `execute` |
| 8 | 197 | 63 | `backend/workflow_steps/add_to_nautobot/executor.py` | `execute` |
| 9 | 196 | 55 | `backend/hatchet/workflows/workflow_run.py` | `_dispatch_children` |
| 10 | 186 | 75 | `backend/services/sources/nautobot/evaluator.py` | `NautobotSourceEvaluator._execute_condition` |

## All functions ≥80 lines

| Lines | File | Function | Start–End |
|---:|---|---|---|
| 288 | `backend/workflow_steps/deploy_rendered_template/executor.py` | `execute` | `84–371` |
| 243 | `backend/services/git/debug_service.py` | `GitDebugService.test_push` | `242–484` |
| 240 | `backend/services/nautobot/devices/update.py` | `DeviceUpdateService.update_device` | `49–288` |
| 238 | `backend/workflow_steps/add_to_ise/executor.py` | `execute` | `122–359` |
| 219 | `backend/workflow_steps/compare_data/executor.py` | `execute` | `164–382` |
| 216 | `backend/services/nautobot/managers/ip_manager.py` | `IPManager.ensure_ip_address_exists` | `43–258` |
| 202 | `backend/workflow_steps/run_command/executor.py` | `execute` | `78–279` |
| 197 | `backend/workflow_steps/add_to_nautobot/executor.py` | `execute` | `109–305` |
| 196 | `backend/hatchet/workflows/workflow_run.py` | `_dispatch_children` | `400–595` |
| 186 | `backend/services/sources/nautobot/evaluator.py` | `NautobotSourceEvaluator._execute_condition` | `155–340` |
| 180 | `backend/services/nautobot/devices/interface_workflow.py` | `InterfaceManagerService.update_device_interfaces` | `43–222` |
| 176 | `backend/workflow_steps/get_device_configs/executor.py` | `execute` | `40–215` |
| 176 | `backend/workflow_steps/merge_content/executor.py` | `execute` | `91–266` |
| 176 | `backend/workflow_steps/store_artifact/executor.py` | `execute` | `165–340` |
| 169 | `backend/workflow_steps/login_successful/executor.py` | `execute` | `69–237` |
| 168 | `backend/workflow_steps/filter_output/executor.py` | `execute` | `116–283` |
| 166 | `backend/workflow_steps/route_on_content/executor.py` | `execute` | `80–245` |
| 164 | `backend/workflow_steps/update_ise_tacacs_key/executor.py` | `execute` | `84–247` |
| 163 | `backend/workflow_steps/get_nautobot_attributes/executor.py` | `execute` | `59–221` |
| 156 | `backend/workflow_steps/deploy_rendered_template/executor.py` | `execute.deploy_on_device` | `153–308` |
| 152 | `backend/hatchet/workflows/workflow_run.py` | `execute_steps` | `190–341` |
| 152 | `backend/services/nautobot/devices/update.py` | `DeviceUpdateService.validate_update_data` | `335–486` |
| 150 | `backend/services/sources/nautobot/live_query_mixin.py` | `NautobotLiveQueryMixin._query_devices_by_custom_field` | `345–494` |
| 141 | `backend/workflow_steps/get_ise_tacacs_key/executor.py` | `execute` | `299–439` |
| 141 | `backend/workflow_steps/render_jinja_template/executor.py` | `execute` | `151–291` |
| 139 | `backend/services/git/debug_service.py` | `GitDebugService.get_diagnostics` | `486–624` |
| 139 | `backend/services/sources/nautobot/live_query_mixin.py` | `NautobotLiveQueryMixin._query_devices_by_location` | `19–157` |
| 136 | `backend/services/git/operations.py` | `GitOperationsService.get_repository_status` | `282–417` |
| 136 | `backend/workflow_steps/compare_data/executor.py` | `execute.compare_for_device` | `213–348` |
| 136 | `backend/workflow_steps/parse_cisco_config/executor.py` | `execute` | `56–191` |
| 135 | `backend/services/nautobot/devices/interface_workflow.py` | `InterfaceManagerService._create_or_update_interface` | `386–520` |
| 126 | `backend/workflow_steps/update_nautobot_device/executor.py` | `_update_one_device` | `177–302` |
| 125 | `backend/workflow_steps/get_from_config/executor.py` | `execute` | `27–151` |
| 124 | `backend/services/nautobot/devices/interface_workflow.py` | `InterfaceManagerService._create_ip_addresses` | `261–384` |
| 124 | `backend/services/nautobot/devices/update.py` | `DeviceUpdateService._update_device_properties` | `488–611` |
| 123 | `backend/scripts/database/sync.py` | `_migrate` | `122–244` |
| 123 | `backend/services/git/file_service.py` | `GitFileService.get_directory_files` | `590–712` |
| 123 | `backend/workflow_steps/get_ise_devices/executor.py` | `execute` | `179–301` |
| 122 | `backend/hatchet/workflows/workflow_run.py` | `_run_steps_until_fan_out_or_done` | `63–184` |
| 121 | `backend/services/git/file_service.py` | `GitFileService.get_file_history` | `232–352` |
| 119 | `backend/services/nautobot/managers/interface_manager.py` | `InterfaceManager.update_interface_ip` | `173–291` |
| 117 | `backend/services/git/file_service.py` | `GitFileService.search_files` | `25–141` |
| 117 | `backend/services/git/operations.py` | `GitOperationsService.sync_repository` | `33–149` |
| 117 | `backend/services/nautobot/managers/prefix_manager.py` | `PrefixManager.ensure_prefix_exists` | `44–160` |
| 116 | `backend/services/sources/nautobot/evaluator.py` | `NautobotSourceEvaluator._execute_operation` | `38–153` |
| 116 | `backend/workflow_steps/list_contains/executor.py` | `execute` | `89–204` |
| 112 | `backend/services/execution/step_runner.py` | `StepRunner.execute_subgraph` | `530–641` |
| 110 | `backend/services/git/auth.py` | `GitAuthenticationService._resolve_from_manager` | `70–179` |
| 109 | `backend/hatchet/workflows/workflow_run.py` | `_aggregate_and_persist` | `598–706` |
| 105 | `backend/services/git/connection.py` | `GitConnectionService.test_connection` | `32–136` |
| 101 | `backend/services/git/file_service.py` | `GitFileService.get_directory_tree` | `488–588` |
| 100 | `backend/services/git/service.py` | `GitService.push` | `336–435` |
| 100 | `backend/services/sources/nautobot/live_query_mixin.py` | `NautobotLiveQueryMixin._query_devices_by_ip_prefix` | `159–258` |
| 100 | `backend/workflow_steps/run_command/executor.py` | `execute.run_on_device` | `117–216` |
| 99 | `backend/workflow_steps/merge_content/executor.py` | `execute.merge_device` | `127–225` |
| 97 | `backend/workflow_steps/route_on_content/executor.py` | `execute.process_device` | `121–217` |
| 95 | `backend/services/git/service.py` | `GitService.commit_and_push` | `505–599` |
| 94 | `backend/utils/inventory_converter.py` | `tree_to_operations` | `22–115` |
| 93 | `backend/services/execution/step_runner.py` | `StepRunner._execute_and_persist_node` | `353–445` |
| 92 | `backend/services/cache/redis_cache_service.py` | `RedisCacheService.stats` | `171–262` |
| 91 | `backend/services/git/debug_service.py` | `GitDebugService.test_write` | `78–168` |
| 90 | `backend/services/nautobot/managers/device_manager.py` | `DeviceManager.verify_device_updates` | `146–235` |
| 88 | `backend/services/nautobot/devices/interface_workflow.py` | `InterfaceManagerService._assign_ip_to_interface` | `573–660` |
| 88 | `backend/workflow_steps/update_attribute/executor.py` | `execute` | `205–292` |
| 87 | `backend/services/git/operations.py` | `GitOperationsService.remove_and_sync` | `151–237` |
| 87 | `backend/workflow_steps/filter_output/executor.py` | `execute.filter_device` | `157–243` |
| 87 | `backend/workflow_steps/log_attributes/executor.py` | `format_pretty_text` | `202–288` |
| 84 | `backend/services/git/version_control_service.py` | `GitVersionControlService.compare_commits` | `64–147` |
| 84 | `backend/services/nautobot/common/utils.py` | `prepare_update_data` | `110–193` |
| 84 | `backend/services/sources/nautobot/live_query_mixin.py` | `NautobotLiveQueryMixin._query_devices_by_primary_prefix` | `260–343` |
| 83 | `backend/workflow_steps/get_nautobot_devices/executor.py` | `execute` | `67–149` |
| 82 | `backend/services/execution/step_runner.py` | `StepRunner.resume_after_join` | `447–528` |
| 82 | `backend/workflow_steps/add_to_nautobot/executor.py` | `execute.create_one` | `189–270` |
| 80 | `backend/services/execution/schedule_service.py` | `ScheduleService.upsert_schedule` | `69–148` |
| 80 | `backend/services/git/connection.py` | `GitConnectionService._test_clone` | `233–312` |
| 80 | `backend/workflow_steps/get_git_devices/executor.py` | `execute` | `25–104` |

## Functions 50–79 lines (watch list)

Not required for the first decomposition pass, but already above the <50-line style rule.

| Lines | File | Function | Start–End |
|---:|---|---|---|
| 79 | `backend/scripts/database/sync.py` | `_report` | `41–119` |
| 79 | `backend/workflow_steps/common/git_workflow_step.py` | `run_git_workflow_step` | `111–189` |
| 78 | `backend/workflow_steps/common/content_resolver.py` | `list_exportable_content` | `44–121` |
| 78 | `backend/workflow_steps/config_to_attributes/executor.py` | `execute` | `140–217` |
| 78 | `backend/workflow_steps/login_successful/executor.py` | `execute.try_login` | `104–181` |
| 76 | `backend/services/git/auth.py` | `GitAuthenticationService.setup_auth_environment` | `264–339` |
| 76 | `backend/workflow_steps/route_on_attribute/executor.py` | `execute` | `163–238` |
| 75 | `backend/routers/netmiko.py` | `run_commands` | `64–138` |
| 75 | `backend/workflow_steps/get_device_configs/executor.py` | `execute.fetch_device` | `80–154` |
| 75 | `backend/workflow_steps/render_jinja_template/executor.py` | `execute.render_device` | `176–250` |
| 74 | `backend/hatchet/workflows/device_group_execution.py` | `execute_device_group` | `38–111` |
| 74 | `backend/workflow_steps/get_nautobot_attributes/executor.py` | `execute.enrich_device` | `116–189` |
| 73 | `backend/services/nautobot/resolvers/device_resolver.py` | `DeviceResolver.resolve_device_type_id` | `302–374` |
| 73 | `backend/services/sources/git/git_source_service.py` | `test_connection` | `54–126` |
| 71 | `backend/services/cache/redis_cache_service.py` | `RedisCacheService.get_namespace_info` | `327–397` |
| 71 | `backend/services/git/debug_service.py` | `GitDebugService.test_delete` | `170–240` |
| 71 | `backend/services/nautobot/resolvers/device_resolver.py` | `DeviceResolver.find_interface_with_ip` | `411–481` |
| 70 | `backend/core/logging_config.py` | `_build_log_config` | `44–113` |
| 70 | `backend/services/git/config.py` | `set_git_author` | `19–88` |
| 70 | `backend/services/git/service.py` | `GitService.pull` | `265–334` |
| 70 | `backend/workflow_steps/common/nautobot_interfaces.py` | `interfaces_from_nautobot_bag` | `82–151` |
| 70 | `backend/workflow_steps/log_attributes/executor.py` | `execute` | `317–386` |
| 69 | `backend/services/execution/step_runner.py` | `StepRunner.execute_all` | `120–188` |
| 69 | `backend/services/nautobot/resolvers/device_resolver.py` | `DeviceResolver.resolve_device_by_ip` | `57–125` |
| 69 | `backend/services/network/netmiko/session_pool.py` | `DeviceSessionPool.run_on_device` | `67–135` |
| 69 | `backend/workflow_steps/reachable/executor.py` | `_ping_device` | `67–135` |
| 68 | `backend/routers/sources/nautobot/ops.py` | `resolve_inventory_to_devices_detailed` | `339–406` |
| 68 | `backend/workflow_steps/parse_cisco_config/executor.py` | `execute.parse_device` | `84–151` |
| 67 | `backend/services/git/file_service.py` | `GitFileService.get_file_content_parsed` | `420–486` |
| 67 | `backend/services/git/service.py` | `GitService.commit` | `437–503` |
| 67 | `backend/services/sources/nautobot/export_service.py` | `NautobotSourceExportService.analyze_devices` | `18–84` |
| 67 | `backend/workflow_steps/update_nautobot_device/executor.py` | `execute` | `326–392` |
| 65 | `backend/services/git/file_service.py` | `GitFileService.get_file_content` | `354–418` |
| 65 | `backend/services/nautobot/managers/interface_manager.py` | `InterfaceManager.ensure_interface_exists` | `44–108` |
| 65 | `backend/workflow_steps/reachable/executor.py` | `execute` | `138–202` |
| 64 | `backend/services/credentials/credentials_service.py` | `CredentialsService.update_credential` | `111–174` |
| 64 | `backend/workflow_steps/common/attribute_write.py` | `set_device_attribute` | `33–96` |
| 63 | `backend/services/git/cache.py` | `GitCacheService.get_file_history` | `185–247` |
| 63 | `backend/services/git/service.py` | `GitService.get_status` | `651–713` |
| 63 | `backend/workflow_steps/set_default_attributes/executor.py` | `execute` | `87–149` |
| 63 | `backend/workflow_steps/store_artifact/executor.py` | `execute.store_for_device` | `215–277` |
| 62 | `backend/services/cache/redis_cache_service.py` | `RedisCacheService.get_entries` | `264–325` |
| 62 | `backend/services/nautobot/managers/interface_manager.py` | `InterfaceManager.ensure_interface_with_ip` | `110–171` |
| 61 | `backend/routers/netmiko.py` | `get_configs` | `142–202` |
| 61 | `backend/services/sources/nautobot/query_service.py` | `NautobotSourceQueryService._parse_device_data` | `379–439` |
| 60 | `backend/core/cert_installer.py` | `install_certificates` | `22–81` |
| 60 | `backend/routers/sources/nautobot/crud.py` | `export_inventory` | `149–208` |
| 60 | `backend/services/nautobot/resolvers/base_resolver.py` | `BaseResolver._resolve_by_field` | `27–86` |
| 60 | `backend/services/nautobot/resolvers/device_resolver.py` | `DeviceResolver.resolve_device_by_name_contains` | `180–239` |
| 60 | `backend/services/nautobot/resolvers/device_resolver.py` | `DeviceResolver.resolve_device_by_name_starts_with` | `241–300` |
| 59 | `backend/routers/sources/git/ops.py` | `preview_git_content_search` | `158–216` |
| 59 | `backend/workflow_steps/common/device_builders.py` | `device_context_from_ise` | `111–169` |
| 58 | `backend/routers/git/operations.py` | `get_repository_info` | `181–238` |
| 58 | `backend/scripts/database/sync.py` | `main` | `247–304` |
| 58 | `backend/services/git/csv_service.py` | `GitCsvService.get_csv_headers` | `81–138` |
| 58 | `backend/services/sources/git/git_content_search_service.py` | `GitContentSearchService.search` | `64–121` |
| 57 | `backend/services/git/connection.py` | `GitConnectionService._validate_credentials` | `138–194` |
| 57 | `backend/services/git/csv_service.py` | `GitCsvService.list_csv_files` | `23–79` |
| 56 | `backend/services/auth/oidc_service.py` | `OIDCService.provision_or_get_user` | `248–303` |
| 56 | `backend/services/execution/step_runner.py` | `StepRunner.run_node_in_sequence` | `296–351` |
| 56 | `backend/workflow_steps/common/update_field_expression.py` | `build_resolved_update_data` | `189–244` |
| 55 | `backend/scripts/ise_test.py` | `create_or_update_device` | `142–196` |
| 55 | `backend/services/git/debug_service.py` | `GitDebugService.test_read` | `22–76` |
| 54 | `backend/routers/oidc.py` | `debug_status` | `206–259` |
| 54 | `backend/services/cache/redis_cache_service.py` | `RedisCacheService.get_performance_metrics` | `399–452` |
| 54 | `backend/services/nautobot/resolvers/metadata_resolver.py` | `MetadataResolver.resolve_rack_id` | `245–298` |
| 54 | `backend/services/sources/git/git_source_service.py` | `GitDeviceService.fetch_devices` | `276–329` |
| 53 | `backend/routers/sources/nautobot/crud.py` | `import_inventory` | `217–269` |
| 53 | `backend/services/nautobot/client.py` | `NautobotService.rest_request` | `115–167` |
| 53 | `backend/services/nautobot/devices/creation.py` | `DeviceCreationService._validate_dry_run` | `133–185` |
| 53 | `backend/utils/inventory_converter.py` | `_convert_item` | `118–170` |
| 53 | `backend/workflow_steps/log_message/executor.py` | `execute` | `40–92` |
| 52 | `backend/services/git/service.py` | `GitService._clone_fresh` | `212–263` |
| 52 | `backend/services/nautobot/resolvers/device_resolver.py` | `DeviceResolver.resolve_device_id` | `127–178` |
| 52 | `backend/services/workflow_context/attribute_path.py` | `resolve_device_attribute` | `238–289` |
| 52 | `backend/services/workflow_context/attribute_path.py` | `resolve_device_attribute_state` | `292–343` |
| 52 | `backend/workflow_steps/common/attribute_defaults.py` | `normalize_defaults_block` | `192–243` |
| 52 | `backend/workflow_steps/common/nautobot_resolve.py` | `resolve_nautobot_device_id` | `53–104` |
| 51 | `backend/services/certificates/certificate_service.py` | `CertificateService.add_to_system` | `87–137` |
| 51 | `backend/services/nautobot/devices/creation.py` | `DeviceCreationService.create_device` | `35–85` |
| 51 | `backend/services/templates/templates_service.py` | `TemplatesService.update_template` | `104–154` |
| 51 | `backend/workflow_steps/git_push/executor.py` | `_push_operation` | `35–85` |
| 50 | `backend/core/config.py` | `Settings.__init__` | `60–109` |
| 50 | `backend/services/nautobot/devices/interface_workflow.py` | `InterfaceManagerService._clean_interface_ips` | `522–571` |
| 50 | `backend/services/nautobot/managers/device_manager.py` | `DeviceManager.extract_primary_ip_address` | `67–116` |
| 50 | `backend/services/network/netmiko/service.py` | `NetmikoService.deploy_config` | `88–137` |
| 50 | `backend/utils/inventory_converter.py` | `convert_saved_inventory_to_operations` | `173–222` |

## Decomposition pattern (in-repo exemplar)

Follow `backend/workflow_steps/get_ise_tacacs_key/executor.py` and the worked example in
`backend/workflow_steps/update_nautobot_device/executor.py` (decomposed by `FABLE_REST.md` Step 4):

- Extract `_parse_config` (validation + typed dataclass)
- Extract per-item / per-device helpers (`_run_for_device`, `_update_one`, …)
- Extract `_build_outcomes` / summary assembly
- Keep the public entry point (`execute` / service method) as a thin orchestrator (<80 lines, ideally <50)

