# In-App AI Assistant — Requirements & Design

Status (2026-10-10): **all six phases are implemented.** Phases 1-3 (settings,
Claude, template assistant, Gemini, Ollama/OpenAI-compatible) are verified by the product owner
against real providers. Phase 4 (workflow canvas assistant) is covered by unit/contract tests and by
checks against the real validator, registry and dev database, but not yet by a real model run or a
browser session. Phase 5 is built: the **run explainer** (run tools, opt-in enforcement, runs-page
panel) and the **inventory assistant** (inventory-page panel, read-only questions) are checked against
real dev-database rows and the live Nautobot; the user has tried the run explainer.
Phase 6 (hardening) is built (§17). Sessions that survive navigation and server-side saved
conversations are built (§18). §12 lists what was built and verified per phase, §13 the
recorded decisions.

This document describes an AI assistant built *into* the app. It is distinct from
`doc/ai_collaboration/` (an external AI coding session such as Claude Code driving
`backend/scripts/ai_*_apply.py` from the host). The two share infrastructure
(validation, step registry, write gates) but have different actors, trust models and UIs.

## 1. Goals

A user configures their own LLM provider and API key, then uses a prompt input inside the
app to:

1. **Author** — create or edit a workflow (canvas) or a Jinja2 template.
2. **Explain** — understand why a run failed, what a workflow does, what a template renders.
3. **Query** — ask questions about inventory and device attributes.

The assistant is an *agent*: it does not just return text, it calls tools backed by the
app's own services, observes the results, and corrects itself before presenting an answer.

### Scope of the first release

| In | Out (later) |
|----|-------------|
| Authoring (as proposals) and explaining | Running/dispatching workflows or any device access |
| Providers: Anthropic Claude, Google Gemini, OpenAI-compatible (covers Ollama) | Other provider-native features (batch, files API) |
| Per-user private API key | Shared/global keys |
| Entry points: template editor, workflow canvas, runs page, inventory page | Change requests, global panel |
| Read tools + proposal-only write tools | Auto-apply, MCP server for external agents |

## 2. Design principles

1. **The assistant is the user.** It acts with the calling user's RBAC. Every tool call goes
   through the same service layer and `require_permission` checks as the equivalent
   REST call. There is no assistant super-principal. (The `ai-assistant` principal in
   `doc/ai_collaboration/` stays what it is: the identity of an *external* session.)
2. **Read freely, write by proposal only.** Read tools execute immediately. Write tools
   never persist; they produce a *proposal* (a patch) that the user reviews as a diff and
   explicitly accepts. Accepting goes through the normal save path, so `WorkflowChange`
   auditing, git versioning and permission checks apply unchanged.
3. **No execution tools.** No tool can run a workflow, open an SSH session, or push to
   git. Rendering a template against sample data is allowed (it is a pure computation).
4. **Untrusted content stays data.** Device configs, Nautobot descriptions, command output
   and run logs are attacker-influenced text. Because writes are proposal-only and there
   are no execution tools, a prompt-injected model can at worst produce a bad proposal the
   user sees as a diff. This invariant must hold for every future tool.
5. **Validate before showing.** A proposal is run through the existing validation tiers
   (and Jinja render for templates) and the model gets the findings back to self-correct
   before the user ever sees it.
6. **Provider-neutral core.** Tools, prompts, and the agent loop know nothing about a
   specific vendor; adapters translate.

## 3. Architecture

```
Frontend panel (SSE, proposal cards)  ──►  /api/proxy/ai/*  ──►  routers/ai_assistant.py
 template editor / workflow builder                                  │ auth, rate limit, thin
                                                                     ▼
                                              services/ai_assistant/
                                                ├─ settings_service.py   per-user config, per-provider keys
                                                ├─ chat_service.py       one request -> event stream
                                                ├─ agent_loop.py         tool loop (max 8 steps)
                                                ├─ surfaces.py           prompt + toolbox per surface
                                                ├─ tools/                base (choke point), template_tools, workflow_tools,
                                                │                        run_tools, inventory_tools
                                                ├─ providers/            anthropic (SDK), gemini, openai_compat (httpx)
                                                ├─ redaction.py          restorable secret tokens
                                                ├─ data_sharing.py       opt-in policy (classes B/C), device labels, attribute allow-list
                                                ├─ conversation_service.py  saved conversations (explicit Save, redacted)
                                                ├─ audit.py              one log line per chat turn
                                                ├─ workflow_expand.py    compact plan <-> persisted canvas
                                                ├─ template_render.py    sandboxed lenient render
                                                ├─ template_reader.py / workflow_reader.py / run_reader.py /
                                                │  inventory_reader.py   per-call DB access + RBAC
                                                ├─ base_url_policy.py    outbound URL check for local servers
                                                └─ knowledge/            curated reference texts the model can read
                                                             │
              existing services (templates, workflow validation, plugin registry, credentials, git, inventories)
```

Layering follows the project rule: router → service → repository. The router never builds
prompts or calls providers.

### 3.1 Providers

A small internal interface — not a third-party abstraction layer — with three adapters:

- `anthropic` — Anthropic Messages API via the **official `anthropic` SDK** (tool use, streaming,
  prompt caching). The adapter wrapping it is still ours; only the HTTP/streaming layer is the SDK's.
- `gemini` — Google AI Studio (Gemini API, function calling). Free tier has tight rate
  limits; the loop must surface 429s clearly.
- `openai_compat` — any `/v1/chat/completions` endpoint with tool calling: Ollama, LM Studio,
  vLLM, OpenAI. Base URL is user-configurable.

Normalised shape: `ChatMessage`, `ToolSpec`, `ToolCall`, `StreamEvent` (text delta, tool
call, usage, done). Adapters own vendor formats and error mapping (auth, rate limit,
context overflow, provider down) into a small set of app errors.

*Decision (agreed):* thin hand-written adapters over `httpx`/official SDKs, no LiteLLM. Three
providers is small, tool-calling quirks are exactly where LiteLLM leaks, and it keeps the
dependency surface and the SSRF-policy integration simple. Revisit if a fourth provider is
requested.

**Model selection.** The user picks from a short per-provider list (not free text); the list lives
in `services/ai_assistant/settings_service.py::PROVIDER_MODELS`, validated server-side. For
Anthropic: **Claude Haiku 5.5 (default; cheap, adequate for editing Jinja2 templates)** and
**Claude Sonnet 5.5 (complex workflows)**. The list is data only: nothing downstream branches on a
model id. A stored model that is no longer offered falls back to the provider default.

**Providers are treated equally.** The app does not special-case individual models or vendors:
no per-model feature flags, capability tables or tuned prompts. The adapter interface is the
only place vendors differ. The Gemini free tier is for testing; whether it is workable beyond
that is unknown, so rate-limit (429) and quota errors must map to a clear, provider-neutral
message and must never be retried in a tight loop.

**Local models:** tool-calling quality varies widely by model. The settings UI should say
so, and the loop must tolerate malformed tool calls (return the error to the model, count
it against the step cap).

### 3.2 Per-user configuration and key storage

Each user has their own provider settings: provider, model, base URL (openai_compat only),
and API key. Requirements:

