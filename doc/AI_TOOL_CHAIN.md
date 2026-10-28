# AI Assistant Tool Chain: execution tools, long chains, PydanticAI

Status: **design notes, nothing built yet.** This file records the reasoning behind letting the
in-app AI assistant run device tasks (run a command, fetch configs, parse them with TextFSM) and
how to keep the door open for (a) chains longer than eight steps over many devices and (b) a later
switch to PydanticAI. Read `doc/ai_integration/AI_ASSISTANT.md` first; this file extends it and
names the invariants it would change.

## 1. Goal

A general assistant that can, on request:

- run a (read-only) command on one or more network devices,
- download configs and parse them (TextFSM / existing parsers),
- chain such results into authoring work (create a Jinja2 template, propose a config change),
- later: troubleshoot across many devices (multi-hop fault finding) with chains well beyond
  eight tool calls.

Constraint from the product owner: **no dedicated workflow** is started for this. The code already
exists in the workflow steps and must be reused.

## 2. Facts about the current code (verified by reading)

| Topic | Finding |
|---|---|
| Loop | `services/ai_assistant/agent_loop.py` is ~106 lines, max 8 tool steps per turn. |
| Providers | Hand-written adapters (`anthropic`, `gemini`, `openai_compat`, ~1000 lines incl. `http_common`, `proxy`); decision "no LiteLLM / no abstraction layer" is in `AI_ASSISTANT.md` §3.1. |
| Tool choke point | `services/ai_assistant/tools/base.py` (rights, redaction, size caps, audit). Tools live in `tools/*.py`. |
| Output contract | SSE events `text`, `tool`, `proposal`, `done` (`events.py`, `chat_service.py`). |
| Step executors | `async def execute(*, config, context, run, artifact_service, node_id, device_sessions) -> list[StepOutcome]`. `StepRunner._execute_step` only looks the executor up in `STEP_REGISTRY` and calls it, so any caller can do the same. |
| What an executor needs | a `WorkflowContext` with devices, a `WorkflowRun` (it reads `run.id`, `run.run_inputs`, `run.triggered_by_id`; artifacts, step results and run events hang off `run.id`), a `DeviceSessionPool`, an `ArtifactService`. |
| Hatchet | Existing workflows (`DeviceGroupExecution`, `dispatch`, `cache_devices`, ...) all wrap workflow runs. A new, thin Hatchet task needs no `Workflow` row and no canvas. |
| TextFSM | Lives in `services/network/netmiko/service.py` and `connection.py`; "run command + parse" can bypass the step wrapper. |

## 3. Invariants this feature touches (decision required)

`AI_ASSISTANT.md` currently states:

- **Rule 3, "No execution tools":** no tool can run a workflow, open an SSH session or push to git.
- **Rule 4, "Untrusted content stays data":** configs, command output and run logs are
  attacker-influenced text. Safety rests on writes being proposal-only and there being no
  execution tools; a prompt-injected model can at worst produce a bad proposal.

A tool that runs a command on a device breaks both. Gerätetext -> model -> SSH command is a textbook
prompt-injection path. **Rules 3 and 4 and the sentence "Tools must be pure reads or proposals" must be
amended in `AI_ASSISTANT.md` before any code is written**, with the mitigations below as the new
invariant.

### Mitigations (proposed; details in §13)

1. **No free command text where avoidable.** Prefer a catalog of named actions
   (`get_device_config`, `run_show_command(device, command, parse)`). Free text only against an
   allow-list (read-only `show ...`; no config mode, `reload`, `copy`, `write`, pipes that write).
2. **User confirmation as the default.** The model does not execute. A tool emits an *execution
   proposal* ("run `show ip int brief` on r1, r2"); the user's click starts the Hatchet task. This keeps
   Rule 4's property: the model never runs anything by itself. A possible later relaxation
   (auto-run of allow-listed read-only commands under an opt-in) is a separate decision.
3. **The assistant is the user.** The task carries the caller's `user_id`; it checks
   `workflows:execute` (or a new `ai_assistant:run_commands`), resolves credentials with
   `acting_user_id`, and is rate limited (`rate_limited(...)`). No super-principal.
