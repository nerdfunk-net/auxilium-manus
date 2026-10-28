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

### Mitigations (proposed)

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

Open design point, **the run shell**. Executors need a `WorkflowRun`. Options:

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

## 10. Implementation order

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