- **Enable switch, independent of the key.** `enabled` (default **false**) is a per-user master
  switch. A user can have a key configured and the assistant still off. When off, every
  assistant UI surface is hidden (panels, entry buttons) and the backend refuses every
  assistant endpoint with `403 {"code": "ai_assistant_disabled"}`. Hiding is a UX
  convenience; the server-side refusal is the enforcement. Turning it off does not delete the
  key or the data-sharing choices.
- **Availability** is the conjunction of three independent things: permission
  `ai_assistant:use` (admin-controlled) AND `enabled` (user-controlled) AND a configured key
  (or, for `openai_compat` with a local endpoint, a configured base URL). The frontend asks one
  lightweight endpoint, `GET /ai/status` → `{available, reason}`, so surfaces do not need the
  full settings payload. The settings page itself stays visible to anyone holding the
  permission, since that is where the assistant is switched on.
- Key is **private to the user** — never readable by other users or admins through the API,
  never returned by any endpoint after being set (write-only; UI shows "key set").
- Encrypted at rest with the same Fernet mechanism as credentials (`EncryptionService`; OpenBao
  storage is not implemented). Stored in a dedicated `user_ai_settings` table: the
  provider/model/base-URL fields don't fit `Credential`. **One key per provider**: the column
  holds a JSON map of individually encrypted keys, so switching provider never makes another
  provider's key look valid and presence checks need no decryption. A pre-existing single token is
  still read as the row's provider key.
- Key resolution goes through the secret-handling path that registers the value for
  run-scoped redaction (`unwrap_secret` / `CredentialsService.get_decrypted_*`).
- Setting a base URL is **admin-only** (`PATCH /ai/settings` returns 403 `ai_base_url_admin_only`
  otherwise): it makes the backend send requests to a host the user chose, inside the internal
  network. The URL may not carry a query, fragment or path parameters.
- Base URL (OpenAI-compatible only) passes `core/safe_urls.py` through `base_url_policy.py` when it
  is saved **and** again right before every call; redirects are never followed. There is **no
  special bypass** for local servers: a LAN host (RFC1918) works, a server on the backend's own
  machine needs `ALLOW_LOOPBACK_SOURCE_URLS=true` like every other source. Outside development an API
  key is only sent over https.
- "Test connection" button (cheap request, rate limited).

### 3.3 Agent loop

- Backend-driven; the frontend sends the chat text plus the surface's **current state** (the
  template editor's buffer, the builder's canvas - which may be unsaved) and renders the event
  stream. The server decides what of that state the model may see.
- Hard caps: max tool steps per turn, max output tokens, request timeout, and a per-user
  `rate_limited("ai-chat", ...)` budget (30 / 60 s).
- Streams events over SSE: `text` deltas, `tool` status (running / done / error), `proposal`,
  `usage`, `error`, `done`. The Next.js proxy must pass streaming through unbuffered —
  verify this early, it is the main frontend unknown.
- Conversations are held client-side per surface and re-sent each turn (stateless server). They
  survive navigation in an in-memory store and can be saved on the server on request (§18).

### 3.4 Context (option 2)

Each surface contributes a context builder, so the model starts informed instead of
discovering everything via tool calls:

| Surface | Injected up front | Status |
|---------|-------------------|--------|
| Template editor | current buffer (content, type, description), custom variables with values, names only of device/run variables | built |
| Workflow canvas | compact view of the current plan (steps with config, edges, run inputs); layout and registry noise stripped | built |
| Run explainer | only the open run's id; the model fetches metadata first and content data on demand, behind the opt-in | built (§14) |
| Inventory | only the Nautobot source id; devices are fetched through tools, behind the opt-in | built (§15) |

Keep it compact: summaries up front, details through tools. Large content data (command
output, config backups) is truncated with an explicit marker and fetchable via a tool.

### 3.5 Tools (option 3)

All tools take/return JSON, run as the calling user, and have bounded output sizes.

**Built (phases 2 and 4)** - see §10 and §11 for the details of each:

| Tool | Surface | Purpose |
|------|---------|---------|
| `get_template_reference` | template | Curated Jinja / namespace reference |
| `list_templates` / `get_template` | template | Saved templates as examples (`templates:read`) |
| `render_template` | template | Lenient sandboxed render with custom variables + model-supplied samples |
| `propose_template` | template | Syntax check + trial render; emits a `proposal` |
| `get_workflow_reference` | workflow | Authoring rules (plan format, outcomes, capability flow, fan-out, run inputs) |
| `list_steps` / `get_step_schema` | workflow | Step catalogue and per-step config schema, outcomes, capabilities |
| `list_references` | workflow | Credentials (id/name/type only), git repositories, sources, saved inventories |
| `validate_workflow` | workflow | The four validation tiers on a plan, without proposing |
| `propose_workflow` | workflow | Expand + validate; emits a `proposal` only when error-free |

**Built (phase 5, run explainer, surface `run_viewer`)** - see §14. All read-only; the first class B/C
tools, so every value of those classes passes the opt-in of §4.2:

| Tool | Purpose |
|------|---------|
| `get_run` | Status, timings, error category, every step, fan-out groups |
| `get_step_result` | One step per outcome and device: status, capabilities, commands + artifact ids; `include` = `attributes` (B) / `parsed` (C) |
| `get_artifact` | Stored command output / config text (C), truncated at 8000 chars |
| `list_run_events` | Live run events; message text is C |
| `get_run_workflow` | The run's workflow as the compact view (A), "as saved now" |

**Built (phase 5, inventory assistant, surface `inventory`)** - see §15. All read-only, class B:

| Tool | Purpose |
|------|---------|
| `list_inventories` | Saved inventories visible to the user (id, name, type, scope) |
| `resolve_inventory` | Devices of one inventory resolved now: `total_count` always; counts by role / platform / location / status / type / manufacturer over ALL devices and up to 50 device rows (chosen fields) only with the opt-in |
| `search_devices` | Devices by name part across Nautobot (opt-in) |
| `get_device_attributes` | Nautobot attributes of one device (opt-in) |

**Planned (not started):** a way to read a saved workflow other than the open one.

Rule for new tools: if it cannot be classified as "pure read" or "proposal", it does not
ship in this feature.

### 3.6 Proposals and the diff UI

A proposal is an SSE `proposal` event: for a template `{kind: "template", content, summary,
warnings}`, for a workflow `{kind: "workflow", canvas_nodes, canvas_edges, canvas_groups,
static_attributes, changes, warnings, summary}`.

- The UI shows a diff (line diff for templates; a change list for workflows - added / removed /
  changed steps with a config diff, added / removed edges) and **Apply / Reject**.
- **Apply writes into the open editor or canvas as unsaved state** (decision 8). The user reviews it
  there and uses the normal **Save**, which re-runs the server-side validation and goes through
  `WorkflowChange` auditing and git versioning. The backend has no "apply proposal" endpoint, so
  there is exactly one write path.
- Staleness is a warning, not a block: the card compares a fingerprint (workflows) or the content
  (templates) from when the turn started with the current editor and says applying will overwrite
  edits made meanwhile.
- A workflow proposal is **never emitted while validation errors remain**: they go back to the model,
  which must fix and re-propose (stricter than the external path, which only refuses Tier 2 drift).
  Warnings are shown on the card.
