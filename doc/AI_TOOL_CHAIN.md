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
- **start workflows that an administrator has released for the assistant** (§16). Such workflows
  encapsulate more complex procedures that were designed, tested and approved in advance, so the
  assistant can rely on them working and on the shape of their result,
- later: troubleshoot across many devices (multi-hop fault finding) with chains well beyond
  eight tool calls.

Two ways to act, deliberately kept apart:

| Way | For | Who defines it | Risk profile |
|---|---|---|---|
| **Ad-hoc tools** (run a read-only command, fetch and parse a config) | exploration, one-off questions | developers (tool code, allow-list) | bounded by the command policy (§13) |
| **Released workflows** | repeatable, complex or state-changing procedures | workflow authors, approved by an admin | bounded by the review the admin did |

Constraint from the product owner: **no dedicated workflow is created or started for the ad-hoc
tools.** The code already exists in the workflow steps and must be reused. Starting an *existing,
released* workflow is a separate capability and is allowed (§16).

## 1a. Guiding principle: tools first

The tools matter at least as much as the agent loop, and in practice more.

- **The loop is replaceable, the tools are not.** The loop is ~106 lines and can later be swapped for
  PydanticAI (§7). The tools hold the app logic: what may run, with whose rights, what the result looks
  like, what the model gets to see.
- **Safety lives in the tools.** The model can only do what a tool allows. Allow-list, confirmation,
  rights check and redaction sit in the tool layer and the choke point (§13). A weak loop yields bad
  proposals; a badly built tool can be a vulnerability.
- **Answer quality depends on the tools.** Whether a multi-device investigation works depends on
  condensed results, handles and fan-out inside tools (§6), not on the loop. A mediocre model with good
  tools beats a strong model with tools that flood the context.
- **Most of the work is tool infrastructure**: run shell, Hatchet task, handle storage, command policy.

Consequences for the work plan:

1. Build and test the tools first, **without an LLM**: inputs, rights, `not_shared`, truncation, policy
   bypasses (§12.6, §13.5).
2. Make them callable by hand early (a test harness or internal endpoint) to design handles and
   previews before a model is involved.
3. Treat tool names, descriptions and input fields as prompt engineering: few, clearly separated tools
   work better than many overlapping ones.
4. Tune the model and loop afterwards. Test with the smallest model the app must support; weak local
   models misfill parameters even with good tools (see "Local models" in `AI_ASSISTANT.md` §3.1).

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

A tool that runs a command on a device breaks both, and so does a tool that starts a workflow (§16). Gerätetext -> model -> SSH command is a textbook
prompt-injection path. **Rules 3 and 4 and the sentence "Tools must be pure reads or proposals" must be
amended in `AI_ASSISTANT.md` before any code is written**, with the mitigations below as the new
invariant.

*Status 2026-10-28: done. Principles 2 to 4, §3.5 (tool rule and naming), the §5 prompt-injection row,
the §17 injection paragraph and the `tools/base.py` docstring now state: no tool executes; effects are
`propose_*` proposals carried out by the confirmed-execution endpoint. The hardening test for the
`general` surface is still to be written with the first tool.*

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

## 10. Implementation order (tools §12, security §13, run shell §14; step 0 in §10a; layout §17)

0. **First increment: Batfish read tools (§15.4, §10a).** Proves the tool layer without touching a
   device. Needs no change to Rules 3 and 4 as long as the tools only read from the Batfish service;
   they still need the data-class opt-in and redaction.
1. Amend `AI_ASSISTANT.md` invariants (Rules 3 and 4) with §3 (before any SSH tool).
1b. Released-workflow tools (§16): list, describe, start, status and result. Independent of the run shell
   (they create ordinary runs), so they can ship before the ad-hoc execution tools.
2. Run shell decision (§14): recommended is a real `WorkflowRun` under a hidden system workflow; do
   **not** make `workflow_id` nullable (§14.1 lists what depends on it).
3. Result handles + artifact storage + `query_result` / `fetch_slice` (§6.1). If step 0 is done, the
   handle mechanism already exists and is reused here.
4. Execution proposal flow + thin Hatchet task + allow-list + rights + rate limit.
5. Tools: `get_device_config`, `run_show_command`, `parse_output`.
6. Per-surface step budget, fan-out inside tools, condensing tools.
7. Scratchpad and (optional) Hatchet-driven long investigations.
8. Runner interface extraction (§7.4) if not already clean; PydanticAI spike only on §8 triggers.

### 10a. Step 0 in detail: Batfish read tools as the first increment

Why first: these tools read from a Batfish service and open no SSH session, so they carry the lowest
risk of all execution-like tools, and they exercise everything the later tools need.

What step 0 proves, in order:

1. **Tool module and registration:** a new `tools/batfish_tools.py` with typed Pydantic inputs
   (`extra="forbid"`, bounded lists) and a "general" surface in `surfaces.py` that offers them.
2. **Standard result envelope:** `{rows, total_rows, truncated}` plus a preview size constant, shared
   helpers next to `tools/base.py` (§15.2 items 2 and 8).