4. **Opt-in and redaction unchanged.** Device output is data class C: only after the user's
   data-sharing opt-in, always through the redaction pipeline and size caps.
5. **Errors:** fixed client messages plus an error id, never `str(exc)`.

## 4. Execution path

```
tool (propose_execution)  ->  SSE proposal  ->  user confirms  ->  POST /ai/exec
      -> Hatchet task "AiToolExecution" (thin, own @hatchet.task)
         -> build WorkflowContext from inventory devices
         -> call STEP_REGISTRY[step] or the netmiko service directly
         -> persist result (artifact / handle, see §6)
      -> result handle returned to the chat (SSE/polling)
```

Open design point, **the run shell** (deep dive in §14). Executors need a `WorkflowRun`. Options:

- **A (preferred):** a lightweight `WorkflowRun` with `trigger_type="ai_assistant"` and no
  `workflow_id`. Artifacts, secret redaction (`secret_fields`), run events, retention and audit work
  unchanged. Needs: `workflow_id` nullable, and a check of every place that assumes
  `run.workflow_id` (UI lists, reaper, retention, schedules).
- **B:** a separate `ai_task_runs` table plus a small stand-in object implementing what executors read.
  Less coupling, but artifacts and events must be re-plumbed.

A throwaway, never-committed `WorkflowRun` is not enough: artifacts and step results need a real `run_id`.

## 5. Why not PydanticAI as a replacement right now

PydanticAI is sensible in principle, but replacing the loop does not shrink the code:

- The loop is 106 lines. The large parts of the assistant are app-specific and would stay or be
  rebuilt: SSRF policy for base URLs (`base_url_policy.py`), error mapping (429, context overflow,
  truncated stream -> `provider_unavailable`), per-user keys and proxy key, redaction and opt-in per
  data class, SSE events and the proposal concept.
- It is an abstraction layer, i.e. the thing the "no LiteLLM" decision argued against (tool-calling
  quirks, local models with weak tool calls, dependency surface).
- New dependency with its own release cadence. **Python 3.14 compatibility is unchecked.**
- The central safety property ("every tool goes through one choke point") is easier to guarantee in
  our own 106 lines.

What it would give: typed tool args/outputs with validation retries, ready streaming and tool loop,
and multi-agent / graph primitives. Typed tool args are available cheaply without it (§7).

**Decision (proposed):** extend the existing loop first; do not replace it. Reassess PydanticAI
when a concrete need appears (see §8 triggers).

## 6. Designing so that long chains and many devices stay possible

The requirement: do not block the path to PydanticAI, and allow chains beyond eight steps over many
devices later. The real bottleneck there is **context size and state**, not the choice of library. These
rules apply to either loop.

### 6.1 Result handles instead of raw output in the prompt

A config can be thousands of lines; 50 devices cannot be pasted. Every execution tool returns a
bounded summary plus a **handle**:

```json
{ "handle": "res_8f3a", "kind": "parsed_table", "device": "r1",
  "rows": 214, "preview": [ ... first N rows ... ], "truncated": true }
```

Raw output and parsed data are stored as artifacts bound to the AI task run (§4, option A). Follow-up
tools take handles, not payloads: `query_result(handle, filter, fields, limit)`,
`diff_results(handle_a, handle_b)`, `fetch_slice(handle, offset, limit)`. This is the existing
"large content is truncated with an explicit marker and fetchable via a tool" principle, made
systematic. Handles must be validated against the caller (same user, same conversation) in the choke point.

### 6.2 Condensing tools

Prefer tools that return answers, not output: "next hop for X", "interfaces with errors",
"BGP neighbours not established". They cut steps and tokens, and help any loop.

### 6.3 Parallelism for many devices

A tool accepts a device list and fans out inside one tool call (bounded concurrency, per-device
result record, partial failures reported per device). One step then covers 50 devices; the model
does not issue 50 calls. For truly large sweeps (hundreds of devices) hand the work to Hatchet and
return a handle that is polled.

### 6.4 Configurable step budget and cheap extensions