- References must be real ids/names obtained from tools, never invented - Tier 2 validation enforces
  it (`doc/ai_collaboration/AI_DEFAULTS.md` thinking, applied to the in-app path).

### 3.7 Explain & query features

- **Run debugging:** the model reads run metadata → failed step result → run events,
  and explains cause and likely fix. Read-only; built as a panel on the runs page (§14).
- **Workflow/template explanation:** "what does this do" over the in-context definition.
- **Inventory questions:** resolved via `resolve_inventory` + `get_device_attributes`;
  bounded by device-count caps, and the answer must say when it was truncated. Built as a panel on
  the inventory page (§15).

## 4. Data sharing — opt-in only

**Anything beyond the assistant's own working material is sent to the model only if the user
has explicitly opted in.** Config backups and command output can contain passwords, keys,
SNMP communities and other secrets, so the default is "off" for everything that comes from
devices or runs.

### 4.1 Data classes

| Class | Examples | Default |
|-------|----------|---------|
| **A. Definitions** | Step catalogue/schemas, workflow definitions and canvas, template content and variable names, credential/repo *names and ids* | Sent (needed for the feature to work). Credential secrets are never in this class. |
| **B. Inventory & attributes** | Device names, Nautobot attributes, resolved inventories | **Opt-in**, split into a base switch (basics) and three categories that each need their own switch on top (§16) |
| **C. Content data** | Config backups, command output, parsed output, generated artifacts, step `content` results, run logs/events, step error text (may echo output) | **Opt-in** |
| **D. Secrets** | Decrypted credentials, vault values, keys | **Never sent**, not even with opt-in |

Class A still passes through the redaction layer, because a template or workflow config can
contain a pasted secret.

### 4.2 Rules

1. **Per-user, default off.** Stored in `user_ai_settings` as `share_inventory_data` (B base),
   `share_device_addresses`, `share_custom_fields`, `share_config_context` (B categories, §16) and
   `share_content_data` (C). Independent switches; C does not imply B, and a B category does nothing
   without the B base switch.
2. **Visible and session-scoped.** The assistant panel shows which classes are currently
   enabled for the active provider (and which provider, so a user can tell a local Ollama from
   a remote API). The user can turn a class off at any time; it takes effect on the next turn.
3. **Enforced server-side in the tool layer, not in the UI.** Every tool that can return class
   B or C data checks the calling user's setting and, if not opted in, returns a structured
   `not_shared` result (telling the model the user has not enabled it, so it can ask the user
   instead of failing silently). The same applies to context builders (§3.4): a run-explanation
   context contains metadata only unless C is enabled.
4. **Opt-in is not a guarantee of safety.** Tool output (classes A–C) goes through the redaction
   pipeline in §4.3 before it reaches the model. This reduces risk; it cannot prove absence of
   secrets. The enable dialog says so.
5. **Truncation.** Class C is truncated with an explicit marker; the model must say when its
   answer is based on truncated data.
6. **No proposals leak C.** A proposal diff may be shown to the user, but class C content must not
   be echoed into a proposal destined for persistence unless it was part of the user's own prompt.
7. **Tests:** a unit test per B/C tool asserting `not_shared` when opted out, and an
   injection-style corpus asserting redaction.

### 4.3 Redaction pipeline

Reuse what the app already has, and add only the missing free-text layer. What exists today
(`services/workflow_context/secret_fields.py`, `services/git/scrub.py`):

| Layer | Handles | Reusable for the assistant? |
|-------|---------|-----------------------------|
| `redact_secrets_in_data` — key-name matching (`password`, `secret`, `token`, `community`, `passphrase`, `api_key`, `*_password`, ...) and `SECRET_BAG_PATHS` | Structured JSON/dicts (attributes, parsed output) | **Yes**, as is, for every dict/list tool result |
| Sealed-envelope redaction | Sealed attribute leaves | **Yes**, same call |
| Run-secret exact-match scrub | Secrets unwrapped during a run | **Only inside a run scope.** The assistant runs outside one, so this layer is a no-op for it. Do not pretend otherwise. |
| `scrub_url_credentials` | `scheme://user:token@host` in free text | **Yes**, applied to all strings |

What does **not** exist: scrubbing secrets inside *free text* such as a `show running-config`
dump, which is the main class-C case. New module `services/ai_assistant/redaction.py` adds a
small, conservative, ordered set of regexes for text, replacing only the secret part with a
**restorable token** (`__SECRET_n__`, see §10) and keeping the surrounding line so the model can
still reason about the config:

- PEM/private-key blocks (`-----BEGIN ... PRIVATE KEY-----` through `END`)
- Cisco-style secrets: `enable secret|password <n> <value>`, `username ... (password|secret) <n> <value>`,
  `key <n> <value>` (tacacs/radius), `password <n> <value>` on line/aaa lines — every type
  (0/5/7/8/9), since types 0 and 7 are plaintext/reversible and 5/8/9 are hashes that still
  enable offline cracking
- `snmp-server community <value>`, SNMPv3 `auth|priv <algo> <value>`
- Routing-protocol / NTP / HSRP auth keys: `authentication-key`, `message-digest-key <n> md5 <value>`,
  `ntp authentication-key <n> md5 <value>`, `standby ... authentication <value>`
- Generic `(password|secret|token|api[_-]?key|passphrase)\s*[:=]\s*\S+` assignments
- `Authorization: Bearer|Basic <value>` and similar header values

Design rules: patterns live in one tuple of compiled regexes with a name and a test fixture
each; false positives are acceptable (a redacted non-secret costs little), false negatives are
the risk; the module must be pure and fast (bounded input, no catastrophic backtracking —
cap line length before matching). Because the existing structured redactor and this text
redactor are independent mechanisms, both run on every class A–C tool result: structured data
first, then every remaining string leaf through the text redactor.

Because the tokens are restorable, an edit never corrupts a secret: a proposal that keeps a token gets
the original value back, one that deletes it removes the value. Structured step configs use
`tokenize_data` / `restore_data` (secret-named keys and sealed envelopes become tokens too). The
structured redactor's literal `***REDACTED***` marker is never persisted: any proposal containing it
is rejected.

The regex set and its fixtures exist (`tests/unit/test_ai_redaction.py`); phase 6 added a
multi-vendor corpus and more patterns (§17). Not in v1 (documented
gaps): registering the user's own credential secrets for exact-match scrubbing, and
ML/entropy-based detection.

## 5. Security & privacy

| Concern | Mitigation |
|---------|-----------|
| Key theft | Per-user, encrypted, write-only API, redaction registration, never logged |
| Secrets in prompts | No tool returns decrypted credentials; run-scoped redaction applied to tool output before it reaches the model |
| Prompt injection | Proposal-only writes, no execution tools, diff review (principle 4) |
| Data exfiltration to a 3rd-party LLM | Opt-in only for device-derived data (§4); active provider and enabled data classes shown in the panel; Ollama as the local option |
| SSRF | Server URL through `safe_urls` at save and before every call, no redirects, no new bypass (loopback needs `ALLOW_LOOPBACK_SOURCE_URLS`); https required for a key outside development |
| Cost / runaway loops | Step, token and time caps; per-user rate limit |
| Error leakage | 5xx via `raise_internal_server_error`; provider error bodies mapped, not echoed raw |
| Audit | Log (not store content): user, surface, provider/model, tool names, token usage. Applied changes are audited by the existing `WorkflowChange` path |