3. **Handles:** results above the preview size are stored and referenced by handle; `query_result` and
   `fetch_slice` work on them; ownership is checked on every use (§6.1, §12.6). For step 0 the storage
   can be a per-conversation store (no run shell needed because nothing is executed on a device);
   decide here whether it moves to run artifacts later (§14).
4. **Redaction and opt-in:** each tool is labelled with its data class (topology, configs are class B/C)
   and returns `not_shared` when the user has not opted in (`run_tools.py` pattern).
5. **Audit and limits:** ids only in `audit_refs`; `rate_limited(...)` on the endpoint; per-turn step
   cap as today.
6. **Tests without an LLM:** invalid input, opted-out sharing, truncation and handle ownership,
   authorisation failure (§12.6).

Candidate tools, in order of value (names follow §15.4; wrap the existing Batfish service code, do not
call Batfish a second way):

| Tool | Notes |
|---|---|
| `get_routes` | `prefix_match_type=LONGEST_PREFIX_MATCH` answers "which route does this IP use" |
| `get_traceroute` | `trace_format=summary` by default, `max_traces` bounded |
| `get_bgp_session_status` | status per session, condensed |
| `get_interface_properties` | projected to useful fields |
| `analyze_acl` / `check_reachability` | bounded result, summary first |
| catalog tool (later) | allow-listed questions only, each with a data-class label and size policy |

Preconditions to check first: which Batfish reads exist as services versus only as step executors
(`batfish_*` steps); where the snapshot comes from (a snapshot made by a workflow run, selected by id,
or created from inventory) and who may use it. The assistant must not take a filesystem path or a
network destination from the model (§15.3).

Exit criteria for step 0: the model can answer "which route does 10.1.2.3 use on r1, and where does a
packet to it go?" with at most 3 tool calls, no result above the preview size enters the prompt, and an
opted-out user gets `not_shared` for every tool.

## 11. Open questions

Decided on 2026-10-28, see §19: confirmation policy, run shell, permission, execution location, handle
storage, released-workflow rules. Still open:

- Exact allow-list grammar for device commands, and where it is enforced (choke point plus the
  execution module, §13.2).
- Retention and size limits for handles (§19 D6); behaviour when Redis is unavailable.
- Does the "general" surface need its own prompt and toolbox in `surfaces.py`? (Probably yes: new
  builder and prompt; check whether `surface` is a closed set, §18 fact 8.)
- The items in §14.7, §16.9 and §17.5 that §19 does not settle.
- Exact permissions and rate limits of `routers/netmiko.py` (to be read before phase 3, §18 fact 11).

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
7. **Naming (pinned by `tests/unit/test_ai_hardening.py`, see `AI_ASSISTANT.md` §3.5):** reads use
   `get_` / `list_` / `search_` / `describe_` / `query_`; every tool that proposes an effect starts with
   `propose_`; no tool name starts with `run`, `trigger`, `execute`, `start` or `delete`. Hence
   `get_traceroute` (not `run_traceroute`) and `propose_workflow_run` (not `start_workflow`). Names of
   the Batfish MCP server's tools in §15 are quoted from that project and are not ours.

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

## 15. Reference study: the Batfish MCP server

Source: `batfish/pybatfish`, `pybatfish/mcp/server.py` (~1770 lines, Apache-2.0, marked **beta**;
FastMCP, stdio transport, entry point `batfish-mcp`). It is not in `batfish/batfish`. Read at the
default branch on 2026-10-28. We use it for ideas on tool design only; we do not adopt its code, its
transport or its trust model.

### 15.1 Tool surface (about 40 tools)

| Group | Tools |
|---|---|
| Sessions / snapshots | `register_session`, `list_sessions`, `get_server_info`, `list_networks`, `set_network`, `delete_network`, `list_snapshots`, `init_snapshot`, `init_snapshot_from_text`, `delete_snapshot`, `fork_snapshot`, `generate_dataplane` |
| Diagnostics of parsing | `get_parse_warnings`, `get_init_issues`, `get_file_parse_status`, `get_vi_conversion_status`, `get_vi_conversion_warnings`, `get_undefined_references`, `get_defined_structures`, `get_unused_structures` |
| Forwarding analysis | `run_traceroute`, `run_bidirectional_traceroute`, `check_reachability`, `detect_loops`, `analyze_acl`, `search_filters`, `compare_filters` |
| Routing | `get_routes`, `compare_routes`, `get_bgp_rib`, `get_evpn_rib`, `get_lpm_routes`, `get_bgp_session_status`, `get_bgp_session_compatibility`, `get_bgp_peer_configuration`, `get_bgp_process_configuration` |
| Inventory | `get_node_properties`, `get_interface_properties`, `get_ip_owners`, `get_edges` |
| Escape hatch | `list_questions`, `run_question` |

### 15.2 Patterns worth copying

1. **Mostly one tool per intent, plus a generic escape hatch.** Frequent questions get a dedicated tool
   with named, typed parameters; everything else goes through `run_question(question, parameters)` with
   `list_questions` for discovery, and unknown names are rejected with a pointer to `list_questions`.
   This keeps the tool list from growing without bound while nothing is unreachable.
   *For us:* dedicated tools for the 5 to 10 common reads, one catalog-style tool for the rest. Our
   escape hatch must be an allow-listed catalog (§13), never free text.