The cap of 8 stays the safe default but becomes a per-surface setting (e.g. the "general" surface
gets a higher cap, with a hard ceiling and a total token/time budget). Bundling tools
(`get_and_parse_config`) reduce steps without raising the cap.

### 6.5 State outside the prompt

For chains that outgrow one chat turn: a persisted *task scratchpad* (conversation-scoped record of
hypotheses, visited devices, finding summaries, handles). The model reads/writes it through tools
(`note`, `get_notes`). Old tool results can then be dropped from the prompt (summarise + keep handles)
without losing the thread. This also gives the resume point if a turn is interrupted.

### 6.6 Long-running work as Hatchet tasks

A long investigation that must survive a closed browser tab runs as a Hatchet task that calls the
same tool functions and writes progress to the scratchpad / conversation. Same code, different driver.

## 7. Loop-agnostic structure (the "do not block PydanticAI" rules)

Keep these seams stable so the loop can be swapped behind them:

1. **Tools are plain functions with Pydantic input/output models**, in `tools/*.py`, knowing nothing
   about the loop. The loop derives the provider tool schema from the model (JSON Schema). A
   PydanticAI agent can register the same functions unchanged.
2. **Validation errors go back to the model** as tool errors and count against the step cap
   (already required for local models); this replaces PydanticAI's validation-retry feature.
3. **One choke point** (`tools/base.py`) does rights, opt-in, redaction, size caps, audit, handle
   ownership. No such logic inside the loop. If PydanticAI is adopted, tools are registered through a
   thin adapter that calls this choke point.
4. **A narrow runner interface** between `chat_service` and the loop, roughly
   `run(messages, toolbox, limits, user_ctx) -> AsyncIterator[AssistantEvent]`. Providers and the
   event stream (`text`, `tool`, `proposal`, `done`, plus new `exec_proposal`/`progress`) are the
   contract. Chat service, persistence and frontend depend only on this.
5. **Providers stay behind the adapter interface.** If PydanticAI is adopted it should sit on top
   of our adapters or our already policy-checked HTTP client, not bypass SSRF policy, user keys or the
   proxy key.
6. **No vendor- or model-specific branches** (existing rule).

With these, the swap is local to the runner implementation; tools, safety, run shell and handles move
over unchanged.

## 8. When to reconsider PydanticAI (triggers)

Start a small spike only when at least one is true, with concrete failing examples:

- Tasks routinely need multi-agent delegation (planner / parser / author) with hand-offs.
- Plans need persisted graph state with branching and resume that the scratchpad (§6.5) handles badly.
- Typed outputs and validation retries become a recurring source of bugs that §7.1/§7.2 do not fix.
- A fourth provider is requested (the "revisit if" condition of the no-abstraction decision).

Spike checklist: Python 3.14 compatibility and pinned version, a custom model wrapping our adapters,
all tools through the choke point, identical SSE events, 429/overflow/truncation mapping, SSRF policy
intact, no extra network egress.

## 9. Worked examples

- **Fetch config -> parse -> Jinja2 template** (short chain, 3-4 steps, works with the current loop):
  `get_device_config(r1)` returns a handle + preview; `parse_output(handle, template)` returns a parsed
  handle + preview; `propose_template(...)` emits a template proposal. User confirms the execution
  proposal at step 1 and the template diff at the end.
- **Fault finding across devices** (grey zone): small scope (3-5 devices, 5-10 calls) fits a raised
  step cap. Large scope needs §6.1 handles, §6.2 condensing tools, §6.3 fan-out and §6.5 scratchpad.
  Either way the autonomy of the model raises the weight of the allow-list, rate limits and
  confirmation (§3).

## 10. Implementation order (tools §12, security §13, run shell §14)

1. Amend `AI_ASSISTANT.md` invariants (Rules 3 and 4) with §3.
2. Run shell decision (§4 A vs B) and, for A, make `workflow_id` nullable and audit its users.
3. Result handles + artifact storage + `query_result` / `fetch_slice` (§6.1).
4. Execution proposal flow + thin Hatchet task + allow-list + rights + rate limit.
5. Tools: `get_device_config`, `run_show_command`, `parse_output`.
6. Per-surface step budget, fan-out inside tools, condensing tools.
7. Scratchpad and (optional) Hatchet-driven long investigations.
8. Runner interface extraction (§7.4) if not already clean; PydanticAI spike only on §8 triggers.