## 6. Frontend

- Feature dir `components/features/ai-assistant/` (`components/`, `hooks/`, `store/`, `types/`, `utils/`).
- One reusable `AssistantPanel` (chat, tool-activity disclosure, proposal card with diff),
  mounted by each surface with a `surface` + context ref. Surfaces: template editor,
  workflow canvas, runs page, inventory page; more later.
- Settings → **AI Assistant** (per-user): enable switch, provider, model, base URL, key, test
  connection, data-sharing switches.
- **Visibility gate:** one hook, `useAiAssistantAvailable()` (TanStack Query on `/ai/status`),
  is the only way a surface decides whether to render assistant UI. When it reports
  unavailable, nothing assistant-related is rendered — no panel, no button, no empty placeholder.
- Server state through TanStack Query hooks + `queryKeys`; the stream itself via a small
  dedicated hook (`use-assistant-chat.ts`) since it is not request/response. The chat state itself
  (messages, draft, open state) lives in an in-memory session store, and the panel header offers Save
  and a Saved-conversations dialog (§18).
- Shadcn UI components only. **Diff view (agreed: simple, library-based):** use a small
  text-diff library (`diff`, i.e. jsdiff 9.x - pure JS, no UI, ships its own types) and
  render the result ourselves with Tailwind tokens (`bg-background`, destructive/success
  tokens — no arbitrary colors). Templates: line diff (`diffLines`) of old vs. proposed
  content, with changed lines highlighted. Canvas: structural diff keyed by node id (added /
  removed / changed nodes and edges listed as a readable change list; changed config fields
  shown as before/after, text-valued fields through the same line diff). No Monaco diff editor
  in v1, no side-by-side canvas rendering.

## 7. Data model (sketch)

- `user_ai_settings`: `user_id` (unique), `provider`, `model`, `base_url`,
  `enabled` (bool, default false), `api_key_encrypted` (JSON map provider -> Fernet token),
  `share_inventory_data`, `share_device_addresses`, `share_custom_fields`, `share_config_context`,
  `share_content_data` (bool, default false each), timestamps.
- `ai_conversations` (§18): `user_id` (FK, cascade), `surface`, `subject_key`, `title`, `messages`
  (JSON, redacted display messages), timestamps. Rows exist only after the user presses Save; the
  chat itself stays stateless on the server.

## 8. Permissions

One new permission, `ai_assistant:use`, added to `rbac_seed.DEFAULT_PERMISSIONS` (and therefore
undeletable, R4). `admin` has it automatically; it is **not** granted to any other role by the
seed (custom role names are not known at seed time), so an admin grants it to the roles that already
hold `workflows:write` or `templates:write` - the people who author things - and not to
viewer/read-only roles. It is deliberately *not* implied by those permissions, so an admin
can switch the assistant off for a role without touching editing rights. The assistant adds no
authority: each tool additionally enforces the underlying permission (`workflows:read`,
`templates:read`, `workflows:write` for applying, ...), so it can never exceed what the user
could do by hand. P2 (grant only what you hold) applies as usual when granting it.

## 9. Phased plan

1. **Foundation** *(done)* (gated on the SSE check, §13 decision 6): provider interface + Anthropic adapter, `user_ai_settings`, settings UI incl. data-sharing switches,
   test connection, rate limiting, SSE endpoint with a plain chat (no tools).
2. **Tool loop + template assistant** *(done)*: agent loop, read tools, `render_template`,
   `propose_template`, diff/apply UI in the template editor. Smallest slice that proves the
   whole architecture.
3. **Gemini + openai_compat adapters** *(done)*: same tools, contract tests across all providers.
4. **Workflow canvas assistant** *(done)*: step catalogue and reference tools, `propose_workflow`
   with the validation feedback loop, change-list diff.
5. **Explain & query** *(done)*: run explainer with opt-in enforcement (§14), inventory assistant (§15).
6. **Hardening** *(done, §17)*: audit trail, truncation behaviour, tool-event hints, sharing
   confirmation, redaction corpus, injection test corpus.

Testing: provider adapters against recorded fixtures; the agent loop against a scripted
fake provider (deterministic tool-call sequences); tools as ordinary service tests; a small
set of live smoke tests (opt-in, like `tests/integration`) per provider.

## 10. Phase 2 design — tool loop + template assistant

Grounded in how the template editor works today: **the editor holds all state in the browser**
(content, variables, test-device data) and may be unsaved, so the template surface sends its
*current* state with each chat turn instead of the server loading a saved row.

**Data rule for phase 2 (conservative, no class B/C values reach the model).** The editor's
variables split cleanly on `isAutoFilled`: *custom* variables are user-authored (class A) and are
sent with values; *auto-filled* ones (`device`, `nautobot`, `command(s)`, `parsed`, `batfish`,
`run_input`) hold device/run data (class B/C) and are sent **by name only**, never with values,
even if the opt-in switches are on. Their shape is documented in a curated reference
(`get_template_reference`) distilled from the editor's Jinja help, so the model can write correct
paths without seeing data. Honouring the opt-in switches for these values is deferred until the
redaction module has been proven (§4.3).

**Neutral turn model.** `ChatMessage` gains `tool_calls`, `tool_results` and an opaque
`raw` (the provider's own assistant content blocks, e.g. thinking blocks, echoed back unchanged
within one request — required by Anthropic when continuing after a tool call). The tool loop runs
entirely server-side inside one request; the client history stays plain text.

**Agent loop** (`services/ai_assistant/agent_loop.py`): max 8 tool steps per turn; a refusal, a
`max_tokens` cut-off or a step-limit hit become `error` events; tool exceptions never reach the
client (generic tool error result + server log); tool inputs validated with Pydantic; tool output
capped and redacted.

**Tools (all permission-checked as the calling user, all read-only or proposal-only):**

| Tool | Class | Purpose |
|------|-------|---------|
| `get_template_reference` | A | Curated Jinja/namespace reference (what `device`, `nautobot`, `commands`, `parsed.*`, `run_input` contain) |
| `list_templates` / `get_template` | A | Existing saved templates as examples (needs `templates:read`) |
| `render_template` | A | Render editor content (or given content) with *custom* variables + model-supplied sample data; withheld variables render as `<<name>>` and are reported |
| `propose_template` | proposal | Syntax check + trial render; on success emits a `proposal` event. Never persists |

**Redaction (pulled forward from phase 6 for what phase 2 sends).** Template source and custom
variable values are class A but can contain pasted secrets. A text redactor replaces secrets with
**restorable tokens** (`__SECRET_1__`), and `propose_template` restores them, so redaction never
corrupts an edit: if the model keeps the token the original secret line round-trips; if it deletes
it the secret is gone. Patterns are the §4.3 set (PEM blocks, Cisco `enable|username` secrets,
tacacs/radius keys, SNMP communities/v3 keys, routing/NTP/HSRP keys, generic `password=` style
assignments, bearer/basic headers) and never touch Jinja expressions (`{{ ... }}`).

