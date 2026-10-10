# In-App AI Assistant — Requirements & Design

Status: **phases 1 and 2 verified by the product owner against the real Claude API (template Q&A and
proposals work). Phase 3 (Gemini + OpenAI-compatible) implemented 2026-10-10, covered by unit/contract
tests only — not yet tried with a real Gemini key or an Ollama server.** Phase 4 (workflow canvas assistant) implemented 2026-10-10, unit-tested and checked against the real
validator/registry/dev DB, but not yet tried with a real model or in a browser. Phases 5–6 are not started. Open questions
were answered by the product owner; see §9 for the recorded decisions.

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
| Entry points: template editor, workflow canvas | Run page, inventory, change requests, global panel |
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
Frontend chat panel  ──►  /api/proxy/ai/*  ──►  routers/ai_assistant.py
 (SSE stream, diff UI)                              │  (auth, rate limit, thin)
                                                    ▼
                                      services/ai_assistant/
                                        ├─ agent_loop.py      tool loop, step/token caps
                                        ├─ context/           per-surface context builders
                                        ├─ tools/             tool registry + implementations
                                        ├─ providers/         anthropic, gemini, openai_compat
                                        ├─ key_store.py       per-user key resolution
                                        └─ proposals.py       proposal model + validation
                                                    │
                      existing services (workflow, templates, validation, runs, nautobot, registry)
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
- Encrypted at rest with the same mechanism as credentials (Fernet, or OpenBao when
  `VAULT_ENABLED`). Stored in a dedicated `user_ai_settings` table (agreed): the
  provider/model/base-URL fields don't fit `Credential`.
- Key resolution goes through the secret-handling path that registers the value for
  run-scoped redaction (`unwrap_secret` / `CredentialsService.get_decrypted_*`).
- Base URL passes `core/safe_urls.py` validation. Local (Ollama) endpoints are legitimately
  private addresses, so this needs an explicit, documented allowance for the
  `openai_compat` provider rather than weakening the global policy.
- "Test connection" button (cheap request, rate limited).

### 3.3 Agent loop

- Backend-driven; the frontend only sends a prompt plus a *surface context reference*
  (e.g. `{surface: "template", template_id: 7}`) and renders the event stream.
- Hard caps: max tool steps per turn, max output tokens, request timeout, and a per-user
  `rate_limited("ai-assistant", ...)` budget.
- Streams events over SSE: text deltas, `tool_call` / `tool_result` (collapsed in the UI),
  `proposal`, `error`, `done`. The Next.js proxy must pass streaming through unbuffered —
  verify this early, it is the main frontend unknown.
- Conversations are held client-side per surface in v1 and re-sent each turn (stateless
  server). Persisting history is a later decision; see open questions.

### 3.4 Context (option 2)

Each surface contributes a context builder, so the model starts informed instead of
discovering everything via tool calls:

| Surface | Injected up front |
|---------|-------------------|
| Template editor | current template (content, variables, type), Jinja conventions of this app, available variable sources |
| Workflow canvas | compact current definition (nodes, edges, configs), step catalogue summary, selected node |
| Run explanation | run metadata, step result *metadata*, failed step's error — content data fetched on demand |

Keep it compact: summaries up front, details through tools. Large content data (command
output, config backups) is truncated with an explicit marker and fetchable via a tool.

### 3.5 Tools (option 3)

All tools take/return JSON, run as the calling user, and have bounded output sizes.

**Read tools**

| Tool | Purpose |
|------|---------|
| `list_steps` / `get_step_schema(step_id)` | Step catalogue from `registry.yaml` + config schema, consumes/produces capabilities |
| `get_workflow(id)` / `list_workflows` | Definition + canvas, subject to workflow visibility rules |
| `get_template(id)` / `list_templates` | Template content and variables |
| `list_inventories` / `resolve_inventory(id)` | Inventory definitions and the devices they resolve to (bounded) |
| `get_device_attributes(device, groups)` | Cached Nautobot attributes (never credentials) |
| `list_credentials` | Names/ids/types only — **never** secret material |
| `list_git_repositories` | Names/ids/categories |
| `get_run(id)` / `get_step_result(run, node)` | Metadata always; content data truncated, on request |
| `render_template(template_or_content, device)` | Pure render against a sample device; returns output or the Jinja error with line |
| `validate_workflow(definition)` | Existing Tier 1–4 validation → findings |

**Proposal tools (no persistence)**

| Tool | Purpose |
|------|---------|
| `propose_template(patch)` | Validates with a trial render; returns findings; emits a `proposal` event |
| `propose_workflow_patch(patch)` | Runs validation on the patched definition; emits a `proposal` event |

Rule for new tools: if it cannot be classified as "pure read" or "proposal", it does not
ship in this feature.

### 3.6 Proposals and the diff UI

A proposal is `{kind, target_id | null, base_version, patch, validation_findings}`.

- The UI shows a diff (template text diff; canvas diff highlighting added/changed/removed
  nodes and edges) and **Apply / Reject**.
- `base_version` (e.g. `updated_at`) guards against applying onto a changed target:
  stale proposals are rejected with a clear message.
- **Apply** calls the ordinary workflow/template save endpoints from the browser, as the
  user. The backend has no "apply proposal" shortcut, so there is exactly one write path.
- Validation errors block *Apply* for workflows (consistent with the external AI path,
  which refuses to write on Tier 1–3 errors); warnings are shown.
- Reuse `doc/ai_collaboration/AI_DEFAULTS.md` / `ai_defaults.yaml` thinking: the model must
  reference credentials, git repositories and sources by real ids obtained from tools,
  never invented ones — Tier 2 reference validation enforces it.

### 3.7 Explain & query features

- **Run debugging:** the model reads run metadata → failed step result → run events,
  and explains cause and likely fix. Read-only; possibly a "Explain this failure" button
  on the runs page later (out of scope v1, but the tools above already support it).
- **Workflow/template explanation:** "what does this do" over the in-context definition.
- **Inventory questions:** resolved via `resolve_inventory` + `get_device_attributes`;
  bounded by device-count caps, and the answer must say when it was truncated.

## 4. Data sharing — opt-in only

**Anything beyond the assistant's own working material is sent to the model only if the user
has explicitly opted in.** Config backups and command output can contain passwords, keys,
SNMP communities and other secrets, so the default is "off" for everything that comes from
devices or runs.

### 4.1 Data classes

| Class | Examples | Default |
|-------|----------|---------|
| **A. Definitions** | Step catalogue/schemas, workflow definitions and canvas, template content and variable names, credential/repo *names and ids* | Sent (needed for the feature to work). Credential secrets are never in this class. |
| **B. Inventory & attributes** | Device names, Nautobot attributes, resolved inventories | **Opt-in** |
| **C. Content data** | Config backups, command output, parsed output, generated artifacts, step `content` results, run logs/events, step error text (may echo output) | **Opt-in** |
| **D. Secrets** | Decrypted credentials, vault values, keys | **Never sent**, not even with opt-in |

Class A still passes through the redaction layer, because a template or workflow config can
contain a pasted secret.

### 4.2 Rules

1. **Per-user, default off.** Stored in `user_ai_settings` as `share_inventory_data` (B) and
   `share_content_data` (C). Independent switches; C does not imply B.
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
small, conservative, ordered set of regexes for text, replacing only the secret part with
`***REDACTED***` and keeping the surrounding line so the model can still reason about the
config:

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

Additional rule: when the model quotes redacted content back into a proposal (e.g. rebuilds a
config template), the `***REDACTED***` marker must not be persisted as if it were a real value.
The proposal validator rejects the literal placeholder in template content and workflow config.

Not in v1 (documented gaps): registering the user's own credential secrets for exact-match
scrubbing, and ML/entropy-based detection.

## 5. Security & privacy

| Concern | Mitigation |
|---------|-----------|
| Key theft | Per-user, encrypted, write-only API, redaction registration, never logged |
| Secrets in prompts | No tool returns decrypted credentials; run-scoped redaction applied to tool output before it reaches the model |
| Prompt injection | Proposal-only writes, no execution tools, diff review (principle 4) |
| Data exfiltration to a 3rd-party LLM | Opt-in only for device-derived data (§4); active provider and enabled data classes shown in the panel; Ollama as the local option |
| SSRF | Base URL through `safe_urls`; documented private-address allowance for `openai_compat` only |
| Cost / runaway loops | Step, token and time caps; per-user rate limit |
| Error leakage | 5xx via `raise_internal_server_error`; provider error bodies mapped, not echoed raw |
| Audit | Log (not store content): user, surface, provider/model, tool names, token usage. Applied changes are audited by the existing `WorkflowChange` path |

## 6. Frontend

- Feature dir `components/features/ai-assistant/` (`components/`, `hooks/`, `types/`).
- One reusable `AssistantPanel` (chat, tool-activity disclosure, proposal card with diff),
  mounted by each surface with a `surface` + context ref. Surfaces: template editor,
  workflow canvas (v1); more later.
- Settings → **AI Assistant** (per-user): enable switch, provider, model, base URL, key, test
  connection, data-sharing switches.
- **Visibility gate:** one hook, `useAiAssistantAvailable()` (TanStack Query on `/ai/status`),
  is the only way a surface decides whether to render assistant UI. When it reports
  unavailable, nothing assistant-related is rendered — no panel, no button, no empty placeholder.
- Server state through TanStack Query hooks + `queryKeys`; the stream itself via a small
  dedicated hook (`use-assistant-stream.ts`) since it is not request/response.
- Shadcn UI components only. **Diff view (agreed: simple, library-based):** use a small
  text-diff library (`diff`, i.e. jsdiff — pure JS, no UI, ships types in current
  majors; confirm the exact version and that it is not abandoned at implementation time) and
  render the result ourselves with Tailwind tokens (`bg-background`, destructive/success
  tokens — no arbitrary colors). Templates: line diff (`diffLines`) of old vs. proposed
  content, with changed lines highlighted. Canvas: structural diff keyed by node id (added /
  removed / changed nodes and edges listed as a readable change list; changed config fields
  shown as before/after, text-valued fields through the same line diff). No Monaco diff editor
  in v1, no side-by-side canvas rendering.

## 7. Data model (sketch)

- `user_ai_settings`: `user_id` (unique), `provider`, `model`, `base_url`,
  `enabled` (bool, default false), `api_key_encrypted` (or vault ref), `storage_backend`,
  `share_inventory_data` (bool, default false), `share_content_data` (bool, default false), timestamps.
- No conversation tables in v1.

## 8. Permissions

One new permission, `ai_assistant:use`, added to `rbac_seed.DEFAULT_PERMISSIONS` (and therefore
undeletable, R4). **Suggested defaults:** grant it to the roles that already hold
`workflows:write` or `templates:write` — the people who author things — and not to
viewer/read-only roles. It is deliberately *not* implied by those permissions, so an admin
can switch the assistant off for a role without touching editing rights. The assistant adds no
authority: each tool additionally enforces the underlying permission (`workflows:read`,
`templates:read`, `workflows:write` for applying, ...), so it can never exceed what the user
could do by hand. P2 (grant only what you hold) applies as usual when granting it.

## 9. Phased plan

1. **Foundation** (gated on the SSE check in §10, decision 6): provider interface + Anthropic adapter, `user_ai_settings`, settings UI incl. data-sharing switches,
   test connection, rate limiting, SSE endpoint with a plain chat (no tools).
2. **Tool loop + template assistant:** agent loop, read tools, `render_template`,
   `propose_template`, diff/apply UI in the template editor. Smallest slice that proves the
   whole architecture.
3. **Gemini + openai_compat adapters:** same tools, contract tests across all providers.
4. **Workflow canvas assistant:** workflow read tools, step catalogue tools,
   `propose_workflow_patch` + validation feedback loop, canvas diff.
5. **Explain & query:** run tools, inventory/attribute questions, "explain failure" entry.
6. **Hardening:** content-data privacy switch, truncation behaviour, injection test corpus,
   docs.

Testing: provider adapters against recorded fixtures; the agent loop against a scripted
fake provider (deterministic tool-call sequences); tools as ordinary service tests; a small
set of live smoke tests (opt-in, like `tests/integration`) per provider.

## 9b. Phase 2 design — tool loop + template assistant

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

## 9c. Phase 4 design — workflow canvas assistant

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

## 9a. Implementation status

**Phase 1 (backend + frontend written, unit-tested; not yet exercised against a real provider key
or in a browser):**

- Backend: `core/models/user_ai_settings.py`, `repositories/user_ai_settings_repository.py`,
  `services/ai_assistant/` (settings, chat, providers, prompts), `routers/ai_assistant.py`
  (`GET /ai/status`, `GET|PATCH /ai/settings`, `POST /ai/settings/test`, `POST /ai/chat`),
  permission `ai_assistant:use`.
- Frontend: `components/features/ai-assistant/` (SSE parser, `useAssistantChat`,
  `AssistantPanel`, `useAiAssistantAvailable`), Settings → AI Assistant section.
- SSE through the Next.js dev proxy verified with a probe endpoint (incremental delivery, no
  gzip buffering). **Not yet verified for a production build / Docker ingress.**
- Key storage is Fernet only (`EncryptionService`); OpenBao storage is deferred.
- No data-sharing enforcement exists yet because no class B/C tool exists yet; the two switches
  are stored and shown, and `AiRuntimeConfig` carries them for the phase-2 tool layer.
- Not done: server-side `fallbacks` for refusals (a refusal is reported as a clear error),
  `openai_compat` loopback/SSRF policy (phase 3), the redaction module (phase 6, must precede any
  class B/C tool).

**Phase 2 (template assistant):**

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
  vitest/tsc/eslint. **Not verified:** a real tool-using turn against the Anthropic API, the UI in
  a browser, and proposal behaviour with Haiku 5.5 on real templates.
- Known limits: a pathological template can burn CPU in the render thread after the 5 s timeout
  returns (threads cannot be killed; same exposure as the editor's own preview); only the template
  *content* is proposable (not variables/options); the opt-in switches are still not consulted
  because no class B/C data is sent.

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
- Not verified: a real Gemini turn (incl. tool calls and thought signatures), a real Ollama turn,
  and the settings UI for the new providers in a browser.

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

## 10. Decisions and open questions

Decided (2026-10-10):

1. **Adapters vs. LiteLLM:** thin hand-written adapters.
2. **Storage:** dedicated `user_ai_settings` table.
3. **History:** stateless, client-held; losing history on reload is acceptable in v1.
4. **Data sharing:** opt-in only for anything device- or run-derived (§4). Config backups and
   command output may contain secrets.
5. **Permission:** `ai_assistant:use`, granted by default to roles holding `workflows:write` or
   `templates:write` (§8).
6. **SSE through the Next.js proxy:** must be verified without buffering *before* we commit to
   SSE; this is the first task of phase 1. Evidence so far is from reading
   `frontend/src/lib/api-proxy.ts`: non-JSON responses are returned as `new
   NextResponse(response.body, ...)`, i.e. the stream is passed through, not read into
   memory. **Not yet verified at runtime**; it must be tested with a real
   `text/event-stream` endpoint, including behind any reverse proxy / compression used in
   Docker. Fallback if it buffers: a dedicated streaming route handler, or polling.
7. **Providers equal:** no per-model handling. Gemini's free tier is for testing; its limits are
   unknown, so quota errors must degrade gracefully (§3.1).
8. **Applying a canvas proposal:** apply into the **open editor state, unsaved**. The user then
   reviews it on the canvas and uses the normal Save (with its validation, `WorkflowChange`
   audit and git versioning), and normal undo applies. This keeps exactly one persistence path
   and makes "Apply" low-stakes. Template proposals follow the same rule (applied into the
   editor buffer, saved by the user).

Decided (2026-10-10, second round):

9. **Redaction:** layered pipeline (§4.3) — reuse the existing structured redactor and URL scrub,
   add a conservative free-text regex layer for config text. The existing run-secret exact-match
   layer does not apply outside a run.
10. **Step error text:** treated as sensitive (class C) for now.
11. **Diff view:** simple, built on a diff library (jsdiff), rendered with our own Tailwind/Shadcn
   styling (§6).

Still open:

- Exact regex set and fixtures for §4.3 — to be written test-first during phase 6 (or earlier if
  class B/C tools ship earlier than planned; they must not ship without it).
- Whether to register the user's credential secrets for exact-match scrubbing later.
