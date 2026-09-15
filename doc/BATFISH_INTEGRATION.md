# Batfish Integration

Backend integration with [Batfish](https://github.com/batfish/batfish), an
offline network-configuration analysis engine, for answering routing/
reachability/ACL questions against already-collected device configs from a
workflow. Unlike the pyATS integration, Batfish's heavy engine runs in its
own container already (`docker/batfish/`) and the Python client (`pybatfish`)
is thin enough to live directly in the backend's own venv — **no shim
container is needed here.**

Optional, like pyATS: nothing in this integration is required for the app to
function, and the **Batfish** step category is hidden from the canvas
palette entirely until a Batfish source is configured (mirrors pyATS's
`hasPyatsSource` gate in `step-catalog.tsx` — see "Frontend: category
gating" below).

## Contents

- [Why no separate shim container](#why-no-separate-shim-container)
- [Architecture](#architecture)
- [File map](#file-map)
- [Snapshot lifecycle: networks, snapshots, retention](#snapshot-lifecycle-networks-snapshots-retention)
- [Configuring a source](#configuring-a-source)
- [Security notes](#security-notes)
- [Workflow steps](#workflow-steps)
  - [Get from Batfish](#get-from-batfish-batfish-start-run)
  - [Init Batfish Snapshot](#init-batfish-snapshot-batfish-init-snapshot)
  - [Extract Facts](#extract-facts-batfish-extract-facts)
  - [Validate Facts](#validate-facts-batfish-validate-facts)
  - [Batfish Routing Table](#batfish-routing-table-batfish-routing-table)
  - [Batfish Node Properties](#batfish-node-properties-batfish-node-properties)
  - [Batfish Interface Properties](#batfish-interface-properties-batfish-interface-properties)
  - [Batfish OSPF Facts](#batfish-ospf-facts-batfish-ospf-facts-get-ospf-facts)
  - [Batfish BGP Facts](#batfish-bgp-facts-batfish-bgp-facts-get-bgp-facts)
  - [Batfish ACL Check](#batfish-acl-check-batfish-acl-check)
  - [Batfish Path Check](#batfish-path-check-batfish-path-check)
- [Frontend: category gating](#frontend-category-gating)
- [Viewing results: the run detail UI](#viewing-results-the-run-detail-ui)
- [Template Editor integration: ad-hoc preview queries](#template-editor-integration-ad-hoc-preview-queries)
  - [Generic ad-hoc questions: the long tail beyond routes/reachability/testFilters](#generic-ad-hoc-questions-the-long-tail-beyond-routesreachabilitytestfilters)
- [Open items / verify during hardening](#open-items--verify-during-hardening)

## Why no separate shim container

pyATS needed its own container because the *engine itself* (pyATS/Genie/
Unicon) couldn't run in the backend's Python 3.14 venv — its published wheels
only confirm 3.12/3.13, and its dependency tree (a pinned `paramiko`/
`cryptography`, plus `unicon`) risked colliding with the backend's own deps.

Batfish is structurally different: the engine (parsing, modeling, answering
questions) already runs inside the `batfish` container we stood up in
`docker/batfish/` (the coordinator + worker, via the official
`batfish/allinone` image). The backend only needs a **client** that speaks
Batfish's RPC protocol — that's `pybatfish`, and it is a genuinely thin
dependency. Checked directly against PyPI metadata rather than assumed
(current release `2026.8.19.3660`):

```
requires_python: >=3.10          (no upper bound — 3.14 is fine)
requires_dist:  attrs, deepdiff, pandas, python-dateutil, PyYAML,
                requests, requests-toolbelt, setuptools, simplejson, urllib3
```

No `unicon`/`paramiko`-class dependency, and nothing here collides with
`backend/requirements.txt` (which has no `pandas`/`requests`/`urllib3` pin at
all, and an unconstrained `PyYAML` requirement compatible with the pinned
`PyYAML==6.0.3`). So `pybatfish` is added straight to
`backend/requirements.txt` and imported directly from
`backend/services/batfish/client.py` — no `Dockerfile`, no second
`docker-compose.yml` service, no shim HTTP contract to design.

## Architecture

```
Settings -> Sources -> Batfish              backend/services/batfish/client.py
  (Settings UI)              (BatfishService: pybatfish.Session, app-scoped)
        |                              |
        v                              v pybatfish's own RPC protocol (ports 9996/9997)
  sources.batfish.<id>          batfish container (coordinator + worker)
  (settings only --                    |
   no credential row)                  v  vendor-neutral model, in-memory per snapshot
                                 answers routing/reachability/ACL questions
```

Reachability of the `batfish` container follows the same two-case pattern as
`docker/pyats` and `docker/openbao`: `host=batfish` on the shared `backend`
Docker network for a containerized backend, `host=127.0.0.1` for the native
dev workflow (`python start.py` / `python scripts/run_worker_dev.py`) — see
`docker/batfish/README.md`. Because the coordinator has no authentication,
the source config has no credential at all (see "Configuring a source"
below) — just host + one port.

**Only one port is actually used, despite two being published.** Checked
directly against `pybatfish.client.session.Session.__init__`: it accepts
`port_v1` (default 9997) but never assigns it to `self` or uses it anywhere —
every request is built from `self.port_v2` (default **9996**, confusingly
named "v2" despite being numerically the lower/older port). `port_v1`/9997 is
a vestigial constructor parameter in the installed `pybatfish` release. The
source config therefore only needs `host` + one `port` (default `9996`); the
9997 publish in `docker/batfish/docker-compose.yaml` is harmless to keep (matches
upstream's own quick-start convention and costs nothing) but isn't load-bearing
for anything this integration does.

## Session caching and concurrency safety

`pybatfish.client.session.Session` is **synchronous** (`requests`-based, no
`asyncio` support) and **stateful**: `set_network(name)` mutates
`self.network`, and every subsequent call implicitly targets whatever
network was last set — there is no `network=` kwarg on the question-answering
path to override it per call (confirmed from `Session.answer_question`'s
signature: `snapshot`/`reference_snapshot` can be overridden per call,
`network` cannot). Naively caching one `Session` per `(host, port)` and
reusing it across concurrent calls would let two unrelated calls — two
workflow runs querying Batfish at the same time, e.g. on the live and
background-tier Hatchet workers — race on `self.network`, silently querying
the wrong network's data.

`BatfishService` avoids this by caching sessions **per `(host, port,
network)`**, calling `set_network()` exactly once when a cache entry is
created and never again for that entry — so a cached session's `.network`
never changes after creation, and it's safe to share across concurrent
callers. `snapshot` is never relied upon as session state — every question
call passes `answer(snapshot=snapshot_name)` explicitly. `init_snapshot`,
`list_snapshots`, and `delete_snapshot` all still implicitly target
`self.network` (none of them take a `network=` override either, confirmed
from their signatures) — safe under this scheme specifically because that
value is fixed at cache-entry creation and never mutated afterward.

Constructing a `Session` performs a blocking HTTP call itself
(`load_questions=True` by default runs `self.q.load()` in `__init__`), so
both session creation and every actual client call must run via
`asyncio.to_thread(...)` — the same pattern already used for other
blocking-library wrapping in this codebase
(`services/artifacts/filesystem_artifact_service.py`,
`services/artifacts/sinks/git_sink.py`), not a new `ThreadPoolExecutor` like
`DeviceSessionPool`'s (that one bounds true concurrent SSH connections;
Batfish calls are one-shot RPCs with no comparable pooling need). A
plain `asyncio.Lock` around "get-or-create" on the cache dict prevents two
concurrent callers from double-constructing the same `(host, port, network)`
entry.

`check_health` (used by test-connection) does **not** go through this cache
at all — it builds a throwaway `Session(host, port)` and calls
`list_networks()`, which doesn't depend on `self.network` being set to
anything in particular.

## File map

**Implemented.** Everything below exists on `feature/batfish` (as of this
writing, not yet merged to `main` — check `git status`/`git log` for current
branch/commit state rather than trusting this document's staleness).

```
backend/services/batfish/
├── __init__.py
├── client.py                              # BatfishService -- wraps pybatfish.client.session.Session
├── credentials.py                         # BatfishConnection(host, port=9996) -- no secret fields
├── common/exceptions.py                   # BatfishError, BatfishValidationError, BatfishAPIError
├── source_config_service.py               # BatfishSourceConfigService -- settings only, no credential
├── query_helpers.py                       # resolve_latest_snapshot_name, build_batfish_headers,
│                                           # require_field, query_routes/query_reachability/
│                                           # query_test_filters/query_node_properties/
│                                           # query_interface_properties -- the ONE place each typed
│                                           # question's pybatfish call is built and made; shared by
│                                           # the workflow-step executors AND BatfishPreviewService.
│                                           # Also GENERIC_QUESTION_ALLOWLIST + query_generic -- the
│                                           # ad-hoc "any allow-listed question" surface, see
│                                           # "Template Editor integration" below
└── preview_service.py                     # BatfishPreviewService -- ad-hoc routes/reachability/
                                            # testFilters/generic, no WorkflowRun; the Template
                                            # Editor's Options-modal preview path

backend/workflow_steps/common/batfish_properties.py   # Shared engine for the "property lookup" steps
                                            # (artifact/metadata storage, route_empty_to_devices/
                                            # empty_match_mode, per-device enrichment) -- both
                                            # batfish-node-properties and batfish-interface-properties
                                            # are thin PropertyQuestionSpec-driven callers of this now

backend/models/batfish.py                  # Pydantic request/response models: source CRUD, test-connection,
                                            # + BatfishQueryQuestion/BatfishRoutesQueryRequest/
                                            # BatfishReachabilityQueryRequest/BatfishTestFiltersQueryRequest/
                                            # BatfishGenericQueryRequest/BatfishQueryResponse (ad-hoc
                                            # query models -- `question` on the response is a plain
                                            # str, not the closed BatfishQueryQuestion Literal, since a
                                            # generic query's question name isn't one of the 3 typed ones)
backend/routers/sources/batfish/
├── __init__.py
├── crud.py                                # /sources/batfish -- source configuration CRUD
├── ops.py                                 # /sources/batfish/{source_id}/test-connection
├── query.py                               # /sources/batfish/{source_id}/query/{routes,reachability,
│                                           # test-filters,generic} -- ad-hoc preview queries, see
│                                           # "Template Editor integration" below
└── discovery.py                           # /sources/batfish/{source_id}/networks,
                                            # /sources/batfish/{source_id}/networks/{network}/snapshots
backend/dependencies.py                    # get_batfish_preview_service (FastAPI dependency)
backend/service_factory.py                 # build_batfish_preview_service

backend/core/models/templates.py           # Template.batfish_config: str | None -- JSON-as-text column,
                                            # same convention as nautobot_attributes/pre_run_commands; stores
                                            # only the query DEFINITION (source/network/snapshot/question/
                                            # params), never the fetched answer
backend/models/templates.py                # BatfishQueryConfig model; TemplateCreate/TemplateUpdate/
                                            # TemplateResponse gained a batfish_config field
backend/services/templates/templates_service.py   # create/update/_to_dict thread batfish_config through
                                                    # (json.dumps/json.loads, mirroring nautobot_attributes)
backend/routers/templates.py               # create_template/update_template pass payload.batfish_config through

backend/tests/unit/test_batfish_preview_service.py       # BatfishPreviewService (incl. run_generic), mocked BatfishService
backend/tests/unit/test_batfish_query_router_auth.py     # auth/permission + error-mapping for the query router (incl. /query/generic)
backend/tests/unit/test_batfish_query_helpers.py         # query_generic allow-list gate, mocked BatfishService
backend/tests/unit/test_batfish_properties_common.py     # workflow_steps.common.batfish_properties pure-logic pieces

backend/service_factory.py                 # get/set_batfish_app_service, build_batfish_source_config_service
backend/dependencies.py                    # get_batfish_source_config_service (FastAPI dependency)
backend/main.py                            # BatfishService lifespan startup/shutdown (API process), router registration
backend/hatchet/worker_services.py         # BatfishService lifespan startup/shutdown (shared by both Hatchet workers)
backend/services/auth/rbac_seed.py         # sources.batfish read/write/delete permissions
backend/services/settings/source_keys.py   # "batfish" added to SourceType + BATFISH_KEY_PREFIX

backend/workflow_steps/common/batfish_context.py   # resolve_batfish_snapshot/store_batfish_snapshot (metadata lookup)
                                                     # + resolve_batfish_snapshot_ref (explicit source/network bypass)
                                                     # + devices_from_nodes (Node column -> DeviceContext dedup, shared by Get from Batfish)
backend/workflow_steps/batfish_start_run/{__init__.py,executor.py,config.py}       # "Get from Batfish" -- three-way: placeholder / metadata-driven / direct-target device listing
backend/workflow_steps/batfish_init_snapshot/{__init__.py,executor.py,config.py}
backend/workflow_steps/batfish_init_snapshot/git_source.py   # config_source: git -- glob-based file collection
backend/workflow_steps/batfish_routing_table/{__init__.py,executor.py,config.py}
backend/workflow_steps/batfish_node_properties/{__init__.py,executor.py,config.py}   # exposes nodeProperties' `properties` filter directly (Get from Batfish never sets it)
backend/workflow_steps/batfish_interface_properties/{__init__.py,executor.py,config.py}   # interfaceProperties -- one row per (node, interface), a different question/shape from nodeProperties
backend/workflow_steps/common/batfish_combined_facts.py   # shared "combined facts" engine -- CombinedQuestionSpec/
                                               # build_combined_facts_outcomes; N-question grouping + per-device merge,
                                               # NOT a PropertyQuestionSpec (see Batfish OSPF Facts section)
backend/workflow_steps/common/batfish_ospf_facts.py   # "Get OSPF Facts" question specs (process/areas/interfaces/edges)
backend/workflow_steps/batfish_ospf_facts/{__init__.py,executor.py,config.py}   # "Get OSPF Facts" -- each question independently toggleable
backend/workflow_steps/common/batfish_bgp_facts.py    # "Get BGP Facts" question specs (process/peers/sessions/edges)
backend/workflow_steps/batfish_bgp_facts/{__init__.py,executor.py,config.py}    # "Get BGP Facts" -- each question independently toggleable
backend/workflow_steps/batfish_path_check/{__init__.py,executor.py,config.py}
backend/workflow_steps/batfish_acl_check/{__init__.py,executor.py,config.py}
backend/workflow_steps/batfish_validate_facts/{__init__.py,executor.py,config.py}       # facts_source: git reuses batfish_init_snapshot/git_source.py::collect_git_source_files
backend/workflow_steps/batfish_extract_facts/{__init__.py,executor.py,config.py}
backend/services/batfish/client.py            # gained BatfishService.validate_facts/extract_facts/node_properties/interface_properties/
                                               # ospf_process_configuration/ospf_area_configuration/ospf_interface_configuration/ospf_edges/
                                               # bgp_process_configuration/bgp_peer_configuration/bgp_session_status/bgp_edges
backend/services/batfish/query_helpers.py     # gained query_ospf_process_configuration/query_ospf_area_configuration/
                                               # query_ospf_interface_configuration/query_ospf_edges/
                                               # query_bgp_process_configuration/query_bgp_peer_configuration/
                                               # query_bgp_session_status/query_bgp_edges
backend/services/execution/step_registry.py   # 11 imports + dict entries
backend/workflow_steps/registry.yaml          # 11 entries, palette_category: batfish

backend/tests/unit/test_batfish_{client,source_config_service,router_auth,context_helper}.py
backend/tests/unit/test_batfish_context_ref_resolver.py
backend/tests/unit/test_batfish_git_source.py
backend/tests/unit/test_batfish_start_run_executor.py
backend/tests/unit/test_batfish_{init_snapshot,routing_table,path_check,acl_check}_executor.py
backend/tests/unit/test_batfish_node_properties_executor.py
backend/tests/unit/test_batfish_interface_properties_executor.py
backend/tests/unit/test_batfish_ospf_facts_common.py
backend/tests/unit/test_batfish_ospf_facts_executor.py
backend/tests/unit/test_batfish_bgp_facts_common.py
backend/tests/unit/test_batfish_bgp_facts_executor.py
backend/tests/unit/test_batfish_validate_facts_executor.py
backend/tests/unit/test_batfish_extract_facts_executor.py
backend/tests/unit/test_batfish_discovery_router.py

frontend/src/components/features/settings/types/settings-api.ts   # BatfishSource*/BatfishTestConnection*/
                                                                    # BatfishNetworksResponse/BatfishSnapshot* types
frontend/src/lib/query-keys.ts                                     # queryKeys.sourcesBatfish (list/networks/snapshots)
frontend/src/hooks/queries/use-batfish-sources-query.ts             # mirrors use-pyats-sources-query.ts
frontend/src/hooks/queries/use-batfish-sources-mutations.ts
frontend/src/hooks/queries/use-batfish-networks-query.ts            # GET .../networks
frontend/src/hooks/queries/use-batfish-snapshots-query.ts           # GET .../networks/{network}/snapshots
frontend/src/components/features/settings/dialogs/batfish-source-dialog.tsx   # host+port only, no credential field
frontend/src/components/features/settings/hooks/use-sources-settings.ts       # "batfish" slice
frontend/src/components/features/settings/hooks/use-sources-settings-save.ts  # "batfish" dialog/save/delete branch
frontend/src/components/features/settings/components/sources-settings-canvas.tsx  # Batfish SourceListSection + dialog

frontend/src/components/features/workflow-steps/shared/batfish-source-config.ts        # BATFISH_SOURCE_ID_KEY etc.
frontend/src/components/features/workflow-steps/shared/batfish-source-select-dialog.tsx
frontend/src/components/features/workflow-steps/shared/batfish-direct-target-fields.tsx  # shared batfish_source_id/network/snapshot block (8 steps: 7 query/fact steps + Get from Batfish)
frontend/src/components/features/workflow-steps/shared/batfish-fact-keys.ts  # BATFISH_FACT_KEYS -- shared by Validate/Extract Facts panels+help
frontend/src/components/features/workflow-steps/batfish-start-run/{index.tsx,help-panel.tsx}  # "Get from Batfish" -- nodes_filter + BatfishDirectTargetFields
frontend/src/components/features/workflow-steps/batfish-init-snapshot/{index.tsx,help-panel.tsx}  # config_source toggle, git fields, network_name
frontend/src/components/features/workflow-steps/batfish-routing-table/{index.tsx,help-panel.tsx}
frontend/src/components/features/workflow-steps/batfish-node-properties/{index.tsx,help-panel.tsx}
frontend/src/components/features/workflow-steps/batfish-interface-properties/{index.tsx,help-panel.tsx}
frontend/src/components/features/workflow-steps/shared/batfish-interface-property-keys.ts  # curated, non-exhaustive suggestion list -- see step section for why
frontend/src/components/features/workflow-steps/shared/batfish-properties-fields.tsx  # shared ConfigPanel fields for the two "property lookup" steps -- see step section
frontend/src/components/features/workflow-steps/shared/batfish-generic-question-names.ts  # suggestion list mirroring GENERIC_QUESTION_ALLOWLIST, not enforcement
frontend/src/components/features/workflow-steps/batfish-ospf-facts/{index.tsx,help-panel.tsx}  # nodes + 4 question checkboxes + BatfishDirectTargetFields (no properties/route_empty_to_devices -- doesn't apply)
frontend/src/components/features/workflow-steps/batfish-bgp-facts/{index.tsx,help-panel.tsx}  # same pattern as batfish-ospf-facts above
frontend/src/components/features/workflow-steps/batfish-path-check/{index.tsx,help-panel.tsx}
frontend/src/components/features/workflow-steps/batfish-acl-check/{index.tsx,help-panel.tsx}
frontend/src/components/features/workflow-steps/batfish-validate-facts/{index.tsx,help-panel.tsx}  # facts_source toggle (rendered_yaml/field/git)
frontend/src/components/features/workflow-steps/batfish-extract-facts/{index.tsx,help-panel.tsx}
frontend/src/lib/plugin-ui-registry.ts        # 11 PLUGIN_UI_REGISTRY entries
frontend/src/components/features/workflows/utils/step-visuals.ts   # "batfish" category label/colors/icons
frontend/src/components/features/workflows/components/step-catalog.tsx  # hasBatfishSource gate

frontend/src/components/features/workflows/components/step-result-viewer/batfish-result-panel.tsx  # see "Viewing results" below
frontend/src/components/features/workflows/components/step-result-viewer/{metadata-panel,outcome-context-view,devices-section,device-card,device-detail-dialog}.tsx  # wiring for the above (edits, not new)

frontend/src/components/features/templates/types.ts                       # BatfishQueryQuestion, BatfishEditorQuestion
                                                                            # (adds a "generic" sentinel), BatfishQueryConfig,
                                                                            # BatfishQueryResult; Template/TemplateCreatePayload
                                                                            # gained batfish_config
frontend/src/components/features/templates/constants.ts                   # BATFISH_VARIABLE
frontend/src/components/features/templates/hooks/use-template-variables.ts     # toggleBatfishVariable, setBatfishResult (edits)
frontend/src/components/features/templates/hooks/use-template-editor-batfish.ts  # target/question/genericQuestionName/params
                                                                                    # state + the query mutation
frontend/src/components/features/templates/hooks/use-template-editor.ts        # wires the above in, loads/saves batfish_config (edits)
frontend/src/components/features/templates/hooks/use-template-editor-save.ts   # threads batfish_config into the save payload (edits)
frontend/src/components/features/templates/components/options-dialog.tsx       # renamed from netmiko-options-dialog.tsx --
                                                                            # now a tabbed "Netmiko" / "Batfish" dialog
frontend/src/components/features/templates/components/batfish-options-tab.tsx  # source/network/snapshot + question picker +
                                                                            # per-question params + Run Query + JSON preview;
                                                                            # a 4th "Custom Question..." block posts to
                                                                            # /query/generic with a free-text question name
                                                                            # (datalist-suggested) + a JSON params textarea
```

No new `backend/core/models/{domain}.py` SQLAlchemy table — like pyATS and
ISE, a Batfish source's config lives entirely in the generic `settings` table
under the `sources.batfish.<id>` key namespace (`SettingsRepository`); there
is no per-source credential row since the coordinator has no auth. This
means the usual "Adding New Backend Endpoint" 6-step recipe in `CLAUDE.md`
doesn't apply as-is for the *source config* endpoints (no model, no
repository, no service-layer-over-a-table) — it mirrors
`services/pyats/source_config_service.py` / `services/ise/source_config_service.py`
instead. The **workflow steps**, by contrast, follow "Adding a New Workflow
Step" exactly as documented.

**Three independent processes, two independent lifespans — same trap as
pyATS.** `BatfishService` must be started/stopped in **both**
`main.py`'s `lifespan()` *and* `hatchet/worker_services.py::start_all()`
(shared by `hatchet/worker.py` and `hatchet/dynamic_worker.py`). Workflow
steps run only in a worker process; registering the service in `main.py`
alone leaves `service_factory.get_batfish_app_service()` raising at every
step call while the API's own test-connection endpoint works fine — this bit
the pyATS integration first (see that doc's File map section) and is exactly
the kind of failure that's easy to miss in review because the symptom is
worker-only.

## Snapshot lifecycle: networks, snapshots, retention

Batfish's own model is two-level: a **network** (a long-lived namespace) 
contains many **snapshots** (one point-in-time set of configs each). This
maps naturally onto Manus's own model:

- **Network name = `f"manus-workflow-{workflow_id}"`, or an explicit override.**
  One Batfish network per Manus workflow by default — keeps different
  workflows' device sets from colliding on node/filter names, and makes
  `bf.list_snapshots()` a meaningful "history for this workflow" view later.
  An optional `network_name` config field on `batfish-init-snapshot`
  overrides this verbatim, giving a network a stable identity independent of
  `workflow_id` — the mechanism a production network (refreshed on its own
  schedule, queried by other workflows that don't share its `workflow_id`)
  uses. See "Config source: live vs. git" below.
- **Snapshot name = `f"run-{run_id}"`.** One snapshot per `batfish-init-snapshot`
  execution, named after the `WorkflowRun` that produced it — traceable back
  to a specific run, and naturally unique (no timestamp collision handling
  needed). Unaffected by `network_name` — even a stable, shared network still
  gets one new, uniquely-named snapshot per init run.

**A Batfish network is never deleted by this integration — only individual
snapshots are pruned.** Worth stating plainly since it's easy to assume
otherwise: `batfish-init-snapshot` never calls `bf.delete_network(...)`
itself. A network (and every snapshot in it beyond what retention below
prunes) persists in the Batfish coordinator indefinitely across runs, unless
removed out-of-band. This is what makes the git-mode/named-network pattern
below workable at all — a nightly refresh reuses the same standing network
rather than starting from nothing each time.

**Retention is enforced by the step itself, not left as an unbounded
liability.** After a successful `init_snapshot(...)`, the executor calls
`bf.list_snapshots(verbose=True)` for the network and deletes every snapshot
beyond the most recent `retain_snapshots` (a step config field, default
`5`) via `bf.delete_snapshot(name)`. **Snapshot names are not chronologically
sortable and retention must not assume they are** — `run-{run_id}` uses
`WorkflowRun.id` (an autoincrementing int, not `WorkflowContext.run_id`,
which is `run.uuid` — confirmed from `step_runner/runner.py`'s
`WorkflowContext(run_id=run.uuid, ...)`), but even a numeric suffix sorts
wrong lexically (`"run-10" < "run-9"`). The real fix, confirmed against a
live coordinator: `verbose=True` returns each snapshot's
`metadata.creationTimestamp` (a fixed-width, always-UTC, `Z`-suffixed ISO
8601 string — safe to sort lexically), e.g.:

```json
[{"name": "probe-snapshot", "metadata": {"creationTimestamp": "2026-09-12T16:21:45.810915760Z", ...}}]
```

`BatfishService.list_snapshots_with_metadata()` wraps this
(`list_snapshots(verbose=True)`); the retention sweep sorts entries by that
field, not by name, before deciding what to delete. `bf.delete_snapshot(name)`
and `bf.delete_network(name)` both exist on `pybatfish`'s `Session` for the
actual deletion.

**Building the snapshot directory (`config_source: live`, the default).**
`pybatfish` has no "upload N files as
one multi-device snapshot from in-memory text" call —
`init_snapshot_from_text()` exists but is explicitly single-file/single-node
(confirmed from its docstring: one `text` blob, one optional `filename`). For
our multi-device case, `batfish-init-snapshot`'s executor must:

1. Create a `tempfile.TemporaryDirectory()`.
2. For every device in `context.devices`, resolve its running-config text via
   the existing `running_config` content source
   (`workflow_steps/common/content_resolver.py`, the same path `store-artifact`
   already uses) and `artifact_service.read_content(artifact_ref.artifact_id)`,
   then write it to `<tmpdir>/configs/<device_id>.cfg`. The filename is
   cosmetic — **Batfish derives each node's real name from the config text's
   own hostname line, not the filename** (verified: a file whose content
   declares `hostname R1` shows up in every answer table as node `r1`,
   regardless of what the file itself was named). Devices with no
   `running_config_ref` yet (upstream `get-device-configs` failed/skipped
   them) are skipped with a per-device warning, not a whole-step failure.
3. Call `bf.set_network(network_name)` (creates it if absent) then
   `bf.init_snapshot(tmpdir, name=snapshot_name, overwrite=True)`.
4. Store one consolidated key, `WorkflowContext.metadata["batfish"] =
   {"host": ..., "port": ..., "network": network_name, "snapshot":
   snapshot_name}`, so the three query steps downstream in the same run have
   everything they need — including the connection itself — without each
   needing their own `batfish_source_id` config. This mirrors the
   "define once, reuse across every step" shape `pyats_testbed` already
   established for pyATS (see `doc/PYATS_INTEGRATION.md` → "Add Testbed"),
   just via `metadata` instead of a per-device `attribute_bags` entry, since
   the value is workflow-scoped, not per-device.
5. Run the retention sweep from above.
6. Delete the temp directory (`TemporaryDirectory` context manager handles
   this even on error).

**Fan-out rule: not fan-out-safe in live mode, same class as
`store-artifact`/git steps.** In `live` mode this step needs every device's
config together in one upload, so it must run **after a Fan In** in a
fanned-out workflow — never inside the fanned-out branch, for the same
reason `git-pull`/`store-artifact` must (see
`doc/HOWTO_BUILD_WORKFLOWS.md` → "Every Git step sits after the Fan In").
`requires: [identity]`, `produces: []` in `registry.yaml` (mirrors
`store-artifact`'s own declaration — the per-device `running_config`
precondition is checked at runtime, not declared as a canvas-level
capability requirement, exactly like `store-artifact` already does for its
own `content_source` choices). `git` mode reads nothing from
`context.devices` at all, so this specific race doesn't apply to it — but
`requires: [identity]` is not made conditional on `config_source` in
`registry.yaml` (see below), so an upstream node is still needed in both
modes for canvas-wiring reasons.

## Config source: live vs. git

Production networks with hundreds or thousands of devices can't feasibly
have every workflow that wants to ask Batfish a question also live-SSH the
entire fleet in the same run just to build a snapshot — and Batfish has no
partial/incremental snapshot update anyway, so every refresh is a full
re-upload regardless of where the configs come from. `config_source` on
`batfish-init-snapshot` offers two ways to build that re-upload:

- **`live`** (default, unchanged from the original design): reads
  `context.devices`' running-configs, pulled live during this run. The
  right choice for ad-hoc/lab debugging against a handful of devices
  selected on this same canvas.
- **`git`**: reads already-collected configs from a `GitRepository` (e.g.
  the repository a separate, existing nightly config-backup workflow
  already writes into) — no live device contact at all. Config fields:
  `git_repository_id` (the repository to read from), `base_path` (directory
  inside the repository to search from, blank = repo root), and
  `glob_pattern` (a glob — supporting `**` recursive segments — matched
  against files under `base_path`).

  `backend/workflow_steps/batfish_init_snapshot/git_source.py`'s
  `collect_git_source_files` resolves `base_path` with the same
  escape-guard pattern as `read_config/executor.py::_resolve_target_path`,
  then walks matches via `pathlib.Path.glob(glob_pattern)` — which natively
  understands `**` as a recursive segment, so the *pattern itself* (not any
  special-cased logic) decides whether devices are told apart by filename
  suffix (`**/*.running.cfg`, e.g. running vs. startup configs saved as
  `{device}.running.cfg` / `{device}.startup.cfg`) or by directory
  (`configs/running/**/*.cfg`). Matches are capped at
  `MAX_GIT_SOURCE_FILES` (20,000 — sized for a full production fleet, not
  borrowed from the much smaller cap `services/git/content_search_service.py`
  uses for its own, unrelated interactive-search feature) and skip anything
  under `.git/`, oversized files, and symlinks that resolve outside the
  repository. **Zero matches, or more matches than the cap, is a hard
  failure (`ValueError`), not a silent truncation or empty upload** — a
  silently incomplete production snapshot is a worse failure mode than a
  loud one. Matched files are copied into the snapshot's `configs/`
  directory with an index-prefixed name (`00001-<basename>`, etc.) —
  filenames stay cosmetic to Batfish, so flattening away the original
  directory structure is safe (see "Building the snapshot directory" above).

  This mode never reads `context.devices` — not even to check it's
  empty — so pair it with an upstream `batfish-start-run` step (see
  "Get from Batfish" below) rather than a real device-selection step when
  the workflow selects no devices of its own. Left unconfigured with no
  prior snapshot metadata on the run, that step is a pure no-op placeholder
  (see "Get from Batfish" for its full three-way behavior) — it does not
  contact Batfish itself.

**The intended production pattern**: a workflow scheduled nightly (via
`/schedules`) runs `batfish-start-run` → `batfish-init-snapshot`
(`config_source: git`, `network_name` set to a stable name such as
`manus-production`) against the git-mirrored config backups — no live
device contact, decoupled from any interactive/ad-hoc workflow. Separate,
unrelated query workflows then target that same standing network directly
(see "Why `WorkflowContext.metadata`, not a new `Capability`" below) without
needing their own Init step or sharing the refresh workflow's `workflow_id`
— including via a `Get from Batfish` step targeting that network directly
with `batfish_source_id`/`network` set, to populate real devices for a
Validate Facts/Extract Facts run with no Init step of its own.

**Why `WorkflowContext.metadata`, not a new `Capability`.** `Capability`
(`models/workflow_context.py`) is a closed enum describing properties of a
single `DeviceContext` — it has no notion of a workflow-level fact like "a
Batfish snapshot exists for this run." Adding one purely to gate three
downstream steps would be modeling a per-run fact as if it were per-device
data, which the data model deliberately keeps separate (see
`doc/ARCHITECTURAL_OVERVIEW.md` → "Per-device data isolation"). Instead, the
three query steps below just declare `requires: [identity]` (a weak
precondition ensuring they're wired downstream of an inventory step, same
role it plays for git steps) and read `context.metadata["batfish"]`
themselves at runtime via a small shared helper
(`workflow_steps/common/batfish_context.py`, mirroring `pyats_batch.py`'s
role as shared logic for a family of steps), raising a `ValueError` ("no
Batfish snapshot found — add an Init Batfish Snapshot step upstream") if
it's missing. Because that one metadata entry carries the connection too,
none of the three query steps need their own `batfish_source_id` config to
use this default path — they only need one when opting into the direct
network-targeting bypass described below. One
consequence worth calling out explicitly for whoever builds this: because
`metadata` merges **first-child-wins** under fan-out
(`ARCHITECTURAL_OVERVIEW.md` again), `batfish-init-snapshot` must never run
*inside* a fanned-out branch — not only because of the shared-upload race
covered above, but because a metadata write there would silently lose to
whichever child fan-out picked as "first" once results are merged back.
Running it post-Fan-In (single writer, single segment) avoids this
entirely — one more reason to enforce that placement rather than merely
document it.

**Bypassing metadata: querying a network directly.** The three query steps
also accept optional `batfish_source_id`/`network`(/`snapshot`) config
fields. When both `batfish_source_id` and `network` are set, the step
resolves that connection/network directly via
`workflow_steps.common.batfish_context.resolve_batfish_snapshot_ref` and
**ignores this run's metadata entirely, even if present** — explicit step
config always wins. `snapshot` defaults to the most recent snapshot in that
network (sorted by `metadata.creationTimestamp`, same sort used by the
retention sweep) when left blank, and raises `ValueError` if the network has
no snapshots at all. This is what lets a query workflow with no Init step
of its own target a standing, independently-refreshed network — the actual
mechanism behind the production pattern described in "Config source: live
vs. git" above.

## Configuring a source

Mirrors `services/pyats/source_config_service.py` /
`services/ise/source_config_service.py`, minus the credential half — there is
no vault credential to select because the coordinator has no auth. Non-secret
config (`host`, `port` default `9996` — see the single-port finding above)
lives under `sources.batfish.<id>` in the generic `settings` table via
`SettingsRepository`, same as every other source. No `verify_ssl`/TLS
setting — `pybatfish` talks plain TCP to the coordinator (`ssl=False` is the
`Session` default and nothing in this integration changes that), matching
the container's own no-TLS setup on the internal `backend` Docker network.

`POST /api/sources/batfish/{source_id}/test-connection` should do a
single-stage check — there's no separate "process is up" vs "functionally
working" distinction like pyATS's `/health` vs `/health/pyats`, since
`pybatfish` has no lightweight liveness probe of its own. The simplest real
check: `Session(host=...).list_networks()` — succeeds only if the
coordinator actually answers pybatfish's RPC protocol, fails clearly
(connection refused/timeout) if the container is down or unreachable.
Response shape is `{success, message}`, same convention as every other
source's test-connection endpoint.

**Which host to use depends on where the backend process itself runs** —
exactly the same two-case split documented in `docker/batfish/README.md` and
already hit once by pyATS: native-backend dev
(`python start.py` / `python scripts/run_worker_dev.py`) uses
`host=127.0.0.1`; a fully containerized backend uses `host=batfish`. The
loopback case needs `ALLOW_LOOPBACK_SOURCE_URLS=true` in `backend/.env` if
the source URL validation path treats a bare hostname the same way it treats
pyATS's/OpenBao's loopback URLs — verify `validate_outbound_http_url`'s
behavior against a non-HTTP `host:port` pair specifically, since Batfish's
source config isn't a URL in the same shape as every other source (see "Open
items" below). **Remember to restart the Hatchet worker** after changing the
source config or this env var, for the same reason documented in the pyATS
doc's "Configuring a source" section — the worker only re-reads config at its
own process startup.

## Security notes

- The `batfish` container's coordinator has **no authentication of its
  own** — anyone who can reach ports 9996/9997 can create, read, or delete
  any network/snapshot. `docker/batfish/docker-compose.yaml` already binds
  the published ports to `127.0.0.1` only; this integration must never
  change that or add a way to point a Batfish source at a non-local/
  non-`backend`-network host without equivalent protection.
- Device configs — potentially containing secrets (enable passwords, SNMP
  community strings, pre-shared keys) if not scrubbed by the collecting
  step — are uploaded into the Batfish container's `/data` volume as part of
  every snapshot. This is the same trust boundary already accepted for the
  git-mirrored config backups (`doc/ARCHITECTURAL_OVERVIEW.md` → "Version-
  controlled workflows"); nothing here widens it, but it's worth recording
  explicitly in `doc/SECURITY-NOTES.md` alongside the other accepted-risk
  entries once this ships, since a *new* place now holds a copy of raw
  device configs.
- Batfish answers (routing tables, ACL contents, reachable paths) are
  themselves sensitive — they describe exactly how to reach or bypass
  network controls. `sources:batfish` read access should be scoped by
  RBAC the same as `sources:pyats`/`sources:ise`, and query-step results
  should be treated with the same care as raw config content when stored as
  artifacts.

## Workflow steps

All eleven steps live under `palette_category: batfish` (a new palette
category — see "Frontend: category gating" below for why it's hidden by
default).

### Get from Batfish (`batfish-start-run`)

`requires: []`, `produces: [identity]`, single `success` outcome. Started life
as a pure placeholder (hence the `id`, kept unchanged for backward
compatibility with saved workflows) and grew into a real device-listing step —
it now has **three auto-detected behaviors**, chosen by what's resolvable at
run time, with no mode/toggle config field:

1. **Nothing configured, and no run metadata resolvable**
   (`context.metadata["batfish"]` absent, and neither `batfish_source_id` nor
   `network` set) — the original, unchanged placeholder behavior:
   `context.devices` is cleared to `{}` and `success` fires, with **zero
   Batfish calls**. This is what lets a `git`-mode `batfish-init-snapshot`
   step (which needs no real devices at all) still be wired in on the canvas:
   `batfish-init-snapshot` keeps `requires: [identity]` unchanged in both
   config-source modes (see "Config source: live vs. git" above), and the
   canvas's own connection-validity rule
   (`workflow-canvas.tsx::isValidConnection`) requires some upstream node
   that `produces: [identity]` before it will accept an edge into a
   `requires: [identity]` step, regardless of what that upstream step's
   device output actually contains.
2. **This run's own `Init Batfish Snapshot` already ran**
   (`context.metadata["batfish"]` present) — resolves that snapshot, queries
   Batfish's `nodeProperties` question for every matching node, and
   **replaces** `context.devices` with one device per distinct node
   (deduplicated) — the same "always replace, never merge" contract other
   `Get from X` device-selection steps use.
3. **`batfish_source_id` + `network` both configured** — same device
   population, but targeting a standing network directly (the "intended
   production pattern" above), bypassing this run's metadata entirely. Same
   `resolve_batfish_snapshot_ref` direct-targeting bypass the three query
   steps and Validate/Extract Facts already use, including its "explicit
   config always wins" precedence.

**Device identity, and why `batfish-routing-table` isn't touched.** The
synthesized `DeviceContext`s use the exact same shape as
`batfish-routing-table`'s own `devices` outcome (`id=name=hostname=<node>`,
`source="batfish"`, `capabilities={IDENTITY}`, `status=OK`) — a
Batfish-sourced identity, not a rehydration of real inventory data, with the
same lowercased-hostname caveat (see "Batfish Routing Table" below) if you
chain into `Get Nautobot Attributes` afterward. This dedup logic lives once,
as `workflow_steps.common.batfish_context.devices_from_nodes`, used only by
this step — `batfish-routing-table`'s own inline copy is deliberately left
as-is, not refactored onto the shared helper, so this rework carries zero
behavior risk for that step.

**A workflow may legitimately contain two instances of this step**: one
before `Init Batfish Snapshot` (case 1, placeholder role — satisfies the
canvas wiring rule) and one after it (case 2, real device population from the
snapshot that step just built), e.g.:
```
Get from Batfish → Init Batfish Snapshot (config_source: git) → Get from Batfish → Validate Facts
```
This is what makes `facts_source: git` on Validate Facts usable without a
live device-selection step anywhere in the workflow — the second `Get from
Batfish` instance supplies real, Batfish-sourced devices for Validate Facts
to check, resolving the original gap that motivated this step's rework (an
empty device list previously meant Validate Facts always returned empty
match/mismatch results, even though `git`-mode Init Snapshot and Extract
Facts both worked fine against the same snapshot).

**Implementation note on why the precondition is checked explicitly, not via
`except ValueError`.** `resolve_batfish_snapshot_ref` (and the
`resolve_batfish_snapshot` it falls back to) always raises `ValueError` when
nothing is resolvable — it never returns a falsy sentinel. The executor
replicates that same "is anything configured at all" precondition itself
*before* calling it, so a case-1 no-op is distinguishable from a genuine
misconfiguration (malformed metadata, a nonexistent network, a network with
no snapshots) — the latter must still propagate as a real step failure, not
be silently swallowed into "no devices."

Config: `nodes_filter: str` (optional NodeSpecifier restricting which nodes
are listed; blank lists every node — unlike Extract Facts, this step has no
`context.devices` of its own to default to, since it *is* the device
source), plus the same `batfish_source_id`/`network`/`snapshot` direct-target
fields as the query/fact steps below.

### Init Batfish Snapshot (`batfish-init-snapshot`)

`requires: [identity]`, `produces: []`. Builds a fresh Batfish snapshot and
stores its location (and connection) in
`WorkflowContext.metadata["batfish"]` — see "Snapshot lifecycle" and
"Config source: live vs. git" above for the full mechanics (directory
assembly, naming, retention, the fan-out placement rule, live vs. git).
Config: `batfish_source_id: str` (required — which configured Batfish
source to use), `retain_snapshots: int` (default `5`), `network_name: str`
(optional override, default derives from `workflow_id`), `config_source:
"live" | "git"` (default `"live"`), and, when `config_source` is `"git"`:
`git_repository_id: int` (required), `base_path: str` (optional),
`glob_pattern: str` (required). Snapshot naming uses `run.id` (the
`WorkflowRun` ORM object's autoincrement int, passed into every executor
already) — not `context.run_id`, which is `run.uuid` and not needed here.

This is the one step in this integration with any real I/O cost/risk (it
touches the shared Batfish network for the whole workflow) — the steps below
are pure reads against an already-initialized snapshot.

### Extract Facts (`batfish-extract-facts`)

`requires: [identity]`, `produces: [parsed]`, `outcomes: [success]`. Wraps
`Session.extract_facts(nodes="/.*/", output_directory=None, snapshot=None)`
— retrieves the facts Batfish parsed for a set of nodes, with no expected
values to compare against (see Validate Facts below for that). Unlike that
step, `nodes` here is a plain `NodeSpecifier` string (a bare comma-joined
name union, or a `/regex/`-delimited alternation) and the call returns the
facts dict directly — no temp directory needed.

**`nodes_filter` defaults to this run's own devices, not Batfish's own
`"/.*/"` default.** Left blank, the step builds a comma-joined, lowercased
union from `context.devices` so an unconfigured step scopes to the
workflow's own selected devices rather than every node in the network; set
it to `/.*/` explicitly to extract everything. **Must be comma-joined, not
`|`-joined** — confirmed against a live coordinator that a bare
(non-`/regex/`-delimited) nodeSpec containing `|` is parsed as one literal
node name rather than an alternation, so `"lab|lab-2"` matches nothing even
when both nodes exist, while `"lab,lab-2"` matches both. A prior `|`-joined
default silently produced a zero-node filter — and therefore zero extracted
facts and a `post_step_guard` failure (`produces={parsed}` unmet) — for
every multi-device run.

**Enriches every device directly, unlike the three query steps below.**
`device.parsed[output_key] = {"parsed": <node's facts>, "error": None}` for
a node Batfish returned, or `{"parsed": None, "error": "no facts found for
node '<name>' in this Batfish snapshot"}` otherwise — the exact non-fatal
`{"parsed", "error"}` shape `run-command`'s TextFSM/Genie parsers use (see
"Normalized command-output parsing" in `doc/WORKFLOW-STEPS.md`), one level
shallower since extraction isn't command-scoped. This is what lets a
downstream Render Jinja Template step read
`{{ parsed.batfish_extract_facts.parsed.TACACS.TACACS_Servers }}` per
device, in addition to the one workflow-level artifact (`kind:
"batfish_result"`, `question: "extractFacts"`) covering every extracted
node.

**Direct network targeting.** Same optional `batfish_source_id`/`network`/
`snapshot` config fields as the three query steps below.

### Validate Facts (`batfish-validate-facts`)

`requires: [identity]`, `produces: [parsed]`, `outcomes: [match, mismatch,
failure]`. Wraps `Session.validate_facts(expected_facts, snapshot=None)` —
verified directly against the installed `pybatfish` source (not assumed from
its docstring alone), which surfaced three implementation-critical facts:

1. **`expected_facts` is a directory path, not YAML text or a single
   file.** `Session.validate_facts` calls `pybatfish.client._facts.load_facts`,
   which `os.listdir()`s every file in that directory and merges their
   `nodes:` maps. This step builds that directory itself in a
   `tempfile.TemporaryDirectory()` — one YAML file per contributing device —
   the exact same pattern `batfish-init-snapshot` already uses for its config
   upload.
2. **Node-name lookup in the diff is a plain dict key** (`actual_facts.get(node,
   {})`), not a case-insensitive nodeSpec match like `routes`/`reachability`/
   `testFilters` use. Batfish canonicalizes hostnames to lowercase, so this
   step always lowercases the node key it writes — a rendered YAML fragment
   whose node key doesn't match the device's own name (case-insensitively)
   fails that device with `node_key_mismatch` rather than silently never
   checking it.
3. **The version gotcha.** `Session.validate_facts` internally fetches actual
   facts via `get_facts()`, which always stamps
   `version: "batfish_v0"` (`pybatfish.client._facts.BATFISH_FACT_VERSION`).
   Its diff logic short-circuits entirely on a version mismatch: `if
   expected_version != actual_version: return {n: {"Version": {...}} for n in
   expected_facts}` — so if the expected-facts file carried any other literal
   version string (e.g. the `version: '1.0'` convention from Batfish's own
   public docs/notebooks — exactly what an operator would naturally write),
   *every* node would report as mismatched purely on the version field,
   masking real results entirely. This step always drops any `version` key
   from the merged file before writing it, letting `load_facts()`'s own
   "assume latest version if none is specified" default apply correctly.

**Three ways to supply expected facts per device** (`facts_source` config,
default `rendered_yaml`):

- **`rendered_yaml`** — reads an upstream Render Jinja Template step's output
  via `workflow_steps.common.content_resolver.list_exportable_content(...,
  content_source="rendered_template", source_step_node_id=...)`, the same
  mechanism `store-artifact` and `batfish-init-snapshot` already use to pull
  an upstream step's rendered content. The rendered YAML must have a
  top-level `nodes` mapping keyed by the device's own name. Intended
  workflow: Get from Nautobot → Get Nautobot Attributes → Render Jinja
  Template (renders the expected-facts YAML per device from Nautobot
  config-context/custom-field data) → Validate Facts.
- **`field`** — builds a single `{fact_key: fact_value}` fact inline, per
  device, with no upstream render step needed (`fact_key` one of the
  supported Batfish fact keys — `Hostname`, `TACACS_Servers`, `NTP_Servers`,
  etc., see the Help tab for the full ~40-key list; `fact_value` a Jinja
  template rendered per device via `workflow_steps.common.jinja_render`).
  `fact_value`'s rendered text is `yaml.safe_load`-ed so one text field can
  represent either a scalar (`10.0.0.1`) or a YAML/JSON list
  (`[10.0.0.1, 10.0.0.2]`) — useful for a quick single-value check like "does
  this device have the right TACACS server" without any rendering step at
  all.
- **`git`** — reads expected-facts YAML files from a `GitRepository`
  (`git_repository_id`, `base_path`, `glob_pattern` — identical field names
  and resolution to `batfish-init-snapshot`'s own `config_source: git`,
  reusing `workflow_steps.batfish_init_snapshot.git_source
  .collect_git_source_files` as-is). Unlike that step's git mode, which
  *copies* raw config files into a Batfish snapshot upload, this one
  *parses* every matched file as YAML — each must have the same top-level
  `nodes` mapping shape as `rendered_yaml` — and merges all of them, once,
  up front (before any device is checked), into one
  node-name(lowercased)-to-fields corpus; later files, in
  `collect_git_source_files`'s own sorted-path order, win on a node-key
  collision. A file that fails to parse, or lacks a top-level `nodes`
  mapping, is a hard step failure (`ValueError` naming the file), not a
  skip — same "loud failure over silent partial data" posture
  `collect_git_source_files` already established for its own zero-match/
  cap-exceeded cases (see "Open items" below). Useful when expected facts
  are authored/maintained as data files in the same repository a
  config-backup or intended-state job already writes into, instead of being
  rendered per-device from Nautobot at run time.

**Failure granularity differs by source.** A `git`-source config error
(missing `git_repository_id`/`glob_pattern`) or a malformed matched file
fails the *whole step* before any device is evaluated — there is no partial
corpus. A device simply missing from the resolved corpus (or, for
`rendered_yaml`, a device with no resolvable artifact) still fails only
*that device*, with `node_key_mismatch`/`missing_content` on its own
`DeviceError`, exactly as today — other devices in the same run are
unaffected.

**Not fan-out sensitive, unlike `batfish-init-snapshot`.** Both
`validate_facts` and `extract_facts` are pure reads against an
already-built snapshot — nothing here mutates shared Batfish state — so
unlike the snapshot-build step, this one has no Fan-In placement
requirement.

**One Batfish call per batch, not per device.** `validate_facts()`
internally re-fetches actual facts for *every* node in the snapshot on each
call (not just the ones being checked), so calling it once per device would
be wasteful. Every device's one-node fragment is merged into a single
temp-directory upload and validated in one call; the returned per-node
mismatch map is then used to partition devices.

**Per-device result.** A contributing device whose node name appears in the
returned mismatch map routes to `mismatch` (with the mismatched fields
written to `device.parsed["{node_id}.<output_key>"]["parsed"]`); one with no
entry routes to `match` (empty dict at the same path). A device whose
expected facts couldn't be resolved (missing rendered content, a Jinja
render error, or a node-key mismatch) routes to `failure` with a
`DeviceError` recorded — mirroring `compare-pyats-snapshot`'s
`match`/`mismatch`/`failure` bucket model, the closest existing precedent
for "same check, once per device, three-way branch." If *zero* devices
contribute a valid fragment, the Batfish call is skipped entirely and every
device lands on `failure`. The full per-batch mismatch map is also stored as
one workflow-level artifact plus a `context.metadata[f"{node_id}.
{output_key}"]` summary (`kind: "batfish_result"`, `question:
"validateFacts"`), the same convention the three query steps below use.

**Direct network targeting.** Same optional `batfish_source_id`/`network`/
`snapshot` config fields as the three query steps below.

### Batfish Routing Table (`batfish-routing-table`)

`requires: [identity]`, `produces: []`. Wraps `bf.q.routes(...)` — confirmed
against a real two-router snapshot, no required parameters, returns one row
per `(node, VRF, network)` route with columns including `Next_Hop`,
`Protocol`, `Metric`, `Admin_Distance`, `Tag`. Config maps directly onto
`routes()`'s own parameters (all optional — an empty config returns every
route on every node):

```python
bf.q.routes(
    nodes=config.get("nodes"),              # nodeSpec, e.g. "R1" (case-insensitive)
    network=config.get("network_prefix"),   # prefix, e.g. "192.168.1.0/24"
    prefixMatchType=config.get("prefix_match_type"),  # EXACT (default) | LONGEST_PREFIX_MATCH | LONGER_PREFIXES | SHORTER_PREFIXES
    protocols=config.get("protocols"),      # routingProtocolSpec, e.g. "static", "bgp"
    vrfs=config.get("vrfs"),
    rib=config.get("rib"),                  # main (default) | bgp | evpn
).answer().frame()
```

**Naming collision, found and fixed during implementation:** pybatfish's own
`routes()` question has a parameter literally named `network` (the
route-prefix filter above). `BatfishService.routes()` — the async wrapper
every step actually calls, not the raw `bf.q.routes()` shown above — takes
the *Batfish* network name as `batfish_network` specifically to avoid
colliding with that when the step's `network_prefix` config value gets
forwarded through `**params`. The step's own config field is named
`network_prefix` for exactly the same reason — `network` alone would be
ambiguous between "which Batfish network" and "which route prefix."

**Result storage: workflow-level, not per-device — deliberately NOT wired
into `store-artifact`/`content_resolver.py` in v1.** Every existing
`artifact_service.store()` call site in this codebase is per-device (one
artifact per device, keyed by that device's `device_id`) — there is no
established convention for a single workflow-scoped artifact, and
`content_resolver.py`'s contract takes one `device: DeviceContext` at a time
by design. A Batfish routing-table result is inherently one table covering
every queried node, not naturally splittable per device. Rather than force
one of two awkward shapes (fan the same artifact out redundantly to every
device's `parsed`, or extend `content_resolver.py`'s per-device contract to
also handle workflow-level content — a real change to a shared file every
existing step depends on), this step stores the result as one artifact via
`artifact_service.store(device_id=f"batfish-{node_id}", ...)` (a sentinel,
not a real device — confirmed safe: `device_id` is stored as descriptive
metadata alongside the artifact, e.g. for filesystem backends, not used to
build the storage path) and puts the `ArtifactRef` plus a small inline
summary (row count) directly in
`WorkflowContext.metadata[f"{node_id}.{output_key}"]` (`output_key` is a
step config field, default `batfish_routes`/`batfish_path_check`/
`batfish_acl_check` per step). One more `run_id` distinction worth stating
explicitly since it's easy to get backwards: `artifact_service.store()`'s
`run_id` parameter is typed `str` and takes `context.run_id` (confirmed
against `get_pyats_snapshot/executor.py`'s real precedent) — this is
*unrelated* to the `run.id` (int) used for Batfish snapshot naming above;
mixing the two up is a real `pyright` error (`reportArgumentType`), not just
a style nit, since `run.id` is an `int`.
Exporting a Batfish result via `store-artifact` is deferred — see "Open
items" below — rather than casually extending a shared, heavily-used
contract as a side effect of this integration.

**Direct network targeting.** Optional `batfish_source_id: str`,
`network: str`, `snapshot: str` config fields let this step bypass
`context.metadata["batfish"]` and query any network directly — see
"Bypassing metadata: querying a network directly" above.

**`devices` outcome: turning routed nodes into a device list.** Alongside
`success` (unchanged — it still just passes the incoming `context.devices`
through untouched), this step always returns a second outcome, `devices`,
built by deduplicating the answer's `Node` column and constructing one
minimal `DeviceContext` per unique node (`id=name=hostname=node`,
`source="batfish"`, `capabilities={IDENTITY}`, `status=OK`). Emitted
unconditionally, even when `rows` is empty (an empty `devices` dict) — the
same "0 is a valid, non-error answer" reasoning `success`'s row count
already follows, so the branch fires predictably rather than being silently
skipped on a 0-match run. `outcomes: [success, devices]` in `registry.yaml`;
no `produces` change was needed to make `devices` canvas-wireable into a
step requiring `identity` — `batfish-routing-table`'s own `requires:
[identity]` already guarantees `IDENTITY` is present on input, and the
canvas's capability-provides computation
(`frontend/.../utils/capability-graph.ts::applyStep`) is `input capabilities
∪ node.produces`, so both outcomes already advertise `IDENTITY` regardless.

This is deliberately a *new*, Batfish-sourced identity, not a rehydration of
whatever device fed the snapshot — in live-mode snapshot building, configs
are uploaded under an opaque UUID filename (see "Building the snapshot
directory" above), so a `Node` string has no reliable link back to a real
Nautobot device UUID. The intended composition is to chain into the
already-existing `get-nautobot-attributes` step (no changes needed there):
wire `devices` → `Get Nautobot Attributes`, whose own `success` outcome
carries only the nodes it could resolve by name (real Nautobot attributes
attached via `attribute_bags["nautobot"]`), while anything it couldn't
resolve lands on its `failure` outcome instead of continuing downstream with
fake identity — this is the "drop devices Nautobot doesn't recognize"
behavior, reused as-is rather than reimplemented here.

**RESOLVED: name matching case-sensitivity, opt-in.**
`resolve_nautobot_device_id` (`workflow_steps/common/nautobot_resolve.py`)
now accepts `case_insensitive: bool`, switching the name lookup to Nautobot's
`name__ie` GraphQL filter. `Get Nautobot Attributes` exposes this as a step
config field, `case_insensitive_lookup` (default `False` —
`workflow_steps/get_nautobot_attributes/config.py`/`executor.py`). Since
Batfish always lowercases parsed node hostnames (see "Node-name case
sensitivity" under "Open items" below), **this option must be turned on** on
any `Get Nautobot Attributes` step downstream of Batfish Routing Table's
`devices` outcome — left at its `False` default, a Nautobot device named with
any uppercase letters (e.g. `R1`) still fails to resolve by name purely due to
casing and lands on the `failure` outcome even though it genuinely exists.

### Batfish Node Properties (`batfish-node-properties`)

**Shares its result-storage/audit/enrichment engine with Batfish Interface
Properties.** Everything past "fetch this question's rows" (the artifact +
`context.metadata` write, `route_empty_to_devices`/`empty_match_mode`, and
per-device enrichment on the `devices` outcome) lives once in
`workflow_steps/common/batfish_properties.py`
(`PropertyQuestionSpec`/`build_property_outcomes`), not duplicated per step —
this step's executor is a thin caller that only builds its own
`query_node_properties(...)` call and passes the result in. This is also the
extension point for a future property-family question (e.g. a verified
`bgpProcessConfiguration` step): a new `PropertyQuestionSpec`, but only once
its row-identity shape is confirmed against a live coordinator the same way
`interfaceProperties`' nested shape was (see that step's section below) — see
"Open items" for the current state of that.

`requires: [identity]`, `produces: []`, `outcomes: [success, devices]`. Wraps
`bf.q.nodeProperties(...)` — the same question `Get from Batfish` already
uses internally to synthesize a device list, but exposed directly here with
its `properties` filter, which `Get from Batfish` deliberately never passes
(it only needs node identity for dedup, not fact contents):

```python
bf.q.nodeProperties(
    nodes=config.get("nodes"),            # nodeSpec, e.g. "R1"
    properties=config.get("properties"),  # NodePropertySpec, e.g. "TACACS_Servers"
).answer().frame()
```

Both filters are optional — an empty config returns Batfish's own default
column set for every node. `properties` is a comma-separated
NodePropertySpec; valid names are the same ~40 keys `Validate Facts`'s
`field` mode and `Extract Facts` recognize (`frontend/.../shared/
batfish-fact-keys.ts::BATFISH_FACT_KEYS`) — confirmed directly against the
installed `pybatfish` source: `pybatfish.client._facts.get_facts()` calls
`session.q.nodeProperties()` with no `properties` filter and reorganizes a
subset of its default columns via `NODE_PROPERTIES_REORG` (e.g.
`TACACS_Servers`/`TACACS_Source_Interface` → a `TACACS` fact group); the
columns that dict doesn't rename (`Hostname`, `Interfaces`, `VRFs`,
`IP_Access_Lists`, etc.) pass through unchanged. So `BATFISH_FACT_KEYS` is,
in practice, the full column set this question can return — safe to reuse
as click-to-add suggestions in the config panel rather than inventing a
second list.

**Use case: does a device have a specific TACACS server configured?** Set
`nodes: R1`, `properties: TACACS_Servers`, run the step, and read the one
resulting row from the stored artifact (or chain into a downstream step —
e.g. Render Jinja Template or Compare Data — to test the value
programmatically). This step reports the *actual* parsed value; it does not
compare against an expected one itself. For an outright
match/mismatch assertion per device instead (e.g. "every device's
`TACACS_Servers` must equal exactly this list"), use `batfish-validate-facts`
with `facts_source: field` — that step already builds exactly this
`{fact_key: fact_value}` shape per device and buckets devices into
`match`/`mismatch`/`failure`. Node Properties is the right tool for
open-ended inspection/export across a fleet (e.g. auditing which TACACS
servers are actually configured everywhere); Validate Facts is the right
tool for asserting one expected answer.

**Result storage: same artifact shape as Batfish Routing Table, but
`success` and `devices` diverge in what they carry.** One workflow-level
JSON artifact (`kind: "batfish_result"`, `question: "nodeProperties"`) plus
a `context.metadata[f"{node_id}.{output_key}"]` summary (`output_key`
default `batfish_node_properties`) — not per-device, same as Routing Table's
"Result storage" above. `success` passes `context` straight through
unchanged (`devices` included, if any were already present upstream) plus
this shared metadata — a workflow that just wants the full-batch artifact
for export/audit uses this outcome and ignores `devices` entirely.

**`devices` outcome: per-device enrichment, not identity-only.** Each
`DeviceContext` in `devices` is built by `_enrich_devices` (layered on top
of the shared `workflow_steps.common.batfish_context.devices_from_nodes`
helper via `device.model_copy`, the same `device.parsed[...] =
{"parsed": ..., "error": None}` idiom `batfish-extract-facts`/
`batfish-validate-facts` already use) and carries **only that node's own
row** at `device.parsed[f"{node_id}.{output_key}"]`. This was not the
original behavior — `devices` originally carried identity only (no
`parsed` at all), with the actual property values living solely in the one
shared, un-partitioned artifact above. That meant a per-device consumer
downstream of `devices` (Log Attributes, a device-detail dialog, a Render
Jinja Template keyed by `parsed`) had nothing device-specific to read: the
only place the data lived showed the *same* full, all-nodes answer
regardless of which device you were looking at — e.g. opening device
`lab-2`'s detail dialog after `Get from Batfish → Batfish Node Properties →
devices` showed `lab`'s TACACS data too, since the "Batfish result" panel
there (`device-detail-dialog.tsx`) just renders whatever's in
`context.metadata`, not anything scoped to `lab-2`. Fixed by enriching
`devices` per device while deliberately leaving `success` as a pure
passthrough — a workflow chaining into per-device tooling should use
`devices`; one that only wants the full-batch artifact keeps using
`success`, unaffected by this change. *Which* nodes land in `devices` (and,
now, which row each one is enriched with) depends on
`route_empty_to_devices`, below.

**`route_empty_to_devices` (config field, default `false`) — an empty
result is not a missing row.** A node with no TACACS server configured
doesn't get *omitted* from the `nodeProperties` answer — it comes back as
`{"Node": "lab-2", "TACACS_Servers": []}`, a normal row with an empty value.
Left disabled, `devices` carries every matched node regardless of value
(today's behavior, unchanged). Enabled, `devices` is filtered down to only
the nodes whose `properties` values are empty (`_is_empty_value`: `None`, a
blank/whitespace-only string, or an empty list/dict/tuple/set) — turning
this step from a plain lookup into an audit ("which devices are missing a
TACACS server"). **Requires `properties` to be set explicitly** — raises
`ValueError` otherwise, since with no filter Batfish returns dozens of
unrelated default columns and "empty" has no single well-defined meaning
across all of them. This check runs entirely in the executor, after the one
Batfish call — no extra round-trip.

**`empty_match_mode` (`"any"` default | `"all"`) — only load-bearing with
more than one `properties` entry.** A node can have some requested
properties empty and others not. `"any"` flags it if *at least one*
requested property is empty (the stricter read: a device must have *every*
requested property present to be excluded — the natural mode when
`properties` lists several fields that must all be configured, e.g. both
`TACACS_Servers` and `TACACS_Source_Interface`). `"all"` flags it only if
*every* requested property is empty (looser — a device with at least one of
several alternative properties set is considered fine). With a single
`properties` entry the two modes are equivalent, so the frontend config
panel only shows this control once more than one property is listed.

**Direct network targeting.** Same optional `batfish_source_id`/`network`/
`snapshot` config fields as the other query/fact steps.

### Batfish Interface Properties (`batfish-interface-properties`)

Shares the same `workflow_steps/common/batfish_properties.py` engine as
Batfish Node Properties above (result storage, `route_empty_to_devices`/
`empty_match_mode`, per-device enrichment) — see that step's section for the
full reasoning. This step's own `PropertyQuestionSpec` is the one place its
`Interface`-nested row shape (vs. `nodeProperties`' plain `Node` string) is
handled.

`requires: [identity]`, `produces: []`, `outcomes: [success, devices]`. Wraps
`bf.q.interfaceProperties(...)` — a genuinely different question from
`nodeProperties`, not a variant of it:

```python
bf.q.interfaceProperties(
    nodes=config.get("nodes"),            # nodeSpec, e.g. "R1"
    interfaces=config.get("interfaces"),  # InterfacesSpecifier, e.g. "GigabitEthernet0/1"
    properties=config.get("properties"),  # InterfacePropertySpec, e.g. "Description"
).answer().frame()
```

**Different result shape from Node Properties — one row per (node,
interface), not one row per node.** Node Properties' rows carry a plain
`Node` string column; `interfaceProperties`' rows carry an `Interface`
column instead, whose value is pybatfish's own `Interface` datamodel object
(`hostname` + `interface`). Confirmed **empirically** (not merely assumed
from the datamodel's `attr.s` definition) by round-tripping a real
`Interface` instance through the exact `pandas.DataFrame.to_json(orient=
"records")` call `BatfishService._answer` already uses for every question:
it serializes to a nested `{"hostname": ..., "interface": ...}` dict, not a
string — so a row looks like `{"Interface": {"hostname": "lab", "interface":
"GigabitEthernet0/1"}, "Description": "uplink", ...}`. This means
`workflow_steps.common.batfish_context.devices_from_nodes` (which reads a
plain `row["Node"]`) does not work for this question's rows; this step uses
a dedicated `devices_from_interface_rows` helper (same file) that reads
`row["Interface"]["hostname"]` instead, with the same dedup-into-one-
`DeviceContext`-per-node behavior.

**`nodes` confirmed; `interfaces` documented-but-unverified in this
codebase.** `pybatfish.client._facts.get_facts()` passes the same `nodes`
kwarg uniformly to every property question it calls (nodeProperties,
interfaceProperties, bgpProcessConfiguration, ...), which is how `nodes` was
confirmed for this question too. `interfaces` is a real, documented part of
Batfish's public `interfaceProperties` question, but — unlike every other
parameter this integration wraps — could not be independently exercised
against a live coordinator from this repo (the question schema itself is
fetched dynamically at runtime, not embedded in the `pybatfish` package). An
incorrect param name would surface immediately as pybatfish's own
rejected-kwarg error, not silently, but flagging it here per this doc's own
confirmed-vs-assumed convention — see "Open items" below.

**Property name suggestions: curated, not exhaustive.** Unlike
`BATFISH_FACT_KEYS` (node-level facts, confirmed by reading pybatfish's own
`NODE_PROPERTIES_REORG` mapping), there's no equivalent small curated list
embedded in the pybatfish client for interface properties —
`_facts.py::_add_interface` keeps every column the `interfaceProperties`
answer returns, whatever the live coordinator's schema defines, rather than
renaming a fixed subset. `frontend/.../shared/
batfish-interface-property-keys.ts::BATFISH_INTERFACE_PROPERTY_KEYS` is
therefore a curated starting-point list per Batfish's public question
documentation, explicitly labeled non-exhaustive in its own doc comment —
the `properties` field always accepts free text regardless.

**`route_empty_to_devices`/`empty_match_mode`: same audit feature as Node
Properties, adapted to the per-interface shape.** Identical semantics and
config fields (see Node Properties above for the full reasoning) — e.g.
`properties: Description`, `route_empty_to_devices: true` flags every node
with at least one interface that has no description set. Because the
`devices` outcome is still node-scoped (this codebase's `DeviceContext` has
no interface-level identity), a node is routed to `devices` if *any* of its
matching interfaces meets the empty condition, not only when every interface
on that node does.

**Result storage: same artifact shape as Node Properties/Routing Table, but
`success` and `devices` diverge in what they carry — see Node Properties
above for the full reasoning.** One workflow-level JSON artifact (`kind:
"batfish_result"`, `question: "interfaceProperties"`) plus a
`context.metadata[f"{node_id}.{output_key}"]` summary (`output_key` default
`batfish_interface_properties`) — read by `success`, which passes `context`
straight through unchanged otherwise.

**`devices` outcome: per-device enrichment, not identity-only.** Each
`DeviceContext` in `devices` is built by `_enrich_devices` (layered on top
of `devices_from_interface_rows` via `device.model_copy`) and carries **only
that node's own matching interfaces**, grouped under
`device.parsed[f"{node_id}.{output_key}"]["parsed"]["Interfaces"][<interface
name>]` — the same `"Interfaces"` nesting `pybatfish.client._facts.
get_facts()` itself uses for this question. Same motivation and same fix as
Node Properties: `devices` originally carried identity only, so a per-device
consumer downstream (Log Attributes, a device-detail dialog) had nothing
device-specific to read — the interface data only ever lived in the one
shared artifact above, identical regardless of which device you inspected.
`route_empty_to_devices` composes with this naturally, with no extra logic:
`_enrich_devices` only ever sees whatever `rows` it's given, and when
filtering is on, that's already just the flagged (empty) rows — so a
flagged device's `Interfaces` entry directly names *which* interface(s)
triggered the flag, not its full interface set.

**Direct network targeting.** Same optional `batfish_source_id`/`network`/
`snapshot` config fields as the other query/fact steps.

### Batfish OSPF Facts (`batfish-ospf-facts`, "Get OSPF Facts")

Combines up to four Batfish OSPF questions into one merged per-device OSPF
picture — genuinely different from Node/Interface Properties (one Batfish
question each): this step makes up to four calls and merges their results
per node. `requires: [identity]`, `produces: []`, `outcomes: [success,
devices]`.

**Row shapes — confirmed live, not assumed**, against a synthetic 3-router
snapshot (r1/r2 in area 0, r2/r3 in area 1, r2 as an ABR spanning both
areas):

- **`ospfProcessConfiguration`** — one row per (Node, VRF, Process_ID).
  Same identity shape as `nodeProperties` (plain `Node` string column).
- **`ospfAreaConfiguration`** — one row per (Node, VRF, Process_ID, Area).
  Same identity shape as `nodeProperties`. Confirmed live that an ABR gets
  more than one row (r2 returned two rows, one per area) — a single-dict
  merge would silently drop one.
- **`ospfInterfaceConfiguration`** — one row per (node, interface). Same
  nested `Interface` identity shape as `interfaceProperties`.
- **`ospfEdges`** — one row per OSPF adjacency, with a local `Interface` and
  a `Remote_Interface` (same nested shape). `nodes` filters by the local
  node; a separate `remoteNodes` param also exists on this question
  (confirmed live) but is not exposed by this step, for consistency with the
  other three OSPF questions.

Because `ospfProcessConfiguration`/`ospfAreaConfiguration` reuse the
`nodeProperties` identity shape and `ospfInterfaceConfiguration`/`ospfEdges`
reuse the `interfaceProperties` one, no new identity-extraction code was
needed — `workflow_steps.common.batfish_properties.group_rows_by_node` (made
public for this reuse) groups all four. What *is* new: the four-question
merge itself, implemented as a generic engine in
`workflow_steps/common/batfish_combined_facts.py`
(`CombinedQuestionSpec`/`build_combined_facts_outcomes`) rather than as
another `PropertyQuestionSpec` entry (that engine assumes exactly one
Batfish call in, one shape out — real merge logic across several
heterogeneous row shapes is genuinely new). `workflow_steps/common/
batfish_ospf_facts.py` supplies only the OSPF-specific `CombinedQuestionSpec`
table on top of that shared engine — originally written as a self-contained
module, then factored apart once **Batfish BGP Facts** (below) needed the
identical fetch-store-merge mechanics with a different question set.

**Config: `nodes`** (optional NodeSpecifier, applied to every enabled
question) **plus four independent toggles** — `include_process` /
`include_areas` / `include_interfaces` / `include_edges`, all default
`true`. At least one must stay enabled; the executor raises `ValueError`
otherwise (the frontend `ConfigPanel` also disables unchecking the last
remaining toggle, so this is a defense-in-depth check, not the primary
guard). Same `output_key` (default `batfish_ospf_facts`) and
`batfish_source_id`/`network`/`snapshot` direct-target fields as every other
query/fact step.

**Result storage: one artifact per enabled question, not one combined
artifact.** Each enabled question's raw rows are stored exactly like Node/
Interface Properties' own single-question result — one `kind:
"batfish_result"` artifact plus a `context.metadata[f"{node_id}.
{output_key}.{key}"]` summary, `key` one of `process`/`areas`/`interfaces`/
`edges` and `question` the real Batfish question name. This reuses the
existing convention verbatim: each enabled question's result shows up
automatically in the run detail view via `extractBatfishResults` (which
scans every `metadata` entry shaped like a Batfish result, regardless of key
naming), needing only new `QUESTION_LABELS` entries on the frontend — no new
rendering code. A disabled question has **no** metadata entry at all (not a
null/empty one).

**`devices` outcome: the actual "combined" merge.** One device per distinct
node seen in *any* enabled question's rows (union, not intersection — a node
appearing in only one enabled question still gets a device). Each device is
enriched at `device.parsed[f"{node_id}.{output_key}"]["parsed"]` with only
the keys for questions that had at least one row for that node:

```python
{
    "Process": [...],       # list -- multi-VRF nodes get more than one entry
    "Areas": [...],         # list -- ABRs get more than one entry
    "Interfaces": {"<if_name>": {...}, ...},  # dict, same nesting as Interface Properties
    "Adjacencies": [...],   # list -- each entry carries its own local + remote interface
}
```

`Process` and `Areas` are **always lists**, even with a single matching row
— the doc's original illustrative sketch showed a single dict, which this
implementation deliberately does not use, since it would silently drop data
for exactly the multi-VRF/multi-area nodes this section's live verification
confirmed are a normal, not edge, case. `Interfaces` mirrors Interface
Properties' own dict-keyed-by-name nesting. `Adjacencies` entries are the
full `ospfEdges` row unmodified (including the local `Interface`, not only
`Remote_Interface`) — useful when a node has more than one OSPF-adjacent
interface across different areas.

**Node identity union, and why a node's `Remote_Interface` doesn't get its
own device.** `ospfEdges` rows contribute identity via their local
`Interface.hostname` only (same as `interfaceProperties`) — `Remote_Interface`
is additional data on the *local* node's adjacency entry, not a second
identity to resolve. A node that appears only as some other node's
`Remote_Interface`, and in no other enabled question's rows, does not get
its own `devices` entry.

**Not fan-out sensitive.** Like the other query/fact steps, this is a pure
read against an already-built snapshot — no Fan-In placement requirement.

**Direct network targeting.** Same optional `batfish_source_id`/`network`/
`snapshot` config fields as the other query/fact steps.

**Deferred to a follow-up, not built here (by design):** an OSPF
health-audit filter (e.g. "flag nodes with a process configured but zero
adjacencies"), the equivalent of Node/Interface Properties'
`route_empty_to_devices`. The semantics differ enough from that flag (empty
value on a *requested property* vs. "one question has rows, another doesn't"
for the *same node*) that it needs its own design rather than reusing
`route_empty_to_devices` as-is — raised, not designed, here.

### Batfish BGP Facts (`batfish-bgp-facts`, "Get BGP Facts")

Combines up to four Batfish BGP questions into one merged per-device BGP
picture — structurally identical to Batfish OSPF Facts above (same
`workflow_steps/common/batfish_combined_facts.py` engine, same `requires:
[identity]`, `produces: []`, `outcomes: [success, devices]`), but simpler:
every one of its four questions shares one identity shape, so there is no
OSPF-style split between plain-`Node` and nested-`Interface` questions.

**Row shapes — confirmed live, not assumed**, against a synthetic 3-router
eBGP snapshot (r1 AS100 — r2 AS200 — r3 AS300, r2 peering with both):

- **`bgpProcessConfiguration`** — one row per (Node, VRF). Plain `Node`
  string column, same identity shape as `nodeProperties`.
- **`bgpPeerConfiguration`** — one row per configured peer. Same plain-`Node`
  identity; r2 (two peers) returned two rows.
- **`bgpSessionStatus`** — one row per BGP session, including
  `Established_Status`. Same plain-`Node` identity — confirmed **not** to use
  `ospfEdges`' nested `Interface` shape: its `Remote_Node` field is a plain
  string.
- **`bgpEdges`** — one row per BGP adjacency direction (each side reports its
  own row, e.g. r1→r2 and r2→r1 are two separate rows). Same plain-`Node`
  identity as the other three — confirmed **not** to use `ospfEdges`' nested
  `Interface`/`Remote_Interface` shape, despite being BGP's direct analogue
  of that question. `nodes` filters by the local node; a separate
  `remoteNodes` param also exists (confirmed live) but is not exposed by
  this step, for consistency with `ospfEdges`' own choice.

Because all four questions share the `nodeProperties` identity shape, this
step needed no `_interface_node_key`/dict-by-name grouping at all — every
merged field is a plain list, via the same `_node_key` extractor and a
shared "strip the redundant `Node` field, return the list" builder
(`workflow_steps/common/batfish_bgp_facts.py`). Genuinely less code than
Batfish OSPF Facts for this reason, not a simplification taken at the cost
of correctness.

**Config: `nodes`** (optional NodeSpecifier, applied to every enabled
question) **plus four independent toggles** — `include_process` /
`include_peers` / `include_sessions` / `include_edges`, all default `true`.
At least one must stay enabled; the executor raises `ValueError` otherwise
(same frontend defense-in-depth as Batfish OSPF Facts). Same `output_key`
(default `batfish_bgp_facts`) and `batfish_source_id`/`network`/`snapshot`
direct-target fields as every other query/fact step.

**Result storage and `devices` outcome: identical convention to Batfish OSPF
Facts** (see that section for the full reasoning) — one `kind:
"batfish_result"` artifact per enabled question (`key` one of
`process`/`peers`/`sessions`/`edges`), and one device per distinct node seen
in *any* enabled question's rows, enriched with only the keys for questions
that matched:

```python
{
    "Process": [...],       # list -- multi-VRF nodes get more than one entry
    "Peers": [...],         # list -- every configured peer
    "Sessions": [...],      # list -- every BGP session
    "Adjacencies": [...],   # list -- every adjacency direction
}
```

Every field here is **always a list**, including with a single matching row
— same multi-row-is-normal reasoning as OSPF's `Process`/`Areas`, just
applying to all four questions here instead of two. Unlike OSPF's
`Adjacencies` (which keeps the row's local `Interface` for context), this
step's row-building step drops the now-redundant `Node` field from every
question's rows before storing them under `parsed` — plain-string `Node`
carries no information beyond the grouping key it already used, unlike
OSPF's `Interface` dict (which also names the local interface).

**Node identity union, and why a node's `Remote_Node` doesn't get its own
device.** Same rule as OSPF's `Remote_Interface`: `bgpSessionStatus`/
`bgpEdges` rows contribute identity via their own `Node` field only —
`Remote_Node` is additional data on the local node's row, not a second
identity to resolve. A node that appears only as some other node's
`Remote_Node`, and in no other enabled question's rows, does not get its own
`devices` entry.

**Not fan-out sensitive. Direct network targeting.** Same as Batfish OSPF
Facts — pure read against an already-built snapshot, same optional
`batfish_source_id`/`network`/`snapshot` config fields.

### Batfish ACL Check (`batfish-acl-check`)

`requires: [identity]`, `produces: []`. Wraps `bf.q.testFilters(...)` —
confirmed against a real ACL (`permit tcp any host 192.168.1.1 eq 22; deny
ip any any`): a concrete 5-tuple flow through a named filter, returning
`Action` (`PERMIT`/`DENY`) and the matched `Line_Content`:

```python
bf.q.testFilters(
    nodes=config["node"],           # nodeSpec, e.g. "R1"
    filters=config["filter_name"],  # filterSpec, e.g. "TEST-ACL"
    headers={                       # required
        "srcIps": config.get("src_ips"),
        "dstIps": config["dst_ips"],
        "applications": config.get("applications"),   # e.g. ["SSH"], ["TELNET"]
        "ipProtocols": config.get("ip_protocols"),
    },
    startLocation=config.get("start_location"),
).answer().frame()
```

`headers` is documented by pybatfish itself as *Required* for this question
(unlike `reachability`'s optional `headers`) — the config panel should mark
at least `dst_ips` as required, matching this. Like Path Check, this step
uses branchable outcomes — `outcomes: [permit, deny]` (as implemented, same
no-`failure`-outcome reasoning as Path Check) — read from the answer's
`Action` column; also a single-`StepOutcome`, whole-context-passthrough
step, not a per-device partition, for the same reason (one concrete flow
from `config`, not one check per device). An empty result set here is
treated as an execution problem, not a verdict — `raise RuntimeError`
rather than defaulting to `deny`, since "no result" means the
`node`/`filter_name` didn't match anything in the snapshot, not that the
filter denied the traffic. Stores its result the same workflow-level-artifact
way Routing Table does.

**`searchFilters` was considered and rejected as the primary mapping for
"ACL permits this traffic".** `searchFilters()` answers a broader question —
"does *any* flow matching this header space get permitted/denied" — useful
for an existence check across a whole space of traffic, but the user's
framing ("ACL permits this traffic") reads as "check this specific traffic
description," which is exactly `testFilters()`'s contract: one concrete flow
in, one concrete verdict out, no example-searching involved.
`filters`/`nodes` narrow which filter(s) are tested the same way in both
questions, so a v2 "does any SSH traffic reach this host at all" variant of
this step could reuse most of the same config shape with `searchFilters()`
if that broader question turns out to be wanted later.

**Direct network targeting.** Same optional `batfish_source_id`/`network`/
`snapshot` config fields as Routing Table — see "Bypassing metadata:
querying a network directly" above.

### Batfish Path Check (`batfish-path-check`)

`requires: [identity]`, `produces: []`. Wraps `bf.q.reachability(...)` —
this is the actual "is there a path between device A and device B" question,
confirmed working end-to-end against the two-router snapshot:

```python
bf.q.reachability(
    pathConstraints={
        "startLocation": config["start_node"],   # e.g. "R1" -- a device hostname/nodeSpec
        "endLocation": config.get("end_node"),   # optional -- omit to search any destination
    },
    headers=config.get("headers", {}),           # optional headerConstraint, e.g. {"dstIps": "..."}
    actions=config.get("actions", ["success"]),  # dispositionSpec, default ["success"]
    maxTraces=config.get("max_traces"),
    invertSearch=config.get("invert_search", False),
    ignoreFilters=config.get("ignore_filters", False),
).answer().frame()
```

**Important param-shape gotcha, verified the hard way**: `headers` is a
**sibling** top-level parameter of `pathConstraints`, not nested inside it —
`reachability(pathConstraints={"startLocation": ..., "headers": {...}})`
fails with a 400 from the coordinator (`Unrecognized field "headers"`,
`PathConstraintsInput` only recognizes `startLocation`/`endLocation`/
`transitLocations`/`forbiddenLocations`). The step's config schema should
mirror the correct (flat) shape directly rather than a nested one that looks
more "intuitive" but doesn't match the real API.

Empty `answer().frame()` means no matching flow was found for the given
constraints, which for a "does a path exist between A and B" question *is*
the negative-case answer, not an error. Unlike Routing Table's plain
success/failure, this step gives that answer a first-class canvas outcome —
`outcomes: [reachable, not_reachable]` (as implemented — **no `failure`
outcome**: a config/input problem raises `ValueError`, a Batfish-side
failure raises via `BatfishAPIError`, neither is modeled as a third outcome
branch) — so a workflow can branch on it directly (e.g. alert only when a
critical path breaks).

**Not a per-device partition, unlike `compare-pyats-snapshot`'s
`match`/`mismatch`/`failure`.** That step's branching splits
`context.devices` itself into buckets, because it evaluates the same
condition independently *per device*. Path Check evaluates ONE flow
definition from `config` (`start_node`/`end_node`/`headers` — not derived
from `context.devices` at all), so the step returns a single-element
`list[StepOutcome]` — whichever one of `reachable`/`not_reachable`
applies — carrying the **full, unmodified** `context.devices` through that
one outcome. The other declared outcome name simply doesn't fire for that
run, the same way a plain `success`/`failure` step only ever returns one of
the two. Result storage follows the same workflow-level-artifact-plus-
metadata-summary approach as Routing Table above.

**Direct network targeting.** Same optional `batfish_source_id`/`network`/
`snapshot` config fields as Routing Table — see "Bypassing metadata:
querying a network directly" above.

## Frontend: category gating

Exactly mirrors pyATS's existing mechanism in
`frontend/src/components/features/workflows/components/step-catalog.tsx`
(lines ~121-130 as of this writing):

```typescript
const { data: batfishSourcesData } = useBatfishSourcesQuery();
const hasBatfishSource = (batfishSourcesData?.sources.length ?? 0) > 0;

// The Batfish category only makes sense once a Batfish source is configured.
const visibleGroups = useMemo(() => {
  const withoutPyats = hasPyatsSource ? allGroups : allGroups.filter((g) => g.categoryKey !== "pyats");
  return hasBatfishSource ? withoutPyats : withoutPyats.filter((g) => g.categoryKey !== "batfish");
}, [plugins, hasPyatsSource, hasBatfishSource]);
```

Frontend-only filter, no backend change — the eleven steps are always
registered in `registry.yaml`/`step_registry.py` (a workflow built before a
source existed and later shared would still execute correctly; only the
*palette* — where you'd drag a new instance from — is gated). `palette_category:
batfish` in `registry.yaml` is the value this filter matches against, exactly
the same field/value pattern as `palette_category: pyats`.

## Viewing results: the run detail UI

The three query steps store their answer as one artifact plus a small
summary dict in `WorkflowContext.metadata[f"{node_id}.{output_key}"]` (see
"Result storage" under each step above) — this section covers where a user
actually sees that after a run finishes, added after real usage surfaced two
navigation/visibility gaps:

**Gap 1 (fixed): the answer was invisible without knowing to open a second
dialog.** The run detail view has two renderings of the same step —
expanding it inline (click the step name) uses `StepResultViewer` in
`compact` mode, which never rendered the Metadata section at all; only
"open in dialog" (a small logs icon) rendered it, and even then only as a
raw `JSON.stringify` blob keyed by `{node_id}.{output_key}`. A user who only
ever expanded inline had no path to the answer whatsoever.

**Gap 2 (fixed): even once found, the metadata blob was a summary, not the
answer.** `{"kind": "batfish_result", "question": "routes", "artifact_ref":
{...}, "row_count": 0}` tells you *that* something happened, not what the
actual routes/path/ACL verdict was — the real content lives in the artifact
the `artifact_ref` points to, and this app has **no generic "click to view
artifact content" UI** (confirmed: `ArtifactRefRow` renders only
`{kind} · {size} bytes`, no click handler, for every step's artifacts, not
just Batfish's — a pre-existing gap, not something this integration
introduced).

**The fix reused an existing mechanism rather than building a new one.**
`ConfigArtifactPanel` + `useArtifactQuery` (`frontend/src/hooks/queries/use-artifact-query.ts`)
already fetch-and-render artifact content by `artifact_id`, scoped to a
`run_id`, via a **generic, kind-agnostic, already-existing backend endpoint**
— `GET /api/runs/{run_id}/artifacts/{artifact_id}`
(`backend/routers/workflow_runs.py` → `RunService.get_run_artifact` →
`ArtifactService.get_for_run`, permission `workflow_runs:read`, scoped by
`run.uuid` so one run can't read another's artifact). This was already used
for device running/startup configs and Genie snapshots — it needed zero
backend changes to work for `batfish_result` artifacts too, since it doesn't
filter by `kind` at all. (Whoever investigates "can we view artifact content
anywhere" for a *different* step in the future should know this already
exists — it's easy to miss since `ArtifactRefRow`, the dumb non-clickable
row component, is the more visible/superficially similar file.)

**New component: `batfish-result-panel.tsx`.** Extracts every
`{node_id}.{output_key}` metadata entry whose value has
`"kind": "batfish_result"` (`extractBatfishResults`), plus the connection
info under the `"batfish"` key (`extractBatfishConnection`), and renders
each as a small card: a human label (`routes` → "Routing table",
`reachability` → "Path check", `testFilters` → "ACL check", `validateFacts`
→ "Validate facts", `extractFacts` → "Extract facts"), a reachable/
not-reachable or permit/deny badge when present, the row count,
an explicit warning line when `row_count === 0` (a real, common answer —
config didn't parse into Batfish's model, or the filters excluded
everything — not necessarily a bug), and a `ConfigArtifactPanel` that
fetches and displays the actual artifact JSON. `metadata-panel.tsx`'s
generic dump excludes these same keys (`isBatfishMetadataKey`) so they don't
appear twice.

**Wired into two places:**
- `OutcomeContextView` — unconditionally (not gated by `compact`), right
  above the Devices section, so the answer is visible from the inline
  expand view with no extra click. This is the actual fix for Gap 1.
- `DeviceDetailDialog`'s left sidebar (the per-device "Detailed view"
  dialog opened from `DeviceCard`) — a new **"Batfish result"** nav entry
  (Radar icon, count badge) appears whenever the run has any Batfish
  result, in *every* device's dialog, labeled as workflow-level (not
  device-specific) content — this was the explicit, literal feature
  request that prompted this section, mirroring the sidebar's existing
  `DetailSection` list pattern (`{id, label, icon, count, render}`).

Prop threading required to get the extracted `batfishResults`/
`batfishConnection` from `OutcomeContextView` (which has `context.metadata`)
down to `DeviceDetailDialog` (which only receives one `device`): through
`DevicesSection` → `DeviceCard` → `DeviceDetailDialog`, each taking the two
values as optional props defaulting to empty/`null` via a module-level
constant (`EMPTY_BATFISH_RESULTS`), matching this codebase's own
"hold defaults in a module-level constant" convention for avoiding a new
array/object identity every render.

**Deliberately not built**: per-device filtering of a routing-table result
to just the rows where `Node` matches the open device (Batfish's `routes()`
answer does have a `Node` column that could support this). The result is
shown identically regardless of which device's dialog is open. Worth
revisiting if users find the unfiltered table noisy for large topologies.

## Template Editor integration: ad-hoc preview queries

The three query steps above only ever run inside a real `WorkflowRun` -- there
was no way to get a Batfish answer into the **Template Editor** as a Jinja
variable, the way "Get Configs"/"Execute Commands" already let it preview a
test device's config/command output. This section adds that: a `batfish`
tab in the Options modal (`options-dialog.tsx`, renamed from
`netmiko-options-dialog.tsx` once it stopped being Netmiko-only) that runs
one of the three questions **ad hoc, with no `WorkflowRun`/`WorkflowContext`
involved at all**, and drops the answer into a `batfish` template variable.

**Same shape as the existing Netmiko preview path.** `NetmikoPreviewService`
(`services/network/netmiko/preview_service.py`) already established the
precedent: a small service that calls the underlying automation library
directly (`NetmikoService`), bypassing the entire workflow-run/step-registry
machinery, keyed only by the values a user picks in the editor (host +
credential). `BatfishPreviewService` (`services/batfish/preview_service.py`)
follows the same shape for Batfish: it resolves a `BatfishConnection` via
`BatfishSourceConfigService.resolve_connection(source_id)` (the same call
`resolve_batfish_snapshot_ref`'s "direct network targeting" branch already
made), picks the latest snapshot when the user leaves `snapshot` blank, and
calls `BatfishService.routes()`/`.reachability()`/`.test_filters()` directly
-- no `run`, no `context`, no `artifact_service`, no `node_id`.

**Shared query-building logic, not a parallel implementation.** Every piece
of "turn inputs into the exact `pybatfish` call for this question" now lives
exactly once, in `services/batfish/query_helpers.py`, used by both the
workflow-step executors and `BatfishPreviewService`:

- `resolve_latest_snapshot_name` — the "pick the most recent snapshot by
  `creationTimestamp`" sort, previously inlined in
  `resolve_batfish_snapshot_ref`.
- `build_batfish_headers` — the `headers` dict construction, previously two
  near-identical private `_build_headers` copies in the
  `batfish-path-check`/`batfish-acl-check` executors.
- `require_field` — the "strip and raise if blank" pattern every required
  field (`start_node`, `node`, `filter_name`, `dst_ips`) used to spell out
  inline, with inconsistent wording between the step-config-dict callers and
  the typed-Pydantic-request caller.
- `query_routes`/`query_reachability`/`query_test_filters` — the actual
  parameter assembly (`pathConstraints`, `_or_none` normalization, etc.) and
  the `batfish.routes()`/`.reachability()`/`.test_filters()` call itself, one
  function per question. Each executor and the corresponding
  `BatfishPreviewService.run_*` method now differ only in how they validate
  required fields and resolve a snapshot beforehand (workflow-step config
  dict + `resolve_batfish_snapshot_ref`'s run-metadata fallback vs. a typed
  request + `BatfishPreviewService._resolve`'s always-explicit network) —
  neither duplicates the question logic itself anymore.

One behavior this consolidation *fixed*: `run_test_filters` previously raised
`BatfishValidationError` (a 400) when the coordinator returned zero rows,
inconsistent with the executor's own reasoning (an empty result means
`node`/`filter_name` didn't match anything in the snapshot — an execution
problem, not a bad request). `query_test_filters` now raises `RuntimeError`
for both callers alike, which the router maps to a sanitized 500 like any
other unexpected failure.

`require_field`/`query_*` are deliberately *not* responsible for resolving
the connection/snapshot themselves, and don't validate required fields
before being called — each caller does that first (via `require_field`) so a
blank required field fails immediately, before paying for a Batfish
snapshot-listing round-trip in `resolve_latest_snapshot_name`.

**New endpoints, one per question, under the existing source prefix**
(`routers/sources/batfish/query.py`, same `require_permission("sources.batfish",
"read")` as the rest of that router -- this is a read-only analysis call
against an already-built snapshot, no device contact, so no new permission
was added):

```
POST /api/sources/batfish/{source_id}/query/routes
POST /api/sources/batfish/{source_id}/query/reachability
POST /api/sources/batfish/{source_id}/query/test-filters
```

Request bodies mirror each question's step-config fields 1:1 (see each
step's section above) plus `network`/`snapshot` (`BatfishRoutesQueryRequest`/
`BatfishReachabilityQueryRequest`/`BatfishTestFiltersQueryRequest` in
`models/batfish.py`); there is no `output_key` field since that's a
workflow-run-metadata concept that doesn't apply here. The response
(`BatfishQueryResponse`) carries `success`, `question`, `network`, `snapshot`,
`rows`, and `reachable`/`action` when applicable -- the same fields
`BatfishResultPanel` already surfaces from a real run's metadata, so the two
surfaces (ad-hoc preview vs. run-detail viewer) present an answer
consistently.

**No networks/snapshots discovery endpoint was added.** The Options modal's
Batfish tab uses a plain `Select` (populated from the existing
`GET /sources/batfish` list) for the source, and free-text `network`/
`snapshot` inputs -- matching the exact convention the three workflow-step
config panels already established via `BatfishDirectTargetFields`'s "blank
snapshot = latest" behavior. (`BatfishDirectTargetFields`/
`BatfishSourceSelectDialog` themselves were not reused verbatim in the
modal -- their built-in copy assumes a workflow-run context, e.g. "Leave
blank to use the snapshot from an upstream Init Batfish Snapshot step in this
run," which is inaccurate for an ad-hoc call with no run at all. The Options
modal's Batfish tab (`batfish-options-tab.tsx`) builds its own small
source/network/snapshot block with copy accurate to that context, reusing
only `useBatfishSourcesQuery` for the source list.)

**Persisted: the query definition, never the fetched answer.** Like
`credential_id`/`pre_run_commands`/`nautobot_attributes`/the "Get Configs"
checkbox today, the Batfish tab's configuration round-trips with a saved
template so reopening it restores the same setup -- but the answer itself is
always re-fetched on demand via "Run Query," exactly like `parsed_config`/
command results aren't persisted either. One new nullable JSON-as-text column,
`Template.batfish_config` (`core/models/templates.py`), stores `{enabled,
source_id, network, snapshot, question, generic_question_name, params}` -- the same
serialize-with-`json.dumps`/deserialize-with-`json.loads`-and-fallback-to-None
convention `nautobot_attributes` already uses, not a native Postgres JSON
column (this codebase's `templates` table stores every JSON-shaped field as
`Text`, not `JSON`/`JSONB`).

**Variable shape.** Enabling the "Enable Batfish Result" checkbox adds a
`batfish` auto-variable (`BATFISH_VARIABLE` in `constants.ts`, mirroring
`PARSED_CONFIG_VARIABLE`'s pattern exactly) whose value is the full
`BatfishQueryResponse` JSON-stringified -- so a template can reference
`batfish.rows`, `batfish.reachable`, `batfish.action`, `batfish.question`,
`batfish.network`, `batfish.snapshot` directly.

**Bug found and fixed: this `batfish` variable is preview-only and must
never be referenced in a template body.** Every other auto-variable this
editor offers mirrors a real workflow step's runtime output exactly
(`nautobot` ↔ Get Nautobot Attributes, `parsed`/`command`/`commands` ↔
Parse Cisco Config/Run Command, etc.) -- `PARSED_CONFIG_VARIABLE`'s own
comment states this explicitly. `batfish` broke that invariant: it mirrors
`batfish-routing-table`/`batfish-path-check`/`batfish-acl-check`'s answer
shape, but per "Batfish Routing Table" → "Result storage" above, none of
those three steps ever write their result onto a `DeviceContext` --
they're stored only as a workflow-level artifact + `WorkflowContext.metadata`
pointer. `build_jinja_context`
(`workflow_steps/common/jinja_render.py`) never injects a `batfish` key at
real render time, so a template that used `{{ batfish.rows }}` -- which
renders correctly in this editor, since the preview genuinely populates that
variable -- would fail **every device** at actual workflow runtime with
`Undefined template variable: 'batfish' is undefined` (Jinja2's default
`Undefined.__str__` raises, it doesn't render blank; see "Undefined
variables" in the Jinja help dialog). Fixed by:
- `constants.ts`: `BATFISH_VARIABLE.description` now states plainly that the
  variable is preview-only and lists the real per-device alternative
  (`parsed.<output_key>` from Extract Facts / Get OSPF Facts / Get BGP Facts
  / Batfish Node or Interface Properties -- see "Extract Facts" and "Batfish
  OSPF Facts" above).
- `batfish-options-tab.tsx`: a persistent warning `Alert` at the top of the
  Batfish tab itself, so the trap is visible at the point of use, not only in
  a variable's description text.
- `jinja-help-dialog.tsx`: a new "Batfish (per-device steps only)"
  subsection under "The parsed namespace" spelling out exactly which Batfish
  steps populate `parsed` (Extract Facts always; Get OSPF Facts/Get BGP
  Facts/Batfish Node/Interface Properties only via their `devices` outcome)
  and which never do (Routing Table/Path Check/ACL Check), with a pointer
  back to the Batfish tab's warning.

No backend change was made or is planned for this — wiring
Routing Table/Path Check/ACL Check results into `device.parsed` (so they
*could* legitimately appear in a per-device template) is a separate,
deferred backend design question, tracked as an open action item in
`doc/OPEN_TODOS.md` → "Wire Batfish Routing Table/Path Check/ACL Check
results into per-device templates". This session's fix only makes the
editor stop lying about what already exists today.

**Still not built (see "Open items" below):** exporting an ad-hoc preview
result via `store-artifact`, and any UI to browse a source's actual Batfish
networks/snapshots (both editor and canvas config panels still take
`network`/`snapshot` as free text).

### Generic ad-hoc questions: the long tail beyond routes/reachability/testFilters

The three typed questions above cover what's worth automating as canvas
steps, but Batfish's own question catalog is much larger (see, e.g., the
[configProperties
notebook](https://batfish.readthedocs.io/en/latest/notebooks/configProperties.html)) --
most of the rest are one-off/exploratory questions that don't justify a
bespoke step package each. `POST /sources/batfish/{source_id}/query/generic`
(`BatfishGenericQueryRequest` -> `BatfishPreviewService.run_generic` ->
`query_helpers.query_generic`) covers that long tail with one endpoint
instead: any question in `GENERIC_QUESTION_ALLOWLIST`
(`services/batfish/query_helpers.py`), plus a free-form `params` dict
forwarded as pybatfish kwargs. Surfaced in the Options modal's Batfish tab as
a 4th "Custom Question..." entry: a free-text question-name field (datalist-
suggested from `BATFISH_GENERIC_QUESTION_NAMES`, the same non-enforcing-
suggestion-list convention as `BATFISH_FACT_KEYS`) plus a JSON textarea for
`params`.

**Security: a hardcoded allow-list, not a raw `getattr` on user input.**
`BatfishService._answer` already dispatches any question name via
`getattr(session.q, question_name)` with zero validation of its own (it's
how the 5 typed questions above are implemented internally) -- so
`BatfishService.generic_question` (a thin public wrapper around `_answer`)
must never be reached with an unvalidated caller-supplied name.
`query_generic` is the actual security boundary: it checks
`question_name in GENERIC_QUESTION_ALLOWLIST` and raises `ValueError`
(-> 400) before ever calling `BatfishService.generic_question`. The
allow-list is a `frozenset[str]` literal in `query_helpers.py`, not
data-driven from any request -- extending it means editing that file, not
something a workflow/template author can do themselves.

**No canvas step, no device enrichment, no `store-artifact` integration** --
same reasoning already given for the 3 typed ad-hoc questions above. A
generic question's answer has no known row-identity shape (unlike
`nodeProperties`/`interfaceProperties`, whose shapes are confirmed and
handled by `workflow_steps/common/batfish_properties.py`), so there is no
`devices` outcome to build even in principle without per-question
verification first -- exactly the same reason Part A's canvas-step allow-list
(node/interface properties) stays smaller than this one; see "Open items".

**Allow-list contents, confirmed live, not assumed from docs.** Every entry
was verified by initializing a synthetic two-router snapshot (loopbacks,
one `GigabitEthernet` link, OSPF area 0, eBGP peering, VRF, and an ACL on
each router) against a real `batfish` coordinator and calling each candidate
question with empty/default params, matching this doc's "confirmed, not
assumed" practice everywhere else:

```
bgpPeerConfiguration, bgpProcessConfiguration, bgpEdges,
bgpSessionCompatibility, bgpSessionStatus, ospfProcessConfiguration,
ospfInterfaceConfiguration, ospfEdges, namedStructures, ipOwners, edges,
undefinedReferences, unusedStructures, filterLineReachability,
switchedVlanProperties
```

Three documented-sounding candidates were tried and dropped because they
don't exist under those names in the installed pybatfish/coordinator version
(`'Questions' object has no attribute ...`): `vrfProperties`,
`aclReachability`, `subnetMultipleAccess`. Also deliberately excluded:
anything needing a second/reference snapshot (`differentialReachability`,
`compareFilters`, ...) -- out of scope for this single-snapshot surface --
and every question already covered by a typed step/endpoint.

## Open items / verify during hardening

- **The generic ad-hoc allow-list is intentionally not a template for the
  canvas-step (Part A) allow-list.** `GENERIC_QUESTION_ALLOWLIST` covers 15
  questions because an ad-hoc query has no `devices` outcome to build --
  there's nothing about a question's row-identity shape it needs to know.
  `workflow_steps/common/batfish_properties.py`'s `PropertyQuestionSpec`
  registry, by contrast, stays at exactly `nodeProperties`/
  `interfaceProperties` (the only two Batfish-Node identity shapes confirmed
  in this codebase) until a *new* question's row-identity shape is verified
  live the same way `interfaceProperties`' was -- adding a name to the
  generic allow-list is not sufficient justification to also add a canvas
  step for it. This was a deliberate scope decision (not an oversight) when
  this generalization work was done -- see this doc's own "Template Editor
  integration" -> "Generic ad-hoc questions" section for the verification
  method to reuse when that day comes.
- **Verify `batfish-interface-properties`' `interfaces` config field against
  a live coordinator.** Unlike every other question parameter this
  integration wraps, `interfaces` (an InterfacesSpecifier passed to
  `bf.q.interfaceProperties(...)`) was not exercised against a real Batfish
  coordinator while implementing this step — `nodes`/`properties` were
  confirmed via `pybatfish.client._facts.get_facts()`'s own usage and
  `nodeProperties`'s confirmed behavior respectively, but `interfaceProperties`'
  own full parameter set is fetched dynamically from the coordinator at
  runtime and isn't available statically in this repo. A wrong param name
  would fail loudly (a pybatfish rejected-kwarg error), not silently, but
  confirm the field actually filters as expected before relying on it for a
  production audit.
- **RESOLVED during implementation**: no `validate_outbound_http_url` call
  was needed. `BatfishSourceConfigService` does plain non-empty/length
  validation on `host` (`_validate_host`) rather than routing it through the
  URL/loopback-allowlist path every other source uses — `host` is a bare
  hostname/IP, not a URL, so that path doesn't apply. This also means the
  loopback case (native-backend dev pointing at `127.0.0.1`) needs no
  `ALLOW_LOOPBACK_SOURCE_URLS` exception the way pyATS/OpenBao do — there's
  no URL-shaped value for that guard to reject in the first place.
- **Deferred: no `store-artifact`/`content_resolver.py` integration for
  Batfish query results.** Narrowed in scope since "Viewing results" above
  shipped: *visibility* (seeing the answer in the run detail UI, and now also
  in the Template Editor's ad-hoc preview — see "Template Editor integration"
  above) is solved; what's still deferred is *export* — piping a result to
  git/filesystem via `store-artifact` the way device configs can be. Revisit
  only if a real request for that surfaces; the in-run viewer and the editor
  preview may be sufficient on their own.
- **RESOLVED: networks/snapshots discovery endpoint and picker.**
  `BatfishService.list_networks(connection)` (a standalone method, not folded
  into `check_health` — kept separate so each keeps its own error-message
  wording for its own purpose) and the already-existing
  `list_snapshots_with_metadata` are now exposed via
  `GET /api/sources/batfish/{source_id}/networks` and
  `GET /api/sources/batfish/{source_id}/networks/{network}/snapshots`
  (`routers/sources/batfish/discovery.py`, same
  `require_permission("sources.batfish", "read")` as the rest of that
  router; snapshots sorted most-recent-first by `created_at`, same sort key
  `resolve_latest_snapshot_name` uses). `BatfishDirectTargetFields` (shared
  by all seven query/fact steps) and the Template Editor's Options-modal
  Batfish tab both fetch these via `useBatfishNetworksQuery`/
  `useBatfishSnapshotsQuery` and render a `<Select>` when the coordinator has
  entries, falling back to the original free-text `<Input>` underneath —
  picking a network clears the current `snapshot` field, since a snapshot
  name from a different network wouldn't be valid. Typing into the fallback
  field locks that field into manual mode on the first keystroke and stays
  there until the operator explicitly switches back — otherwise, if the
  picker's data finished loading mid-keystroke, the `<Select>` would swap
  back in under the cursor and (in some browsers) trigger an
  autofill-suggestions popup listing every partial value typed so far.

  **Bug found and fixed during hardening: a picker querying an
  unconfirmed network name silently CREATED it.** `list_batfish_snapshots`
  originally called `list_snapshots_with_metadata` directly, which goes
  through `BatfishService._get_session()` → pybatfish's own
  `Session.set_network(name)` — confirmed by reading the installed
  pybatfish source that this call 404s via `restv2helper.get_network` and
  then unconditionally calls `restv2helper.init_network`, i.e. it **creates
  the network if it doesn't already exist**. Before the "lock into manual
  mode" fix above existed, every keystroke into the network field fired
  this endpoint with the current partial string, silently creating a real,
  empty network on the coordinator per keystroke (confirmed in practice: a
  user typing "manus-live" left behind eleven junk networks — `m`, `ma`,
  `man`, ..., `manus-live` — permanently polluting the picker for everyone).
  Fixed by having `list_batfish_snapshots` call `list_networks` first and
  return an empty snapshot list for any network not already in that result,
  never reaching `list_snapshots_with_metadata`/`set_network` for an
  unconfirmed name. Regression-tested
  (`test_list_snapshots_unknown_network_returns_empty_without_touching_metadata_call`).

  **RESOLVED: the same risk in the query/fact steps' "direct network
  targeting" fields and the ad-hoc preview service.** Both
  `workflow_steps.common.batfish_context.resolve_batfish_snapshot_ref`
  (used by all seven query/fact steps' direct-network-targeting config) and
  `BatfishPreviewService._resolve` (the Template Editor's ad-hoc preview
  queries) resolved a caller-supplied `network` straight into a
  `list_snapshots_with_metadata`/actual-question call — the identical
  `_get_session` → `set_network` → creates-if-absent path as the picker bug
  above, just triggered by a saved step's config or a preview request
  instead of a keystroke. A typo'd or not-yet-created `network` value would
  silently create a junk network before failing. Fixed with one shared
  guard, `services.batfish.query_helpers.assert_batfish_network_exists`
  (calls `list_networks` and raises `ValueError` if the name isn't in it),
  called at the top of both resolution points — before
  `resolve_latest_snapshot_name` *and* before the explicit-snapshot path
  that used to skip it entirely (an explicit `network`+`snapshot` pair
  still reaches the question call itself, which hits the same
  `_get_session` path). Regression-tested in both callers
  (`test_nonexistent_network_raises_value_error_without_listing_snapshots`
  in `test_batfish_context_ref_resolver.py` and
  `test_batfish_preview_service.py`), asserting
  `list_snapshots_with_metadata`/the question call is never reached for an
  unconfirmed network.
- **Not built: a loud signal when a snapshot init parses zero usable
  nodes.** Observed in real usage: a `batfish-routing-table` run returned
  `row_count: 0` with no other indication anything was wrong, and the
  underlying cause (a device's captured "running-config" not being valid
  Batfish-parseable syntax — wrong platform, malformed capture, etc.) is
  invisible without manually inspecting the artifact content via the new
  viewer. `batfish-init-snapshot` already knows the input device count
  (`len(context.devices) - len(skipped)`, in its success summary) but has no
  way today to know how many of those actually became real Batfish nodes
  (`pybatfish` doesn't return a "N nodes parsed" count from `init_snapshot`
  itself — would need a follow-up `bf.q.nodeProperties()` or similar call
  right after init to get a real node count and warn loudly if it's zero
  or far below the device count).
- **Snapshot retention default (`retain_snapshots: int`, proposed default
  `5`).** Chosen for symmetry with pyATS's per-chunk defaults being
  reasonable-guess numbers rather than measured ones — revisit once real
  snapshot sizes/frequency are known.
- **TODO: network/snapshot deletion management (endpoints + UI).** There is
  currently no in-app way to delete a Batfish network or snapshot — a real
  gap surfaced directly by the `set_network`-creates-if-absent incident
  above: cleaning up the junk networks it left behind required going
  around the app entirely (direct coordinator access). Needed:
  - `BatfishService.delete_network(connection, batfish_network)` — a new
    thin wrapper (mirrors `delete_snapshot`'s shape); `Session.delete_network`
    already exists on `pybatfish`, unused so far.
  - `BatfishService.delete_snapshot` **already exists** (used internally by
    `batfish-init-snapshot`'s retention sweep) — only a management endpoint
    is missing, not the primitive.
  - New endpoints in `routers/sources/batfish/discovery.py` (or a sibling
    file): `DELETE /sources/batfish/{source_id}/networks/{network}` and
    `DELETE /sources/batfish/{source_id}/networks/{network}/snapshots/{snapshot}`.
    Destructive, so gate on `require_permission("sources.batfish", "write")`
    (matching `test-connection`'s write-gated mutation), not the `read`
    dependency the rest of this router uses.
  - Frontend: a delete action next to each entry in
    `useBatfishNetworksQuery`/`useBatfishSnapshotsQuery`'s consumers, or a
    small dedicated management view under Settings → Sources → Batfish —
    not yet designed.
  - Confirm before deleting either — irreversible, and a network can hold
    snapshots other workflows still depend on.
- **Node-name case sensitivity, verified as a non-issue but stated
  explicitly.** Batfish canonicalizes hostnames to lowercase internally (a
  device configured with `hostname R1` appears as node `r1` in every answer
  table), but pybatfish's node/filter specifiers matched `"R1"`/`"TEST-ACL"`
  case-insensitively in testing. Config panels can accept whatever casing
  matches the user's own device hostnames without a normalization step —
  confirmed empirically, not from documentation (Batfish's specifier-language
  docs don't state this explicitly either way).
- **Multi-VRF, multi-AS, or genuinely large topologies** are unverified here —
  every claim above was checked against a deliberately minimal 2-router,
  single-VRF, static-routing snapshot (two `GigabitEthernet` interfaces per
  device, one static route each, one ACL). BGP/OSPF-heavy real inventories,
  multiple VRFs, or very large device counts (Batfish's own parse/model time
  scales with snapshot size) are not covered by anything checked while
  writing this doc.
- **RESOLVED: git-backed snapshot source.** `batfish-init-snapshot` now
  supports `config_source: git`, reading configs from a `GitRepository`
  instead of live, in-run device configs — see "Config source: live vs.
  git" above. Still not built: a "build a snapshot from a specific historical
  git commit" variant (useful for "what did routing look like last
  Tuesday") — the current git mode always reads the repository's current
  checked-out state (via `clone_or_pull`), not a pinned commit/ref.
- **UNVERIFIED: the "hundreds/thousands of devices" production-scale
  claim.** Git mode removes the live-SSH bottleneck for building a
  full-fleet snapshot, but nothing in this change has been measured against
  a real coordinator with a snapshot that large — upload time,
  `init_snapshot` parse time, and `list_snapshots_with_metadata` behavior
  with a long history are all unverified at that scale. Every claim in this
  doc about git mode was checked with small (single- or double-digit) file
  counts. A smoke test against a realistically-sized synthetic config set is
  recommended before relying on this for a real production fleet; not done
  as part of this change.
- **Cap-exceeded / zero-match behavior in git mode is a hard failure, not a
  silent truncation.** `collect_git_source_files` raises `ValueError` past
  `MAX_GIT_SOURCE_FILES` and on zero matches, rather than silently uploading
  a partial or empty snapshot — a deliberate "loud failure over silent
  partial data" choice, mirroring the existing "Not built: a loud signal
  when a snapshot init parses zero usable nodes" bullet above (this is an
  earlier-stage version of the same philosophy: catch the empty-snapshot
  case at file-match time, not only later via `row_count: 0`).
- **`batfish-validate-facts`'s `facts_source: git` applies the same
  hard-fail philosophy one layer up, for a different failure class.** Where
  `collect_git_source_files`'s own zero-match/cap-exceeded guard is about
  *which files got matched*, this step's `_build_git_facts_corpus` guards
  *whether a matched file is valid expected-facts YAML* — a file that fails
  to parse, or lacks a top-level `nodes` mapping, raises `ValueError` naming
  the file rather than being silently skipped (which would otherwise leave
  some devices failing with a confusing `node_key_mismatch` purely because
  one sibling file in the repo was malformed). Same posture, one layer
  closer to the data than the file-collection step below it.
- **`docker build`/`up` for `docker/batfish` was verified working in this
  environment** (unlike pyATS's own doc, which flagged this as unverified at
  the time it was written) — the container reaches `healthy`, runs only the
  Batfish coordinator/worker process (no bundled Jupyter notebook — see
  `docker/batfish/docker-compose.yaml`'s `command:` override), and every
  `pybatfish` call shape documented above (`init_snapshot`, `routes`,
  `reachability`, `testFilters`, `list_snapshots`/`delete_snapshot`) was
  exercised against a real running instance, not assumed from pybatfish's
  documentation alone.
- **RESOLVED: Template Editor's `batfish` preview variable could be used to
  write templates that always fail at real workflow runtime.** See "Template
  Editor integration" → "Bug found and fixed" above for the full writeup —
  short version: `batfish.*` is populated only by the editor's own ad-hoc
  query, never by any real workflow step, so a template referencing it
  previewed successfully but failed every device once actually run. Fixed
  with an explicit preview-only warning in `constants.ts`'s
  `BATFISH_VARIABLE` description, a persistent `Alert` in
  `batfish-options-tab.tsx`, and a new "Batfish (per-device steps only)"
  subsection in `jinja-help-dialog.tsx` documenting the real mechanism
  (`parsed.<output_key>` from Extract Facts / Get OSPF Facts / Get BGP Facts
  / Batfish Node/Interface Properties).
- **Deferred by explicit decision, not oversight: wiring Routing
  Table/Path Check/ACL Check results into `device.parsed`.** This would let
  those three steps' results be genuinely usable in `route-on-attribute`/
  Render Jinja Template, closing the gap the bug above was fixed around —
  but it's backend design work (how does a single workflow-level answer
  table map onto N devices for a per-device template render?), not a
  one-line fix, and was explicitly scoped out when the editor bug above was
  fixed. Tracked as an action item in `doc/OPEN_TODOS.md` → "Wire Batfish
  Routing Table/Path Check/ACL Check results into per-device templates".