**Proposal flow.** `propose_template` → SSE `proposal` event → the editor shows a line diff
(jsdiff) against its *current* buffer with Apply/Reject. Apply writes into the **unsaved editor
buffer** only; the user saves with the normal Save. If the buffer changed since the turn started,
the card says applying will overwrite those edits.

**UI.** An "AI Assistant" button in the template editor toggles an inline right-hand panel, rendered
only when `useAiAssistantAvailable()` is true. Tool activity shows as collapsed one-line chips.

## 11. Phase 4 design — workflow canvas assistant

Grounded in the existing external-AI path (`ai_workflow_apply.py`, `WorkflowValidationService`
tiers 1–4, `contributing-data/workflow-gallery/*.json`) and the builder's client-side canvas state.

**Compact plan, server-side expansion.** A persisted canvas node carries ~20 fields (denormalized
registry data, `measured`, `stepUuid`, positions...) and edges have a fixed id/handle scheme. Asking a
model to emit that JSON is fragile, so the model works in a compact vocabulary and the server expands it:

- node: `{id, kind, title?, config, disabled?}` — `kind` is a registry step id, `config` its
  `pluginConfig`.
- edge: `{from, outcome, to}` — `outcome` must be one of the step's registry outcomes.
- `static_attributes`: the existing `StaticAttributeDef` list, passed through.

The model always sends the **complete** plan (full replacement, like the external path). The server
merges it onto the canvas the client sent: an existing node id with the same `kind` keeps its position,
size, `stepUuid` and everything the model did not touch; new nodes are built from the registry and
placed next to their parent; unchanged edges keep their waypoints/style; canvas decorations (labels,
backgrounds, funnels) and groups pass through untouched (groups are repaired like
`WorkflowService._repair_orphan_groups`).

**Validation loop (the main quality lever).** `propose_workflow` expands the plan and runs
`WorkflowValidationService` (Tier 1 schema, Tier 2 references, Tier 3 capability flow, Tier 4
attribute-path wiring) as the calling user. Any *error* is returned to the model as a tool error
(with node ids and codes) so it fixes and re-proposes; **no proposal is emitted while errors remain**.
Warnings are carried on the proposal. This is stricter than the external path, which only refuses
Tier 2 drift, and matches the run-time gate (`RunService` refuses Tier 1–3 errors anyway).

**Context sent each turn (client → server):** the raw canvas (`canvas_nodes`, `canvas_edges`,
`canvas_groups`, `static_attributes`) — the server builds the model's compact view, so formats cannot
drift. Caps: 300 nodes, 600 edges. Step configs are class A (workflow definition) but pass through
redaction; secret-named keys and sealed envelopes are **tokenised and restored** on propose, so an edit
can never overwrite a real secret with a placeholder (`Redactor.tokenize_data` / `restore_data`).

**Tools (all permission-checked as the calling user, read-only or proposal-only):**

| Tool | Class | Purpose |
|------|-------|---------|
| `get_workflow_reference` | A | Authoring rules: node/edge model, outcomes, capability flow, fan-out/fan-in, static attributes, conventions |
| `list_steps` / `get_step_schema` | A | Step catalogue from the registry; full config schema, outcomes, capabilities for one step |
| `list_references` | A | Credentials (id/name/type only, never secrets), git repositories, sources, saved inventories — so references are real, never invented |
| `validate_workflow` | A | Run the tiers on a plan without proposing |
| `propose_workflow` | proposal | Expand + validate; emits the `proposal` event with a change summary |

**Not in phase 4:** running a workflow, editing workflow metadata (name/folder/visibility), notes,
creating schedules, canvas groups beyond preserving existing ones.

**Proposal flow.** The card lists added / removed / changed steps (changed ones with a before/after
config diff) and added / removed edges, with validation warnings. **Apply** loads the merged canvas into
the open builder as **unsaved** state (`applyLoadedCanvas` + mark dirty); the user reviews it on the
canvas and saves with the normal Save, which also runs the server-side validation again.

## 12. Implementation status

**Phase 1 (settings, Claude adapter, SSE chat) - verified by the product owner with a real key:**

- Backend: `core/models/user_ai_settings.py`, `repositories/user_ai_settings_repository.py`,
  `services/ai_assistant/` (settings, chat, providers, prompts), `routers/ai_assistant.py`
  (`GET /ai/status`, `GET|PATCH /ai/settings`, `POST /ai/settings/test`, `POST /ai/chat`),
  permission `ai_assistant:use`.
- Frontend: `components/features/ai-assistant/` (SSE parser, `useAssistantChat`,
  `AssistantPanel`, `useAiAssistantAvailable`), Settings → AI Assistant section.
- SSE through the Next.js dev proxy verified with a probe endpoint (incremental delivery, no
  gzip buffering). **Not yet verified for a production build / Docker ingress.**
- Key storage is Fernet only (`EncryptionService`); OpenBao storage is deferred.
- Data-sharing enforcement did not exist yet in this phase (no class B/C tool); it was added in
  phase 5 (§14, §16).
- Not done: server-side `fallbacks` for refusals (a refusal is reported as a clear error).

**Phase 2 (template assistant) - verified by the product owner with a real key:**

- Backend: `services/ai_assistant/` gained `redaction.py` (restorable-token redactor, 26 tests),
  `agent_loop.py` + `tools/base.py` (tool loop, one choke point for validation/redaction/size
  caps), `tools/template_tools.py` (5 tools), `template_render.py` (lenient sandboxed render),
  `template_reader.py` (per-call DB session + RBAC), `surfaces.py` (prompt + toolbox per surface),
  `knowledge/template_reference.md`. The Anthropic adapter now does tool use, echoing the
  provider's raw blocks. `POST /ai/chat` accepts an optional `context` (template editor state).
- Frontend: tool-activity chips, `proposal` events, `TemplateProposalCard` (line diff via `diff`
  9.x), "AI Assistant" button + inline panel in the template editor, gated by
  `useAiAssistantAvailable()`. Apply writes into the **unsaved** editor buffer.
- Verified: backend unit tests (adapter tested against real SDK message types), frontend
  vitest/tsc/eslint, and by the product owner: template Q&A and added lines through a proposal.
- Trial renders run in a killable child process with CPU / memory limits and a 5 s timeout
  (`render_isolated.py`), and the sandbox caps `*` / `**` results.
- Known limits: only the template
  *content* is proposable (not variables/options); the template surface still sends no class B/C
  data (device and run variables by name only), so the opt-in switches do not apply to it.

**Phase 3 (Gemini + OpenAI-compatible):**

- Adapters: `providers/gemini_provider.py` (Gemini API `generateContent`, `streamGenerateContent`
  over SSE, `x-goog-api-key` header, tools via `parametersJsonSchema`, the model's `parts` echoed back
  unchanged for thought signatures) and `providers/openai_compat_provider.py` (`/chat/completions`
  SSE, tool-call fragment assembly, optional key). Both on `httpx` with a shared `http_common.py`
  (neutral error mapping, SSE reading, **no redirects followed**); a contract test suite runs the same
  expectations against both (`tests/unit/test_ai_http_providers.py`, `httpx.MockTransport`).