## 11. Open questions

- Confirm every execution, or auto-run allow-listed read-only commands under an opt-in?
- Run shell A or B (§4)?
- New permission `ai_assistant:run_commands`, or reuse `workflows:execute`?
- Exact allow-list grammar for commands, and where it is enforced (choke point).
- Retention for AI task artifacts (reuse `RUN_RETENTION_*`?).
- Does the "general" surface need its own prompt and toolbox in `surfaces.py`?

## 12. Tools (deep dive)

### 12.1 What exists

A tool is `Tool(name, description, input_model, handler)` (`tools/base.py`). `Toolbox.execute`
already is the choke point: it validates the input with the Pydantic model (errors go back to the model
as text), runs the handler, contains every exception (logged, generic message to the model),
redacts the output, detects `not_shared` markers and truncates at `MAX_TOOL_OUTPUT_CHARS` (20 000).
`ToolContext` carries `user_id`, `redactor`, `sharing` (the opt-in) and `audit_refs`, and is built per
request. The handler contract is `async (ToolContext, args) -> ToolOutput`, where `ToolOutput` has
`content` (to the model), `proposal` (to the client only), `truncated` and `withheld`.
The module docstring states the rule "pure read or proposal; nothing here executes or touches a
device". The new tools change that rule (§13).

### 12.2 Tool classes

| Class | Examples | Executes? | Goes through |
|---|---|---|---|
| Read | `list_inventory`, `query_result`, `fetch_slice`, `get_notes` | no | today's path |
| Proposal | `propose_template`, `propose_config_change`, **`propose_execution`** | no | proposal event, user confirms |
| Execution (new) | `get_device_config`, `run_show_command`, `parse_output` | yes, on the user's click | Hatchet task (§4), never inline in the handler |

Important: the **handler of an execution tool does not touch a device**. It validates and returns an
`exec_proposal`; the device access happens in the Hatchet task after the user's confirmation (or, if
auto-run is later allowed, after the policy check in §13). This keeps `Toolbox.execute` free of
long-running I/O (the loop has a request timeout) and keeps the loop-agnostic property (§7).

### 12.3 Proposed tool set (first increment)

| Tool | Input (Pydantic) | Result to the model |
|---|---|---|
| `propose_show_command` | `devices: list[str]` (max N), `command: str`, `parse: bool` | proposal only; after confirmation the result arrives as a handle message (§12.5) |
| `propose_get_config` | `devices`, `format: running\|startup` | same |
| `parse_output` | `handle`, `parser: textfsm\|genie`, `template?` | new handle + preview + row count |
| `query_result` | `handle`, `filter?`, `fields?`, `limit` | bounded rows |
| `fetch_slice` | `handle`, `offset`, `limit` | bounded text |
| `diff_results` | `handle_a`, `handle_b` | bounded diff |
| `propose_template` / `propose_config_change` | existing / new | proposal with diff |

Naming: tools that need a click are named `propose_*` so the model and the UI see that they do not
return data immediately. The model gets the data in a later turn (see 12.5).

### 12.4 Reuse of existing code

Per task the Hatchet task calls one of:

- the step executor from `STEP_REGISTRY` (`run-command`, `get-device-configs`) with a config built by
  the tool layer from the validated tool input, **never** from raw model text (so `execution_mode`,
  `write_config_after_execution`, `auto_confirm_prompts`, `dry_run` and similar flags are fixed by the
  tool, not model-controlled; `run-command` has a `config_mode` that can write config and must be
  unreachable), or
- the netmiko service directly (`services/network/netmiko/service.py`) for "command + TextFSM", which
  avoids the `WorkflowContext` plumbing for plain reads.

Prefer the second where the step wrapper adds nothing; prefer the executor where artifacts,
credentials resolution (`resolve_ssh_credential`) and per-device outcomes are wanted. Decide per tool
and write the choice in the tool module docstring.

### 12.5 Asynchronous results and the conversation