2. **Output shaping is a parameter of the tool**, not a global cap. `max_rows` turns a bare array into
   `{"rows", "total_rows", "truncated"}`, so the model sees that data was cut and by how much.
   `run_traceroute(trace_format=text|structured|summary, max_traces)`: `summary` collapses identical
   (disposition, node path) traces into counts. That is a **condensing tool** in the sense of §6.2.
   *For us:* make `{rows, total_rows, truncated}` our standard result envelope and add summary modes
   where raw data is large. Their `max_rows` default is 0 = unlimited; ours must default to a safe cap
   (their server has no equivalent of `MAX_TOOL_OUTPUT_CHARS`).
3. **Hide deprecated or redundant columns** (`_drop_legacy_nexthop_columns`): less noise and fewer
   tokens for the model, no loss of information. *For us:* project parsed output to the useful fields.
4. **Explicit state in every call.** Every analysis tool takes `network` and `snapshot` and sets them
   on the session itself (`_analysis_session`), so the model never relies on hidden "current snapshot"
   state and calls are order-independent. *For us:* tools take explicit device list / handle, never an
   implicit "current device".
5. **Docstrings are the prompt.** Each tool has a docstring with a purpose sentence, `:param` lines with
   examples (`'10.0.0.1'`, `'bgp,ospf'`, `'1024-65535'`) and a `:return:` shape, and the server has an
   `instructions` string telling the model where to start. *For us:* same discipline for `Tool.description`
   and for the field `description=` in the Pydantic input models.
6. **Diagnostics as first-class tools** (`get_parse_warnings`, `get_init_issues`, undefined references):
   the model can check whether its input was understood before reasoning about results.
   *For us:* a "was the output parsed?" signal on parse results (parser used, rows, unparsed lines).
7. **Bidirectional / compare variants** (`run_bidirectional_traceroute`, `compare_routes`,
   `compare_filters`) fold a common two-call pattern into one call and save steps (§6.4).
8. **Small helper layer** for JSON handling (`_df_to_json`, `_json_default` sorts sets, strings the rest)
   so tool bodies stay short. *For us:* shared result-serialisation helpers next to `tools/base.py`.

### 15.3 What we deliberately do differently

| Their choice | Our choice | Why |
|---|---|---|
| Every parameter is a string, including lists and JSON objects (`nodes: str`, `extra_args: str = "{}"`) parsed in the tool | Typed Pydantic input models (lists, enums, bounded ints) with `extra="forbid"` | validation errors go back to the model (§12.6); fewer malformed calls from weak models |
| `max_rows=0` means unlimited, truncation is opt-in | Output always bounded, handles for the rest (§6.1) | a multi-device run would flood the context |
| No users, rights, redaction, audit; trust model of a local stdio process | RBAC per call, opt-in data classes, redaction, audit, rate limits (§13) | multi-user server with device access |
| Process-global session registry (`_session_configs`, `_session_cache`) | Request-scoped `ToolContext`, handles owned per user | tenancy and testability |
| `init_snapshot(snapshot_path)` reads an arbitrary local path | No tool takes a filesystem path from the model | path traversal / data exfiltration; snapshots come from our own steps (`batfish_init_snapshot`) |
| `register_session(host, ...)` lets the model point the server at another host | No tool lets the model choose a network destination | SSRF policy (`core/safe_urls.py`); sources are admin-configured |
| Errors are raised exceptions, FastMCP renders them | `ToolOutput(is_error=True)` with a fixed message, details in the log | no internal text to the model or client |
| Pure analysis server: no tool changes a device | Same for the first increment; writes only as proposals | §13 |

### 15.4 Overlap with our existing Batfish steps