- Why `generateContent` and not Gemini's newer Interactions API: Google documents `generateContent`
  as "fully supported" (no deprecation announced) and the stateless tool loop maps onto it directly.
  Revisit if Google deprecates it.
- Gemini models offered: `gemini-3.8-flash` (default), `gemini-3.5-flash-lite`,
  `gemini-3.1-pro-preview` (preview). Which ones a free-tier key may call is unknown; a 429/quota
  error shows the neutral rate-limit message. OpenAI-compatible takes a **free-text model**.
- **One key per provider** (individually encrypted, JSON map in the existing column; the earlier single
  token is still read). Switching provider no longer makes another provider's key look valid.
  `configured` replaces "has a key" as the readiness test: a key for hosted providers, a server URL +
  model for OpenAI-compatible (the key is optional there).
- **SSRF decision:** no new bypass for local servers. The server URL goes through `core.safe_urls`
  (via `base_url_policy.py`) when saved and again before every call; a server on the backend's own
  machine (`localhost`) is reachable only when `ALLOW_LOOPBACK_SOURCE_URLS` is enabled, a LAN host
  (RFC1918) just works. Outside development an API key is only sent over https.
- **Transient failures:** the httpx adapters retry HTTP 500/502/503/504 and connection errors up to twice
  (1 s, 2 s) *before* any output is streamed, never 429 (quota). Error messages now carry the HTTP status
  and the provider's short error category (e.g. `HTTP 503 UNAVAILABLE`) but never its free text.
  Observed in real use: `gemini-3.8-flash` answered 503 on a free-tier key while `gemini-3.5-flash-lite`
  worked; cause not established (a 503 is server-side, not the usual free-tier signal).
- Verified by the product owner (2026-10-10): real Anthropic, Gemini and Ollama turns work.

**Phase 4 (workflow canvas assistant):**

- Backend: `workflow_expand.py` (compact plan <-> persisted canvas: registry-built nodes, layout next to
  parents, edge id/handle scheme, position/uuid/waypoint preservation, decoration + group pass-through,
  change summary), `tools/workflow_tools.py` (6 tools), `workflow_reader.py` (per-call DB sessions,
  RBAC-checked reference lists, validation as the calling user), `knowledge/workflow_reference.md`,
  `Redactor.tokenize_data/restore_data` (secrets in step configs round-trip), tool schemas are inlined
  (no `$ref`) for every provider. `POST /ai/chat` accepts `context.surface == "workflow_editor"`.
- Frontend: "AI Assistant" button + side panel in the workflow builder (only while the assistant is
  available), `WorkflowProposalCard` (added / removed / changed steps with config diff, edges, warnings,
  stale-canvas notice), Apply loads the merged canvas as **unsaved** state via the same path as opening
  a workflow.
- Verified: unit tests (expansion, tools, router, redaction); the real `WorkflowValidationService` accepts
  a correct expanded plan and returns the Tier 3 `missing_capability` / Tier 2 `source_not_found` errors
  for broken ones; reference lists and permission checks against the real dev DB.
- Not verified: a real model driving the loop (plan quality with Haiku / Flash-Lite on non-trivial
  workflows is unknown), the UI in a browser, and apply/undo behaviour on a large canvas.
- Known limits: `stop-here` inside a fan-out branch is only rejected at save time (`WorkflowService`),
  not by the proposal validation; canvas groups are preserved but not created; workflow metadata
  (name, folder, notes, schedules) is out of scope.

## 13. Decisions and open questions

Decided (2026-10-10):

1. **Adapters vs. LiteLLM:** thin hand-written adapters.
2. **Storage:** dedicated `user_ai_settings` table.
3. **History:** the chat request is stateless and client-held. The panel keeps its session in memory
   while the user works and loses it on reload or sign-out (§18); the user can save a conversation
   on the server explicitly (decision 18).
4. **Data sharing:** opt-in only for anything device- or run-derived (§4). Config backups and
   command output may contain secrets.
5. **Permission:** `ai_assistant:use`. `admin` has it automatically; an admin grants it to the roles
   that hold `workflows:write` or `templates:write` (§8).
6. **SSE through the Next.js proxy:** must be verified without buffering *before* we commit to
   SSE; this was the first task of phase 1. `frontend/src/lib/api-proxy.ts` returns non-JSON
   responses as `new NextResponse(response.body, ...)` (streamed, not buffered), and a probe
   `text/event-stream` endpoint confirmed incremental delivery through the **dev** server with and
   without `Accept-Encoding: gzip`; chat works in real use. **Not verified:** a production build or a
   reverse proxy / ingress (see `docker/DOCKER.md`). Fallback if it buffers: a dedicated streaming
   route handler, or polling.
7. **Providers equal:** no per-model handling. Gemini's free tier is for testing; its limits are
   unknown, so quota errors must degrade gracefully (§3.1).
8. **Applying a canvas proposal:** apply into the **open editor state, unsaved**. The user then
   reviews it on the canvas and uses the normal Save (with its validation, `WorkflowChange`
   audit and git versioning), and normal undo applies. This keeps exactly one persistence path
   and makes "Apply" low-stakes. Template proposals follow the same rule (applied into the
   editor buffer, saved by the user).

Decided (2026-10-10, second round):

9. **Redaction** (refined by decision 12): layered pipeline (§4.3) — reuse the existing structured redactor and URL scrub,
   add a conservative free-text regex layer for config text. The existing run-secret exact-match
   layer does not apply outside a run.
10. **Step error text:** treated as sensitive (class C) for now.
11. **Diff view:** simple, built on a diff library (jsdiff), rendered with our own Tailwind/Shadcn
   styling (§6).

Decided (2026-10-10, later rounds):

12. **Redaction:** restorable tokens instead of a literal marker (§4.3, §10); structured configs
    via `tokenize_data` / `restore_data`.
13. **Providers:** hand-written adapters on `httpx` for Gemini (`generateContent`, not the newer
    Interactions API) and OpenAI-compatible; official SDK for Anthropic; one key per provider; no SSRF
    bypass for local servers (§3.2, §12).
14. **Workflow authoring:** compact plan expanded and validated server-side; no proposal while errors
    remain (§11).

Decided (2026-10-10, phase 5):

15. **Opt-in is enforced in the tool layer** through `SharingPolicy` on `ToolContext` (§14); the
    result carries a `{"not_shared": ...}` marker so the model can tell the user what to enable.
16. **Device names are class B.** With inventory sharing off, tools show `device-1`, `device-2`
    (stable within one request) so a failure can still be discussed per device; the real name is
    not accepted as a `device` filter either.
17. **Run `run_inputs` and every error text are class C**; `error_category` and `error_id` are
    metadata and always shown.

Decided (2026-10-10, sessions):

18. **Sessions and saving (§18):** the panel session lives in an in-memory store keyed by surface and
    subject, and a running turn is cancelled when the user leaves. A conversation is saved
    server-side only on an explicit Save, redacted, with proposals reduced to a summary.

Still open:

- Read-only Nautobot GraphQL queries for open questions ("which devices are in City A?"); see
  `doc/OPEN_TODOS.md` "AI assistant: Nautobot GraphQL queries".
- Inventory assistant follow-ups (§15): awareness of the unsaved filter being built and the loaded
  inventory, and proposing a filter ("all core switches at site X") as a reviewable proposal.