A confirmed execution produces a result that arrives after the model turn ended. Options:

- **A (preferred):** the Hatchet task writes the result handle(s) + preview to the conversation as a
  *tool-result message* tied to the original tool call id; the UI shows progress via `progress`
  events, and the loop continues in the next turn ("continue" is automatic when the result lands, or
  the user sends the next message). Needs: a conversation store that accepts a late tool result
  (`ai_conversations` / `conversation_service.py`) and a resume path in `chat_service`.
- **B:** the execution proposal is awaited inside the turn (the SSE stream stays open while the user
  confirms and the task runs). Simple, but ties the turn to a held connection and the loop timeout,
  and breaks for long tasks. Use only for a first prototype.

### 12.6 Tool design rules

1. Input models `extra="forbid"`, bounded lists (max devices per call), bounded string lengths,
   enums instead of free text wherever possible.
2. Output always bounded; large data becomes a handle (§6.1). The preview size is a constant, not a
   parameter.
3. Every device-related value passes `ctx.sharing` (class B/C), like `run_tools.py`.
4. IDs and handles the model supplies are **re-authorised on every use** (ownership check in the
   choke point); the model never receives a capability it can pass on to another user.
5. No tool returns secrets; credential references are by name (`resolve_ssh_credential`), the secret
   is resolved inside the task and registered for redaction (`unwrap_secret`).
6. Each tool has a unit test for: invalid input, opted-out sharing (`not_shared`), truncation, and
   authorisation failure.

## 13. Security (deep dive)

### 13.1 Threat model

Assets: device access (SSH credentials, write access to network gear), device data (configs,
topology), other users' data, the Redis/DB state.

Attackers: (1) **Prompt injection** through anything the model reads: device banners, interface
descriptions, config comments, SNMP locations, Nautobot fields, run logs, file contents. (2) A
legitimate low-privilege user trying to escalate through the assistant. (3) A confused model making a
wrong but "valid" call (large blast radius, repeated calls, wrong device).

Core property to preserve: **the model's text never becomes a device-side effect without a gate that
the model cannot satisfy by itself.**

### 13.2 Layers

| Layer | Control | Where |
|---|---|---|
| 1. Capability | Execution tools are offered only if the operator enabled them, the user has the permission, and the surface is allowed. Off by default. | settings/policy (`policy.py`), `surfaces.py` |
| 2. Command policy | Allow-list of read-only commands; deny list for config mode, `reload`, `copy`, `write`, `delete`, `erase`, `debug`, `terminal`, redirections and pipes that write, command chaining characters (`;`, `&&`, newline). Matching on the normalised command, per device platform. | one module, called from the tool **and** again in the Hatchet task (defence in depth: the task never trusts the queue payload) |
| 3. Fixed flags | The tool builds the step config; mode flags are constants. No model-controlled `config_mode`. | tool module |
| 4. Confirmation | The click starts the task; the confirmation shows the exact devices and command. The task stores a hash of what was confirmed and refuses a payload that differs. | `POST /ai/exec`, task |
| 5. Authorisation | `user_id` from the JWT of the confirming request (not from the payload), `workflows:execute` or `ai_assistant:run_commands`, device visibility via the user's inventory access. | router + task |
| 6. Credentials | Resolved with `acting_user_id`; only credentials that user may use. Secrets never in the prompt, the payload, logs or results (redaction + `secret_fields`). | `resolve_ssh_credential` |
| 7. Limits | Max devices per call, max commands per call, per-user `rate_limited("ai_exec", ...)`, per-conversation budget, per-device timeout, Hatchet execution timeout, `device_sessions` pool closed after the task. | router + task |
| 8. Output | Class C data only after opt-in; redaction on every result; handle storage per user. | choke point |
| 9. Audit | One audit record per confirmed execution: user, conversation id, device ids, command hash, task id, outcome. Ids only, no content (existing `audit_refs` principle). A `WorkflowChange`-style record is not needed for reads. | `audit.py` |

### 13.3 Prompt injection specifically

- The tool descriptions and the system prompt tell the model that tool output is untrusted data
  (already the case); this is **not** a control, only a hint.