We already have `batfish_init_snapshot`, `get_batfish_devices`, `batfish_node_properties`,
`batfish_interface_properties`, `batfish_routing_table`, `batfish_ospf_facts`, `batfish_bgp_facts`,
`batfish_path_check`, `batfish_acl_check`, `batfish_extract_facts`, `batfish_validate_facts`. The
assistant tools should wrap the same service code, not call Batfish a second way. Candidate first set,
roughly in the order of value: `get_routes` (with `prefix_match_type=LONGEST_PREFIX_MATCH` for "which
route does this IP use"), `get_traceroute` (summary mode), `get_bgp_session_status`,
`get_interface_properties`, `analyze_acl`, `check_reachability`, plus a catalog tool for the rest.
These are reads against a Batfish service, so they are the lowest-risk execution-like tools: they touch
no device. They are a good **first increment to prove the tool layer** (handles, envelope, redaction,
audit) before the SSH-based tools exist. Batfish data still counts as data class B/C (topology,
configs) and goes through the opt-in.

### 15.5 Open questions from this study

- Which Batfish reads does the existing code already expose as services (versus only as step
  executors)? Wrap services where they exist; extract a service where only an executor exists.
- Snapshot lifecycle for the assistant: reuse a snapshot made by a workflow run (by handle/id) or let a
  tool create one from the current inventory? The reference server leaves this to the model; we should not.
- Do we expose a generic `run_question` catalog at all? Useful for reach, but every entry then needs a
  data-class label and a size policy (§12.6).

## 16. Starting released workflows

### 16.1 Idea

An administrator marks selected workflows as **released for the assistant**. The assistant can list
them, read what each one does, start one with validated inputs and read its result. The workflow
itself is ordinary, built and tested in the normal editor, so complex procedures (collect, parse,
compare, report, even change steps) are written once by people and the model only chooses and
parameterises them. This is the safe way to give the assistant powerful abilities: **the model selects,
the admin has reviewed.**

It also removes a problem from §14: a released workflow runs as a normal `WorkflowRun` under its own
`Workflow`, so the hidden system workflow is not needed for this path.

### 16.2 What "released" means

- A flag set only by an administrator (P3-style rule in `doc/claude/auth.md`: changes to what the
  assistant may execute are admin-only). Proposed column: `workflows.ai_released` (bool, NOT NULL,
  scalar default `False`, so `AutoSchemaMigration` back-fills) plus `ai_released_by_id` and
  `ai_released_at`, and a `WorkflowChange`-style audit record for set and clear.
- **A release is bound to the version that was reviewed.** If the workflow is edited afterwards, the
  guarantee "it works and returns this" no longer holds. Simplest rule: any edit of a released workflow
  clears the flag, and the admin re-releases. Alternative: store a hash of the released definition and
  only offer the workflow while the hash matches. Pick one; the first is easier to explain.
- **An assistant description is part of the release**: what the workflow does, when to use it, what
  each input means and what the result contains (§16.4). Written by the author or the admin; it is the
  tool documentation the model sees (§1a), so it is reviewed like code.
- Optional gate: require a successful run of the current version before the flag can be set.

### 16.3 Tools

| Tool | Class | Notes |
|---|---|---|
| `list_released_workflows` | read | name, id, short description, category; only workflows the calling user may run |
| `describe_workflow` | read | assistant description, inputs (from `static_attributes`: name, type, required, default, description), whether devices are needed, result contract, expected duration |
| `propose_workflow_run` | execution proposal | `workflow_id`, `inputs`, `device_ids` or an inventory filter. Emits an `exec_proposal` for the user to confirm (§13.2 layer 4); the click calls the normal run endpoint |
| `get_run_status` | read | exists in spirit in `run_tools.py` / `run_reader.py`; reuse |
| `get_run_result` | read | returns the declared result as a handle + preview (§6.1), class C, opt-in |

Prefer **two generic tools** (`describe_workflow`, `propose_workflow_run`) over one tool per released
workflow, so the tool list stays small and stable (§15.2 item 1). Generating a typed tool per workflow
from `static_attributes` is possible later and gives better parameter validation for small models;
keep the generic form as the escape hatch.

### 16.4 Inputs and results

- **Inputs** reuse the existing contract: `static_attributes` declare name, type and required/default,
  and `run_input_validation.resolve_run_inputs` rejects unknown keys, missing values and type
  mismatches. The tool layer validates against this schema before it even proposes the start, so the
  model gets the error and can fix its call. A secret-typed attribute is **never** settable by the model
  (sealed secrets stay sealed; the confirmation UI collects them from the user, if at all).
- **Devices** are chosen by the model only from devices the user may see in the inventory; a hard
  maximum per start; larger sets need the user to select them in the UI.
- **Result contract.** "Returns a suitable result" needs a definition. Proposal: the author marks one
  artifact or one step output as the workflow's *assistant result* (for example the output of a
  designated step or a `store-artifact`), with a short schema/description. `get_run_result` returns
  that, bounded, via a handle. Without a designated result the tool returns only status and a summary
  of step statuses. This is open design work (§11).

### 16.5 Rights and ownership

- The run is started **as the confirming user** (`RunService.trigger_run(workflow_id, data, user_id)`),
  with `trigger_type="ai_assistant"` (the column is `String(20)`; no enum). The existing rules then
  hold unchanged: the user needs `workflows:execute`, `_assert_workflow_access` applies, the user
  owns the run (cancel, approve, delete), Wait & Run approvals stay with the user.
- A released workflow must be visible to the users who should be able to use it. Today a `private`
  workflow is accessible only to its creator, so release should require a non-private visibility (or
  an explicit decision that release grants run access). Open question.
- The assistant never gets more than the user has: if the user cannot run the workflow, it is not
  listed and `propose_workflow_run` refuses.

### 16.6 Security

- Starting a workflow is an **execution**, so §13 applies: default is a confirmation that shows the
  workflow name, the resolved inputs and the device list as data (not as model-written prose).
- A released workflow may change devices (deploy, configure). That is the admin's decision when
  releasing; the confirmation is therefore on by default. A per-workflow switch "may start without
  confirmation" (for read-only workflows) is possible later and is an admin-only part of the release.
- Budgets: maximum concurrent assistant-started runs per user, maximum starts per conversation, and
  `rate_limited("ai_workflow_start", ...)`. No chain where the assistant starts workflow after workflow
  without a user action in between unless auto-start is explicitly released.
- Child workflows (`start-workflow` step) keep working under the existing recursion guard and the
  triggering-user rule.