- Keeping a session across a full reload (not done on purpose: messages may hold device or run
  data, so nothing is written to browser storage).
- A wider real-world redaction corpus (add a case to `test_ai_redaction_corpus.py` whenever a leak is found).
- Whether to register the user's credential secrets for exact-match scrubbing later.
- Production verification of SSE behind the real ingress, and of the workflow assistant path with a
  real model (see §12 "Not verified"). Gemini and Ollama work (product owner, 2026-10-10).
- Cause of the `gemini-3.8-flash` HTTP 503 seen on a free-tier key (retry + clearer errors added; cause
  not established).

## 14. Phase 5 design - run explainer and opt-in enforcement

**Surface.** `POST /ai/chat` accepts `context = {surface: "run_viewer", run_id?}`. The runs page
(`/workflows/runs`) shows an "AI Assistant" button (only while the assistant is available) that opens
a side panel; the context carries the open run (`activeRunId`), so the model starts on the right run
and can still be asked about another id. The surface is read-only: no proposal tool, no execution.

**Opt-in enforcement (`services/ai_assistant/data_sharing.py`).** The router builds a `SharingPolicy`
from the user's saved `share_inventory_data` / `share_content_data` on every chat request and the
session puts it on `ToolContext.sharing`, so switching a setting takes effect on the next turn.
Tools call `gated(policy, DataClass.X, value)`; off means the value is replaced by
`{"not_shared": "<class>", "message": ...}`. Classification of what the run tools return:

| Always shown (metadata) | Class B (inventory) | Class C (content) |
|---|---|---|
| run / step status, timings, `error_category`, `error_id`, step type + name, outcome names, capabilities, command success flag, artifact ids, attribute group and parsed key *names* | device names (else `device-N`), `attributes` values | `error_message` (run, step, group), device `errors`, command `summary`, `parsed` values, `run_inputs`, command text, event `message`, artifact text |

The tool output is then redacted twice: `Redactor.redact_data` on structured results (secret-named
keys, sealed envelopes, then every string leaf through the text redactor) and the text redactor again
in the `Toolbox` choke point. The panel header shows the provider and the enabled classes
(`DataSharingNotice`), with a link to the settings.

**Known limits (by design).** Class C text (errors, event messages, command summaries, artifact text)
often contains hostnames and IPs; the `device-N` substitution applies to structured fields only, so
enabling content sharing alone can still reveal device names. `get_run_workflow` is class A (§4.1,
same as the workflow-editor surface): step configs can hold device names or filters, so it is not
gated. Labels are seeded from all devices of the run in sorted order, so they are stable across
tools and turns. Long strings are capped at 2000 characters, artifacts at 8000 (redacted first).

**Access.** `run_reader.py` delegates to `RunService`, so private-workflow visibility is the same as
for the REST endpoints, and additionally requires `workflow_runs:read` (and `workflows:read` for
`get_run_workflow`). A missing run and a forbidden run give the same message.

**Verified.** 23 unit tests (`tests/unit/test_ai_run_tools.py`: each B/C field with the switch off and
on, inventory-only does not leak content, label filtering, artifact truncation and redaction, access
errors, injected text stays inside JSON) and 3 router tests (saved switches reach the surface); the
tools were also run against real rows of the dev database with the switches off and on.

**Not verified:** a real model explaining a real failed run (the dev database has only successful
runs) and the panel in a browser. The injection corpus is in §17.

## 15. Phase 5 design - inventory assistant

**Decision (2026-10-10):** inventory questions live in a panel on the inventory page
(`/inventory`), not on the runs page or a global panel.

**Surface.** `context = {surface: "inventory", source_id}`; `source_id` is the Nautobot source the page
already uses. The button appears only while the assistant is available and the source is ready. The
surface is read-only.

**Data and access.** `inventory_reader.py` runs as the calling user: `sources.nautobot:read`, saved
inventories through `InventoryService` (another user's private inventory looks like a missing one), and
device data through the same `NautobotSourceService` the page uses (Redis-cached bulk data). DB work
happens in a worker thread; the Nautobot calls are awaited after the session is closed.

**Opt-in.** Device data is class B. With the switch off `resolve_inventory` returns only the inventory
name and `total_count` (the size) and `search_devices` / `get_device_attributes` return the `not_shared`
marker. With it on, device rows are limited to 50, string values to 500 characters, and results pass
`Redactor.redact_data` (secret-named custom fields such as `snmp_password` are redacted). The aggregate
`counts_by` block is computed over all devices so "how many ..." questions are exact even when rows are
truncated.

**Verified.** 12 unit tests (`tests/unit/test_ai_inventory_tools.py` plus 2 router tests): sharing off
and on, counts over 100 devices with a 5-row limit, field projection, secret redaction, unknown
inventory, denied access. The tools were run against the live Nautobot source and dev inventories.

**Not verified:** a real model answering inventory questions, the panel in a browser, and behaviour on a
large (thousands of devices) inventory.

**Not built:** the assistant does not see the unsaved filter or loaded inventory of the page (it works
from saved inventories by id), and it cannot propose filters. See §13 open items.

## 16. Fine-grained inventory opt-in

**Why.** Device basics rarely carry sensitive values, but addresses, custom fields and especially the
Nautobot config context often do (keys, passwords, addressing), and the key-name redactor cannot
recognise a secret under an unmarked key (a value under `key` or `comments` is not caught). So the user
decides per category.

**Switches** (Settings -> AI Assistant -> Data sent to the model; the three are nested under the base
switch and disabled while it is off). Each category works only while `share_inventory_data` is on
(`SharingPolicy.allows`), whatever its own value.

| Setting | `DataClass` | Releases |
|---|---|---|
| Inventory and device attributes (base) | `inventory_data` | name, role, platform, device type, manufacturer, location, status, tags, face, position; inventory sizes and `counts_by` |
| Addresses and serial numbers | `device_addresses` | `primary_ip4/6`, `oob_ip`, `ip_addresses`, `interfaces`, `hostname`, `serial`, `asset_tag` |
| Custom fields | `custom_fields` | `custom_fields`, `_custom_field_data`, `computed_fields` |
| Config context | `config_context` | `config_context`, `local_config_context_data` |

**Enforcement** (`data_sharing.py`, tool layer):

- `resolve_inventory` / `search_devices`: a requested field whose category is off is dropped, and the
  result lists it under `withheld_fields` with the setting that would release it.
- `get_device_attributes`: an allow-list. Names in none of the sets above (for example `comments`) are
  **never** sent, even with every switch on; they are reported as `"never"`. Asking for an attribute by
  name does not bypass this.
- Run tools: attribute bags in a step result (`include=['attributes']`) are masked recursively by key
  name, so a `primary_ip4`, `custom_fields` or `config_context` nested anywhere shows
  `{"not_shared": ...}` unless its category is on. This is a deny-list because run bags hold arbitrary
  per-source keys.
- The system prompt and the panel notice name exactly what is enabled.

**Known limits.** Class C text (errors, command output) can still contain IPs once content sharing is on.
A secret stored under a non-secret-looking key inside a category the user enabled is not recognised by
the redactor; that is the residual risk the opt-in makes explicit. Not built: a per-user list of custom
field names that are always withheld (add if asked for).

**Verified.** Unit tests for the policy (`tests/unit/test_ai_data_sharing.py`), each category per tool,
the base-switch requirement, the allow-list and the run-bag mask; 5,115 backend tests pass. The new
columns are added at startup by `AutoSchemaMigration` (NOT NULL with a Python default). Not verified:
the settings page in a browser.

## 17. Phase 6 - hardening

**Audit trail** (`audit.py`, logger `ai_assistant.audit`). One INFO line per chat turn, written even
when the turn fails: `user_id`, `surface`, `provider`, `model`, tool names, withheld data classes,
input / output tokens and `outcome` (`ok` or `error:<code>`). Never prompts, tool results or content.
Applied changes stay audited by the existing `WorkflowChange` path (§5).

**Truncation.** The choke point (`Toolbox`) now cuts an oversized result at a line boundary and appends
`[output truncated: showed N of M characters; tell the user the answer is based on partial data]`
instead of cutting mid-value. Tools that cap themselves (artifact text, device rows) set
`ToolOutput.truncated` too. The `tool` SSE event carries `truncated` and `withheld`.

**Hints in the panel.** A tool chip shows "(partial result)" and, when the user's opt-ins blocked part
of a result, "needs <setting> - enable" with a link to the settings. `withheld` is derived from the
`not_shared` markers our own gating emits, so a forged marker in third-party text can at worst show a
harmless hint.

**Sharing confirmation.** Turning any data-sharing switch on (base, the three categories, run and device
content) asks first, naming the data and repeating that redaction is best-effort; turning it off is
immediate and applies from the next message (`ShareConfirmSwitch`).

**Redaction.** A corpus of 36 realistic lines (IOS, NX-OS, EOS, Junos, generic) now must not leak
(`tests/unit/test_ai_redaction_corpus.py`). It found 11 gaps, closed by new patterns: IPsec
`isakmp key` and `pre-shared-key`, BGP `neighbor ... password`, PPP chap / pap, `wpa-psk`, Arista
`sha512` secrets, quoted Junos `encrypted-password` / `authentication-key` / `secret`, Junos
`community X {`. A second gap found by the injection corpus: `enable secret` and `username ...
secret` were matched only at the start of a line, so a secret embedded in a log or error sentence
leaked; those anchors were relaxed (false positives are accepted by design). Hostile input (very long
lines, repeated tokens) is tested to redact in under 2 s.

**Injection corpus** (`tests/unit/test_ai_hardening.py`). Six payloads (instruction override, forged
closing tags and fake system turns, JSON breakout, fake dialogue, Jinja / SSTI, social engineering for
secrets) placed in run errors, step names and artifacts are asserted to stay inside quoted JSON or the
`<artifact>` fence; a forged closing tag does not end the fence. A scripted model that obeys an
injection and asks for `propose_workflow`, `propose_template`, `trigger_run` or `execute_command` on a
read-only surface gets "Unknown tool" and no `proposal` event is emitted; no read-only surface offers a
tool whose name starts with propose / run / trigger / execute / delete. Secrets inside injected text are
still redacted.

**Not done / limits.** Prompt injection cannot be excluded for the model's text answer (it may repeat
what a tool result said); the safety property is that it cannot act (no write or execution tool on any
read surface; writes are proposals the user reviews). Redaction stays best-effort. Not verified: the new
confirmation dialog and chip hints in a browser.