- Real controls are layers 2 to 4: even a fully compromised model can only *propose* an allow-listed
  read command on devices the user can already access, which the user then sees verbatim.
- The confirmation UI must show the **actual command and devices**, not the model's description of
  them, and must not render untrusted text as markdown/links in that dialog.
- Output that came from a device is wrapped/marked as data when it is put back into the conversation
  (existing practice for run logs); a handle preview is treated the same.
- Chained attacks: a result handle from device A being used by a tool call on device B is allowed
  (read-only), but a *write* path (`propose_config_change` and later deploy) always goes through the
  existing save path with RBAC and `WorkflowChange`. The assistant has **no** deploy tool; deployment
  stays a normal workflow run by the user.

### 13.4 Auto-run of allow-listed reads (later, optional)

If confirmation proves too slow for investigations (many reads across devices), allow auto-run only
when all hold: per-user opt-in in AI settings, operator switch, command on the strict read allow-list,
device count within a small limit, and rate limit/budget per conversation. Everything else still needs
a click. This is a separate decision (open question in §11) and must be documented in
`AI_ASSISTANT.md` as a deliberate exception to the rule that the model never executes.

### 13.5 Changes to existing documents and checks

- `AI_ASSISTANT.md` Rules 3 and 4 and the `tools/base.py` docstring ("nothing here executes ... touches
  a device") are rewritten to: *the model never executes; confirmed, policy-checked read tasks run in
  a Hatchet task as the user.*
- New permission, if chosen: `ai_assistant:run_commands`. It is not in the viewer set
  (`VIEWER_PERMISSIONS`); document it in `doc/claude/auth.md`.
- Guard scripts: extend or add a check that `services/ai_assistant/` imports netmiko/steps only through
  the one execution module, so no other tool can open a device session (same idea as
  `check_text_sql.py`).
- Tests: command policy table tests (allowed, denied, bypass attempts: case, whitespace, unicode
  homoglyphs, `|` and `;`, abbreviations like `conf t`, `wr`), payload-tamper test (confirmed hash
  mismatch), RBAC test (user without permission cannot confirm), secret-leak test on results.

## 14. Run shell (deep dive)

### 14.1 What the executors really require

Verified in the code:

- `WorkflowContext` requires `run_id: str` and `workflow_id: str` (`models/workflow_context.py`).
- Executors read `run.id`, `run.run_inputs` and `run.triggered_by_id` (`get-device-configs`,
  `run-command`: credential resolution runs `acting_user_id=run.triggered_by_id`). A few common helpers
  read `run.workflow_id` and load the workflow (`workflow_steps/common/notification_context.py`).
- Artifacts are keyed by the **run uuid** (`FilesystemArtifactService`: `meta["run_id"]` is the uuid);
  retention deletes by `delete_for_run(run_uuid)` and purges as **orphan** every artifact whose run uuid
  is not in `valid_run_uuids` once it is older than a grace period. So artifacts of a run that has no
  row in `workflow_runs` would be deleted by the orphan sweep.
- Log-attribute files live under `<root>/<workflow_id>/<run_uuid>/` (`log_attribute_files.py`).
- `workflow_runs.workflow_id` is `NOT NULL`, FK to `workflows.id`, `ondelete=CASCADE`.
- `RunService` calls `_assert_workflow_access(run.workflow_id, user_id)` in about a dozen places (read,
  cancel, delete, events, artifacts), plus the dashboard, schedules and the AI `run_reader`.

### 14.2 Option A: real `WorkflowRun` with a hidden system workflow

Instead of making `workflow_id` nullable (which breaks all the above), create **one system workflow
per user** (or one global), e.g. name `__ai_assistant__`, flagged so it is hidden from lists, and
create the AI task runs as normal `WorkflowRun` rows with `trigger_type="ai_assistant"` under it.

- Pros: no schema change to `workflow_runs`; artifacts, orphan sweep, retention, redaction, run events,
  audit and `_assert_workflow_access` work unchanged; the existing runs page can show these runs
  (filter by `trigger_type`) so users can inspect what the assistant did; `delete_run_dir` paths stay valid.
- Cons: a "fake" workflow object must be excluded from workflow lists, schedules, exports and the
  git-versioned workflow store; per-user ownership of the hidden workflow must be settled
  (a per-user row keeps `_assert_workflow_access` meaningful; a global one needs an explicit rule).
- Needs: a flag column on `workflows` (e.g. `is_system`/`hidden`, **nullable-safe add** via
  `AutoSchemaMigration`) and filters in the workflow list/schedule/export queries; a new
  `trigger_type` value (the column is `String(20)`, no enum; `ai_assistant` is 12 chars); a repository
  method `create_ai_task_run(user_id, device_ids)`.

### 14.3 Option B: separate `ai_task_runs` table

A new table (`user_id`, `conversation_id`, `status`, `task_ids`, timestamps, `uuid`) and a small adapter
object exposing what the executors read (`id`, `uuid`, `run_inputs`, `triggered_by_id`,
`workflow_id`).

- Pros: no fake workflow, no pollution of workflow queries, clean ownership by user and conversation.
- Cons: artifacts need the run uuid to be in `valid_run_uuids` for the orphan sweep, so the retention
  service must be extended to include these uuids; run events, log-attribute paths and the runs UI
  must be re-plumbed or duplicated; any executor or helper that does `isinstance`/ORM access on
  `WorkflowRun` or `object_session(run)` (both seen in the executors) would break with an adapter,
  because `object_session(run)` returns the DB session from the ORM instance.

`object_session(run)` is used by `get-device-configs` and `run-command`; this alone argues for a real
ORM row, i.e. option A, or an ORM-mapped class for B.

### 14.4 Option C: no run at all for plain reads

For "command + TextFSM" and "get config" the netmiko service can be called directly (§12.4) with
credentials resolved by the tool layer. Results are stored as AI-owned artifacts. No `WorkflowRun`.
Cons: two code paths for storing results, no run-level audit, and artifact ownership/retention must be
built for AI artifacts separately. Reasonable as a first spike for single-device reads, not as the
end state.

### 14.5 Recommendation

**Option A with a hidden system workflow per user**, revisited after a spike that checks:

1. which workflow queries need the hidden flag (lists, schedules, exports, dashboard, git versioning),
2. that `_assert_workflow_access` passes for the owner and rejects others,
3. that retention, the reaper (`run_reaper`) and `purge_retention` treat the runs correctly
   (they must not be reaped as "stuck" while a long investigation runs; they must be purged after
   `RUN_RETENTION_DAYS`),
4. that the runs page filters or labels `ai_assistant` runs.

Granularity: **one run per confirmed execution** (not per conversation), so the retention and the
reaper rules fit short-lived runs; the conversation links to the run ids (`audit_refs`). Result handles
(§6.1) point to artifacts of those runs.

### 14.6 Hatchet side

- A new, thin `hatchet.workflow(name="AiToolExecution", input_validator=...)` in
  `backend/hatchet/workflows/`, registered in the worker like the others; input carries only
  `run_id`, `user_id`, `confirmation_hash`, the validated tool name and arguments; no secrets, no free
  command text beyond the already policy-checked argument.
- Inline comment on queue/worker settings is required by the project rules for Hatchet code
  (`doc/claude/development.md`, "Python Conventions"). The task sets `execution_timeout` and uses
  bounded concurrency per user so one user cannot saturate the worker slots.
- The task opens its own DB session (`SessionLocal`), runs the executor/service, always closes the
  `DeviceSessionPool`, writes the result handle, and finalises the run status. On any exception: fixed
  message plus `error_id`, the stack in the worker log (same pattern as `run_device_group`).
- Cancel: the same owner-only cancel rule as any run (`triggered_by_id`).

### 14.7 Open points specific to the run shell

- Hidden workflow per user vs one global system workflow (ownership and access rule).
- Whether `WorkflowContext.workflow_id` gets the hidden workflow id or a fixed string such as
  `"ai-assistant"` (helpers that load the workflow by id would fail on the string).
- Whether AI runs appear in the user's run list by default.
- Retention class for AI task runs (shorter than workflow runs?).