- The workflow's output is untrusted data when it comes back (device text inside results): same
  class C handling as any tool result.
- Audit: run id, workflow id, user id, conversation id, input keys (not values) in the audit line.

### 16.7 Why this matters for the design

- It is the cheapest way to offer complex abilities safely, and it reuses the most existing code
  (workflow editor, validation, run engine, Hatchet dispatch, run viewer, retention).
- It changes the roadmap: for repeatable procedures (collect interface errors across a site, backup
  configs, run a compliance check) build a workflow and release it, instead of a new ad-hoc tool.
  Ad-hoc tools stay for exploration. This keeps the number of risky tools small.
- A good first workflow-based increment: one or two read-only, admin-released workflows (for example
  "collect and parse show interface for a device set") to prove release, listing, start, status and
  result handles end to end, in parallel with the Batfish read tools (§10a).

### 16.8 Implementation sketch

1. Model and migration: `workflows.ai_released` (+ by, at), clear-on-edit in the workflow update path.
2. Admin API: set/clear release (admin only, audited) and a field for the assistant description and
   result designation; UI toggle in the workflow editor.
3. Tools: `list_released_workflows`, `describe_workflow`, `propose_workflow_run` (proposal),
   `get_run_status`, `get_run_result`.
4. Exec endpoint: confirm → `RunService.trigger_run` with `trigger_type="ai_assistant"`; verify the
   release flag again at start time (defence in depth, the proposal may be old).
5. Result handle storage for `get_run_result` (shared with §6.1).
6. Tests without an LLM: not released, edited after release, user without access, secret input,
   device limit, confirmation payload tamper, result truncation.

### 16.9 Open questions

- Clear-on-edit versus hash-pinned release?
- How is the assistant result declared (designated step output, designated artifact, or a dedicated
  "return to assistant" step)?
- Visibility of released workflows (require non-private, or release grants run access)?
- Auto-start without confirmation for read-only released workflows: allowed at all?
- Who may write the assistant description, and is it reviewed together with the release?
- How long a run may the assistant wait for (polling interval and time limits), and how does the
  result reach the conversation after the turn ended (§12.5)?

## 17. Code layout

### 17.1 Rule

Tools are **thin adapters**; logic lives in **services** that workflow steps and tools both call.
Tools do not live next to `workflow_steps/`, and they never import it.

- `workflow_steps/` is a plugin system (`executor.py`, `config.py`, `registry.yaml`,
  `step_registry.py`, a frontend `ConfigPanel`, a canvas node). A tool has a different consumer and
  different needs (Pydantic input, data class, redaction, handles). A second registry beside it would
  duplicate the concept.