## 18. Sessions and saved conversations

**Session across navigation (frontend only).** `ai-assistant/store/assistant-session-store.ts` is an
in-memory Zustand store: per session key the open state, the messages, the draft and the id of the
saved conversation the chat belongs to. Keys: `template_editor:<id|new>`, `workflow_editor:<id|new>`,
`run_viewer`, `inventory:<sourceId>`, so returning to workflow A restores A's chat and opening B
starts a new one. At most 10 sessions are kept (least recently used dropped).

- `useAssistantChat({ sessionKey })` reads and writes that store. **Leaving the page, or switching to
  another key, cancels the running turn** (decision of the product owner); an empty cancelled reply is
  marked "Cancelled", partial text is kept, and cancelled replies are not sent back to the model.
- Cleared by the Clear button (that session), logout and any 401 from chat (all sessions). A full reload
  clears everything: nothing is written to `sessionStorage`/`localStorage`, since messages can hold
  device or run data.
- Pending proposals survive; the stale-edit check compares against the editor at render time, so it
  still works on a restored message.

**Saved conversations (server side, explicit Save).** The panel header has **Save** (becomes **Update
saved** once the chat was saved or resumed) and **Saved**, which opens a list for the current surface
and subject with Resume and Delete. Only panels given a `conversationScope` show them; the Settings
"Try it" panel does not.

| Endpoint | Purpose |
|---|---|
| `GET /ai/conversations?surface=&subject_key=` | Summaries (no messages), newest first |
| `GET /ai/conversations/{id}` | One conversation with its messages |
| `POST /ai/conversations` | Save a new one; title defaults to the first user message (80 chars) |
| `PUT /ai/conversations/{id}` | Replace messages and/or rename |
| `DELETE /ai/conversations/{id}` | Delete |

- **Access:** `ai_assistant:use`, like the settings endpoints (not the enable switch: a user can still
  list or delete what they saved). Rows are private to the owner; another user's id answers 404. Writes
  are rate limited (`ai-conversations`, 30 / 60 s).
- **What is stored** (`services/ai_assistant/conversation_service.py`): message text, error text, tool
  chips (name and status) and, for a proposal, only its kind and summary. All text goes through
  `Redactor.redact` first, so a stored conversation holds no more than the model was shown; the tokens
  are not restorable. A full proposal payload is rejected by the request model (`extra="forbid"`).
- **Resume** loads the stored messages into the current session as history; the server needs no change
  because chat history is plain role/content. A resumed proposal shows as "Earlier ... proposal (not
  applicable after resuming)", since the canvas or template has changed.
- **Limits:** 50 messages of 20,000 characters, 200,000 characters per conversation (413
  `ai_conversation_too_large`), 100 conversations per user (409 `ai_conversation_limit`).
- **Retention:** conversations not updated for `AI_CONVERSATION_RETENTION_DAYS` (default 90, `0` keeps
  them) are purged by the `purge_ai_conversations` task of the daily Hatchet housekeeping workflow
  (`hatchet/workflows/purge_retention.py`). Deleting a user deletes their conversations (FK cascade).
- **Why explicit Save, not autosave:** a conversation may contain text derived from opted-in device or
  run data (classes B/C); writing that to the database for every chat would bypass the point of the
  opt-in. The dialog says where it is stored and that redaction is best-effort.

**Verified.** Backend unit tests for owner isolation, redaction on save, size and count caps,
retention and the HTTP status codes (`test_ai_conversation_service.py`,
`test_ai_conversations_router.py`); frontend tests for the store, the mapping and the Save/Resume/Delete
flow. The product owner tried it in the browser (2026-10-10): navigating away and back keeps the chat,
and a conversation can be saved, the page reloaded and the conversation resumed. Not verified: the
retention purge against a real Hatchet worker, and delete / second-user isolation in the browser (covered
by the router tests only).