- `services/*` must not import `workflow_steps.*` (enforced in
  `services/workflow/workflow_validation_service.py`; CLAUDE.md: "External code must never import
  `workflow_steps` packages directly"). A tool that called an executor directly would break that rule.
  The only legitimate path to an executor is the run engine (`StepRunner -> STEP_REGISTRY`).
- Executors carry workflow concepts (`WorkflowContext`, `WorkflowRun`, `node_id`, `StepOutcome`) that
  a one-command tool does not need.

A tool therefore does: validate (Pydantic) -> check rights and data class -> call a service ->
return the result envelope (§15.2) or a handle (§6.1). Anything beyond that is a smell.

### 17.2 Proposed tree (all Python under `backend/`)

```
backend/
  services/
    network/netmiko/         # exists: send_command(s), get_running_config, textfsm      (tools + steps)
    batfish/                 # exists: BatfishService (routes, reachability, bgp, ospf, ...) (tools + steps)
    ai_assistant/
      agent_loop.py, chat_service.py, providers/, ...      # exist
      tools/
        base.py                    # choke point (exists)
        batfish_tools.py           # new: adapter on services/batfish
        device_tools.py            # new: propose_show_command, propose_get_config, parse_output
        result_tools.py            # new: query_result, fetch_slice, diff_results
        released_workflow_tools.py # new: list/describe/start/status/result (section 16)
        workflow_tools.py          # exists: authoring (proposals); keep separate from the above
      results/                     # new: handle store, result envelope, preview size constants
      execution/                   # new: command policy (allow-list), confirmation hash, task payload
  hatchet/workflows/
    ai_tool_execution.py           # new: thin task (section 14.6)
  routers/
    ai_assistant.py                # exists; add confirm/exec endpoint here or in routers/ai_exec.py
  repositories/
    ai_result_repository.py        # only if handles are stored in the database
  core/models/
    ai_results.py                  # only if handles are stored in the database
```

Frontend (confirmation dialog, execution proposal card, progress, result view) goes under
`frontend/src/components/features/ai-assistant/`, next to the existing panels, with query hooks in
`hooks/queries/` and keys in `lib/query-keys.ts` (project rules, `doc/claude/frontend.md`).

If the number of tools grows, split `tools/` into subpackages (`tools/batfish/`, `tools/devices/`,
`tools/workflows/`); one module per domain, not per tool.

### 17.3 What can be reused as is, and what must be extracted

Checked by reading the code:

| Need | Status |
|---|---|
| Batfish reads | `services/batfish/client.py::BatfishService` already offers `routes`, `reachability`, `test_filters`, `node_properties`, `interface_properties`, `ospf_*`, `bgp_*`, `bgp_session_status`, `file_parse_status`, `undefined_references`, `unused_structures`, `generic_question`, `list_snapshots(_with_metadata)`. **Reusable as is.** No `traceroute` method yet: add it to the service (not to a step). |
| Batfish snapshot choice | `workflow_steps/common/batfish_context.py` resolves the snapshot from an upstream step via `WorkflowContext`: workflow-specific, **not reusable**. The tool needs its own snapshot selection on top of `list_snapshots_with_metadata` (§15.5). |
| Run a command | `services/network/netmiko/service.py::NetmikoService.send_command(s)` supports TextFSM (`use_textfsm`); device type via `services/network/netmiko/platform.py`. **Reusable.** An ad-hoc path with host validation and credential-by-id already exists: `NetmikoPreviewService` (§18, fact 5). |
| Fetch configs | `NetmikoService.get_running_config` / `get_startup_config` / `get_configs`, and `NetmikoPreviewService.get_configs`. **Reusable.** |
| Per-device loop, retry, outcome shaping | in `workflow_steps/run_command/exec_mode.py` (~300 lines) and `get_device_configs/executor.py`. Tied to `DeviceContext`, `StepOutcome`, `fail_device`, `record_dry_run`; **stays in the steps**. The tool calls `NetmikoService` directly (§18, fact 3). |
| TextFSM/Genie normalisation | `workflow_steps/run_command/enrichment.py` works on `DeviceContext`. For tools, call the netmiko TextFSM path and shape the result in the tool; do not import the step module. |
| Credential resolution for the acting user | `workflow_steps/common/credential_resolver.py` is already a thin shim over `services/credentials/manager.py::CredentialManager(db, acting_user_id=...)`. **No extraction needed**: tools call `CredentialManager` (its docstring says new code should). |
| Run creation | `RunService.trigger_run` / `_create_and_dispatch_run` (services/execution): reusable for released workflows (§16). |

So the refactoring is smaller than first assumed (see §18): **at most a shared per-device fan-out
helper, and a traceroute method on `BatfishService`.** Everything else is reuse.

**Extraction means moving, not copying.** The forbidden import direction does not cause duplicate
code as long as shared logic is moved into a service and the step is changed, in the same PR, to call
that service:

```
before:  step ──> workflow_steps/common/credential_resolver.py
after:   step ──┐
                ├──> services/credentials/ (resolver)
         tool ──┘
```

- A step gets thinner, not heavier; this is the layering the project already prescribes
  (Model -> Repository -> Service -> Router; logic in services).
- What stays separate on purpose is the adapter layer, because step and tool serve different
  contracts: step config in / `StepOutcome` + `DeviceContext` out versus Pydantic tool input in /
  result envelope or handle out (plus redaction, data class, audit). That is small mapping code, not
  duplicated domain knowledge.
- Copying part of an executor into a tool is the failure mode to avoid. Countermeasures: the import
  check in §17.4, a review rule (needing something that exists only in a step means: move it to a
  service first, point the step at it, in the same PR) and service-level tests that both callers share.
- Relaxing the rule so tools may import `workflow_steps.common.*` is rejected: the rule is documented
  and tested in the project, and the import would tie the assistant to plugin internals that change
  more often than services do.

### 17.4 Guard rails for the layout

- Add a check script (same style as `scripts/check_text_sql.py`) that fails when
  `services/ai_assistant/` imports `workflow_steps`, `netmiko` or `paramiko` directly, or opens an
  SSH session outside `services/ai_assistant/execution/` plus the Hatchet task. The command policy and
  the one execution module are then the only way to reach a device.
- Tool modules import only: `tools/base.py`, services, `core.*`, models. No router, no repository
  (the `check_router_repositories.py` spirit), no direct `sqlalchemy.text()`.
- One test module per tool module, runnable without a model (§1a, §12.6).
- Documentation: register new tools in `doc/ai_integration/AI_ASSISTANT.md` §3.5 (tool table) and add
  the rights/permission entries to `doc/claude/auth.md` when they exist.

### 17.5 Open points

- (Resolved by §18 fact 4: `CredentialManager` already takes `acting_user_id`; no extraction.)
- Do handles live in the database (new table, repository, retention) or as artifacts of a run
  (§14)? This decides whether `results/`, `ai_result_repository.py` and `core/models/ai_results.py`
  exist.
- Does `routers/ai_assistant.py` get too large? A separate `routers/ai_exec.py` for confirm, status and
  cancel keeps rate-limit buckets and permissions separate.

## 18. Pre-checks before implementation (plan item 0.3), facts by reading the code

Read on 2026-10-28; nothing was run. Each fact says what it changes in this document.

1. **Run status and result reading already exist as tools.** `services/ai_assistant/run_reader.py::DbRunReader`
   delegates to `RunService` (so visibility rules are the REST ones), requires `workflow_runs:read`, and
   uses a short `SessionLocal()` per call in `asyncio.to_thread`. `tools/run_tools.py` offers `get_run`,
   `get_step_result`, `get_artifact`, `list_run_events`, `get_run_workflow` (class B/C gated by the
   opt-in). *Effect:* for §16 `get_run_status` is `get_run`; `get_run_result` can reuse
   `get_artifact`. What is missing is only the "designated result" concept and the start tool.
2. **`object_session(run)` is used by about 16 executors** (for example `get_device_configs`,
   `secret_get`, `add_to_ise`, `deploy_rendered_template`) to obtain the DB session, and they raise
   `RuntimeError("... WorkflowRun has no active DB session")` without one. *Effect:* an adapter object
   instead of an ORM row cannot work (confirms §14.3). It only matters if executors are called, which
   §17 avoids; service-based tools need no `WorkflowRun` at all.
3. **`run-command`'s `exec_mode.py` need not be split.** It is bound to `DeviceContext`, `StepOutcome`,
   `fail_device`, `record_dry_run` and `ParsedRunCommandConfig`. Its core is
   `resolve_connection_device_type(...)` plus `NetmikoService.send_commands(..., use_textfsm=...)`, both
   in `services/`. `models.workflow_context` lives outside `workflow_steps/` and is importable.
   *Effect:* the tool calls `NetmikoService` directly; no extraction. `run-command` also has a
   `config_mode` that writes configuration (`write_config_after_execution`, `auto_confirm_prompts`);
   the tool must not expose any of it.
4. **Credential resolution needs no extraction.** `workflow_steps/common/credential_resolver.py` is a
   shim over `services/credentials/manager.py::CredentialManager(db, acting_user_id=...)`; global
   credentials plus the acting user's private ones resolve. *Effect:* §17.3 corrected above.
5. **Ad-hoc device and Batfish access without any run already exists in the Template Editor.**
   - `services/network/netmiko/preview_service.py::NetmikoPreviewService` (`run_commands`, `get_configs`)
     with host validation (`core/safe_hosts.py::validate_netmiko_preview_host`), credential by id with
     `acting_user_id`, router `routers/netmiko.py`.
   - `services/batfish/preview_service.py::BatfishPreviewService` (`run_routes`, `run_reachability`,
     `run_test_filters`, `run_generic`, facts), router `routers/sources/batfish/query.py` with
     `sources.batfish:query` permission, rate limits, `PREVIEW_ROW_LIMIT` (context var, capped by
     `MAX_PREVIEW_ROWS`) and `assert_batfish_network_exists`.
   *Effect:* (a) the app already accepts the principle "a user runs an ad-hoc read without a workflow
   run"; the new assistant tools can wrap these services, so **§14.4 option C (no run) becomes the
   natural start for ad-hoc tools** and the run-shell decision (§14) can be deferred until persistent
   audit or artifacts are needed; (b) their permissions, rate limits and host validation are the
   baseline the assistant tools must at least match; (c) the rule text in `AI_ASSISTANT.md` ("no tool can
   open an SSH session") concerns the assistant, not the app. Not yet verified: exact permission and
   rate limits on `routers/netmiko.py`, and whether the preview service stores anything.
6. **Batfish.** `BatfishService` takes a `BatfishConnection` (from
   `BatfishSourceConfigService.resolve_connection(source_id)`) and a network name; sessions are cached
   per `(host, port, network)`; the snapshot is passed explicitly on every question. Ad-hoc generic
   questions go through `query_helpers.py::GENERIC_QUESTION_ALLOWLIST` (BGP, OSPF, edges, named
   structures, ipOwners, undefined/unused references, filterLineReachability, switchedVlanProperties).
   **No traceroute** exists (not a method, not in the allow-list). Snapshot names are caller-chosen
   (workflow runs use `run-<uuid>`), so selection must sort by `creationTimestamp`
   (`list_snapshots_with_metadata`). The `viewer` role has `sources.batfish:read` but not `:query`.
   *Effect:* §10a: add traceroute to the service plus a bounded wrapper; reuse the preview service
   and its row cap for the first tools; define which permission the assistant tools require
   (`sources.batfish:query`); decide the snapshot selection rule (§15.5).
7. **`trigger_type`.** The API model is `TriggerType = Literal["manual", "scheduled", "webhook"]`
   (`models/runs.py`); `"workflow"` is set internally (`start_child_run`); the column is `String(20)`.
   *Effect:* `"ai_assistant"` (12 chars) needs the `Literal` extended or a dedicated server-side start
   method; screens that switch on `trigger_type` (dashboard, runs list) were not inspected.
8. **Conversations.** `ai_conversations` stores `messages` as JSON per `user_id`, `surface`
   (`String(32)`) and `subject_key`; surfaces are assembled in `surfaces.py` (one builder and prompt
   per surface). A late tool result (§12.5) needs a stored-message shape; not inspected in detail.
   *Effect:* the "general" surface is a new builder plus prompt; check whether `surface` values are
   validated against a closed set.
9. **No hidden/system flag on `workflows`.** `core/models/workflows.py` has none (columns: name,
   creator, visibility, canvas, static_attributes, `is_version_controlled`, ...). *Effect:* §14.2
   needs a new column and filters in workflow list/schedule/export queries; those queries were not
   inspected. With fact 5 this option is needed later than assumed.
10. **Run creation for released workflows** is `RunService.trigger_run(workflow_id, data, user_id)`:
    `_assert_workflow_access` (private workflows only for the creator), `resolve_run_inputs`,
    `_create_and_dispatch_run`. *Effect:* §16.5 holds as written; the permission check for
    `workflows:execute` is done by the router, so the new endpoint must repeat it.
11. **Not yet checked** (open before the matching phase): retention and run reaper behaviour for a
    non-workflow run source; exact router permissions/limits in `routers/netmiko.py`; UI places that
    list runs by `trigger_type`; closed set of `surface` values; `MAX_PREVIEW_ROWS` value.

### 18.1 Consequences for the plan

- Phase 1 (Batfish) is cheaper: services, allow-list, row cap and permission exist; add traceroute.
- Phase 3 (ad-hoc devices): no credential extraction, no executor split, and the run shell can start
  as option C; §14 becomes a later decision.
- Phase 2 (released workflows) is unchanged except for the `TriggerType` extension.
- The new risk to name: the assistant must not become a way around the rights, limits and host
  validation that the preview endpoints enforce; it must be at least as strict.

## 19. Decisions (proposal accepted 2026-10-28)

Principle: proceed in small, reversible steps from low risk to high risk, and use only paths the app
already guards. Costly decisions are deferred until real use informs them.

| # | Topic | Decision | Reason |
|---|---|---|---|
| D1 | Access to devices and Batfish | Wrap `NetmikoPreviewService` and `BatfishPreviewService`; no run (option C of §14.4). | The Template Editor already has this path with host validation, per-user credentials, allow-list, row cap and rate limits (§18 fact 5). No second security logic, no hidden system workflow. |
| D2 | Confirmation | Batfish reads run without a click. Everything that opens an SSH session needs the user's click. Auto-run of device reads is not part of the first version; if ever, behind a per-user opt-in. | Batfish touches no device and has an allow-list. SSH is the prompt-injection path (§3); the click is the one control the model cannot satisfy itself. |
| D3 | Permission | No new permission at first. Required: the same permission as the matching preview endpoint, an operator switch (off by default, in the style of `AI_ALLOWED_DATA`) and the data-class opt-in. A dedicated permission can follow on demand. | A new permission adds RBAC maintenance (P1 to P8). The operator switch is the honest emergency brake. |
| D4 | Where execution runs | After the click, in the exec endpoint, for small sets (about 10 devices, hard time limit, to be fixed in config). Hatchet only for large sets and long runs. The contract (payload, handle, confirmation hash) is designed so the same code runs in a Hatchet task later. | Preview endpoints work this way; fewer moving parts, faster feedback, easier tests. A deliberate concession to simplicity versus the initial Hatchet idea (§4, §14.6). |
| D5 | Run shell | Deferred. Until then an audit record with ids only (`audit_refs`). Decide §14 when artifacts must persist or runs get long. | Real requirements will make the choice easier. |
| D6 | Handles (§6.1) | Short-lived store with expiry (hours), per user, not in the database; Redis is the candidate. An expired handle returns a clear "expired, fetch again" message. | No migration, no retention job; matches intermediate results. Move to DB or run artifacts if results must live for weeks. Limit the size per handle. |
| D7 | Released workflows: version | Any edit of a released workflow clears the release (no hash pinning). | Simple to explain and safe; the admin re-releases deliberately. |
| D8 | Released workflows: result | At release the admin marks one step output or artifact as the assistant result. Without it only status and step summary are returned. | The model gets a defined return value. |
| D9 | Released workflows: visibility and start | Only non-private workflows can be released. Starting always needs the user's click in the first version. | A private workflow is accessible to its creator only. A workflow may change devices. |
| D10 | PydanticAI | Not now. Spike only on the triggers in §8. | The loop is ~106 lines; the work is in the tools; seams in §7 keep the switch local. |

### 19.1 Order of work (from the plan)

1. Plan item 0.2: amend Rules 3 and 4 in `AI_ASSISTANT.md` (also the `tools/base.py` docstring).
2. Phase 1: Batfish read tools (traceroute added to the service, preview service wrapped, result
   envelope and handles, "general" surface). §10a.
3. Phase 2: released workflows (§16, with D7 to D9).
4. Phase 3: device tools with click confirmation and small sets (D2, D4); run shell and Hatchet when
   real tasks require them.
5. Phase 4 and 5 on demand (§6, §8).

### 19.2 What we deliberately do not do (first versions)

- No auto-run of SSH commands.
- No new table for handles or results while short-lived storage is enough.
- No free `run_question` catalogue for Batfish at the start, only named tools.
- No calls from the assistant into executors (§17).

### 19.3 Assumptions to verify before the matching phase

- Permission and limits of `routers/netmiko.py` equal what D3 assumes ("same permission as the
  preview endpoint") before phase 3.
- Redis is sufficient for the expected handle sizes; otherwise cap sizes or switch the store (D6).
- Running device work inside the exec endpoint stays within request timeouts for the chosen set
  size (D4); otherwise lower the limit or move to Hatchet earlier, which brings §14 forward.
