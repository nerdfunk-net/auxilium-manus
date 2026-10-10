# AI Assistant — Branch Review (`feature/ai-integration`)

**Date:** 2026-10-10
**Scope:** `git diff main...feature/ai-integration` (merge base `73ad81e`): 102 files, +13,044 / −293.
Uncommitted doc edits in the working tree (`doc/ARCHITECTURAL_OVERVIEW.md`,
`doc/ai_integration/AI_ASSISTANT.md`, `doc/claude/development.md`) were not reviewed.
**Method:** I read every backend module under `services/ai_assistant/`, the router, models, repository
and DB readers, plus the frontend hook, panel, proposal cards and page integrations. I ran the
toolchain and reproduced the most important finding (H1) against the real code.

---

## 1. Verdict

| Question | Answer |
|---|---|
| Ready to merge to `main`? | **Not yet.** Fix **H1** and **H2** first, and preferably **M1** and **M2**. They are small, contained changes. Once they are fixed, the branch can be merged. |
| Production ready? | **No.** Apart from the fixes above, the feature's own design doc lists unverified items: a real model driving the workflow loop, the panels in a browser, a production build with SSE through the proxy, and the run and inventory surfaces against real data. The security-relevant DB adapters also have low test coverage (§5). |
| Standards (CLAUDE.md) | **Largely followed.** The layering, RBAC per tool, `extra="forbid"`, rate limits, the proxy-only pattern, TanStack Query, Shadcn and the 5xx rules are all respected. The deviations are listed in §4: function length, duplicated UI markup, one blocking call on the event loop, and a compat shim. |
| Security posture | The design is good: deny by default, opt-in data classes, allow-listed attributes, tools that only read or propose, RBAC as the calling user, neutral error messages and a write-only encrypted key. There are **two real holes** (H1, H2) and two medium issues. |

### Toolchain results (all green)

| Check | Result |
|---|---|
| `pytest tests/unit` (full suite) | **5177 passed** |
| AI tests only (`-k "ai_ or user_ai"`) | 396 passed |
| `ruff check` (touched backend files) | clean |
| `pyright services/ai_assistant routers/ai_assistant.py models/ai_assistant.py` | 0 errors |
| Guards `check_asyncio_run`, `check_http_500_leaks`, `check_router_repositories`, `check_text_sql` | all pass |
| `tsc --noEmit` | clean |
| `eslint` (changed frontend files) | clean |
| `vitest` (`features/ai-assistant`) | 11 passed (3 files) |
| Prettier | clean |
| Coverage of `services/ai_assistant` | 33–100 % per file; see §5 |

---

## 2. Security findings

### H1 — `render_template` returns redacted secrets in cleartext to the LLM (HIGH, reproduced)

`tools/template_tools.py:152` calls `ctx.redactor.restore(...)` on the content **the model supplies**,
renders it, and returns the rendered output to the model. Whatever the model writes, a
`__SECRET_n__` token is swapped back to the real secret. The choke-point redaction in
`Toolbox._finish` only matches config-shaped patterns (`enable secret …`, `password …`), so any
other context gets through unchanged.

Reproduction against the branch code (template editor with `enable secret 9 MyS3cretValue99`):

```text
prompt has secret: False
render_template(content="leak: {{ '__SECRET_1__' | list | join(' ') }} / __SECRET_1__")
→ Rendered output:
  leak: M y S 3 c r e t V a l u e 9 9 / MyS3cretValue99
```

**Impact:** this defeats the redaction guarantee in AI_ASSISTANT.md §4.3. A prompt injection can
trigger it, for example text in a template read through `get_template`. The model can also do it by
accident while "checking" a template. The secret then reaches the third-party provider and may stay
in its logs.

**Fix:** do not call `restore()` in `render_template`. Render the tokenised text, so tokens appear
as literals in the output; secrets are not needed to check syntax or logic. Keep `restore()` only in
`propose_template`, whose content goes to the client and never back to the model. Add a regression
test using the reproduction above.

### H2 — The OpenAI-compatible `base_url` gives any `ai_assistant:use` holder an SSRF primitive into the internal network (HIGH/MEDIUM)

`base_url_policy.py` reuses `validate_outbound_http_url`. That check deliberately **allows RFC1918**
for on-prem Nautobot/ISE, and it accepts query strings and fragments:

```text
http://10.0.0.5:6379/x?y=   -> accepted
http://10.0.0.5/admin#      -> accepted   (httpx drops the fragment → POST http://10.0.0.5/admin)
```

Together with `OpenAiCompatProvider` (`f"{base_url}/chat/completions"`), a non-admin user can make
the backend send a **JSON POST to any path on any internal host:port**. `POST /ai/settings/test`
works even while the assistant is disabled, and it returns distinguishable results (`ok`, "Could not
reach the provider", `HTTP 404 …`, `HTTP 401 …`). That makes it a port and service scanning oracle
(6 requests per minute). DNS rebinding is also possible: the URL is validated with one
`getaddrinfo`, and httpx then resolves the name again on its own.

The source settings for Nautobot, ISE and the others are admin-only (`sources.*:write` falls under P3
in `doc/claude/auth.md`). This setting is per user and needs only `ai_assistant:use`, so the same
outbound reach is now available to non-admins.

**Fix, in order of preference:**
1. Make the allowed LLM endpoints an admin-managed list (a system setting or a `sources.llm` source)
   and let users pick one, or require `admin` / a new protected permission to set a custom
   `base_url`.
2. At minimum, reject a `query`, `fragment`, `params` or userinfo in `base_url`.
3. Pin the resolved IP for the connection, or validate it again in an httpx transport hook.

### M1 — Redaction tokens can be relocated to other fields when a proposal is restored (MEDIUM)

`Redactor.restore_data()` (`redaction.py`) replaces a token wherever it appears in **any** string.
Through `_restored_plan` (`tools/workflow_tools.py`), a model (or an injection) can put
`__SECRET_3__` (say, a step's password) into a non-secret field of a **new** node, such as a Mattermost
message, a command or an HTTP body. The change list shows only `id/kind/title` for added nodes
(`workflow_expand._summarize`), so the user cannot see the moved value before clicking Apply. After
saving and running, the secret sits in cleartext in a non-secret config field, in run output and in
git mirrors, and it can be sent to an external system.

**Fix:** record the origin path of each token in `tokenize_data`, and in `restore_data` restore a
token only at that same key path (reject the plan otherwise). Show the config of added nodes in the
proposal card as well.

### M2 — Provider HTTP clients are never closed (MEDIUM, resource leak)

`AnthropicProvider` (`anthropic.AsyncAnthropic`), `GeminiProvider` and `OpenAiCompatProvider`
(`new_client()`) each create a new connection pool **per chat request and per connection test**, and
nothing ever calls `aclose()`. Under sustained use this leaks sockets and file descriptors and
produces "unclosed client" warnings.

**Fix:** either share one long-lived `httpx.AsyncClient` (or `AsyncAnthropic`) per process, opened
and closed in the app lifespan (see the memory note on lifespan registration), or make the providers
async context managers and use `async with` in `chat_service`.

### M3 — The trial Jinja render can tie up worker threads (MEDIUM, known)

`_render_with_timeout` uses `asyncio.wait_for(asyncio.to_thread(...), 5s)`. The timeout returns
control, but the thread keeps running. `SandboxedEnvironment` limits `range()` but not nested loops or
string multiplication (`{{ 'a' * 10**9 }}`). With 8 tool steps × 30 chats/min, and with
prompt-injection reachability, the model can fill the default thread pool. The DB readers share that
pool through `asyncio.to_thread`. AI_ASSISTANT.md §12 documents this ("same exposure as the editor's
own preview"), but the AI path can be reached by the model, not only by the user.

**Fix:** run the trial render in a subprocess with CPU and memory limits, or with a dedicated small
`ThreadPoolExecutor` so it cannot starve the shared pool. Also add sandbox binop interception
(`intercepted_binops` for `*` and `**`) to cap sizes.

### L1 — `POST /ai/settings/test` blocks the event loop (LOW)
`routers/ai_assistant.py:162` is `async def`, but it calls the synchronous
`service.require_runtime_config()` (a SQLAlchemy query plus Fernet decryption) directly. Make it a
`def` endpoint that resolves the config, then await the probe, or wrap the config resolution in
`asyncio.to_thread`. `chat` is a sync `def` and is fine.

### L2 — Prompt-injection guidance is missing on two surfaces (LOW)
`prompts.py` tells the run (line 76) and inventory (line 95) surfaces that tool results are data. The
template and workflow prompts only cover `<editor_state>`/`<canvas_state>`, yet `get_template` returns
other people's template content. Add the same sentence to both prompts. This matters most together
with H1 and M1.

### L3 — The audit loses token usage on failed turns (LOW)
`run_agent` emits `usage` only on the success path. Turns that fail with "too many tool steps",
`max_tokens` or a provider error are logged with 0 tokens, although they are the most expensive ones.
Emit `usage` from a `finally`, or count it in `TurnAudit` per provider turn.

### L4 — Aborting the chat may not cancel the backend loop (LOW, unverified)
`lib/api-proxy.ts` calls `fetch(targetUrl, …)` without `signal: request.signal`. Whether a browser
"Stop" cancels the upstream stream depends on Next/undici cancelling the piped body. Verify this.
If it does not cancel, the agent loop keeps spending the user's quota for up to 9 provider calls.

### Known by design (documented, not counted as new findings)
- Class C text (errors, artifacts) can reveal device names and IPs once content sharing is on (§14).
- `get_run_workflow` and the workflow canvas are class A and are not gated by the sharing switches (§14).
- The client holds the history: users can forge `assistant` turns. This only affects their own
  session, because every tool enforces RBAC.

### Positive security observations
- Every DB reader re-checks RBAC **as the calling user** in a fresh session (`run_reader.py`,
  `inventory_reader.py`, `template_reader.py`, `workflow_reader.py`) and delegates to the same
  services as REST, so private-workflow and inventory visibility match.
- Data sharing is **allow-listed** for Nautobot attributes (unknown → `"never"`), the default shares
  nothing, and the gate is enforced in the tool layer rather than the UI.
- The API key is Fernet-encrypted per provider, write-only, excluded from `repr`, and the response
  only reports `api_key_set`.
- Provider errors are mapped to neutral messages; bodies are inspected but never echoed.
  `follow_redirects=False`. The model output is rendered as plain text, with no markdown or HTML,
  so there is no XSS path.
- Outbound URLs are re-validated before every call. The API key is refused over plain http outside
  development.
- Proposals never persist anything. Applying goes into the unsaved buffer or canvas with a stale-state
  check (`baseContent` / `baseFingerprint`).

---

## 3. Dead code, duplication and simplification

| # | Location | Finding | Suggestion |
|---|---|---|---|
| D1 | `settings_service.py` `_key_map` | Fallback that reads a "pre-existing single raw token". The table is new on this branch, so only dev rows could have that format; per project policy there is no backward compatibility. | Drop the branch and treat non-JSON as "no key". |
| D2 | `settings_service.py:250` | `register_secret_value(cleartext)` is a **no-op** here. It only records inside `run_secret_scope()`, and the chat path never opens one. The module docstring claims the key "is registered for run-scoped redaction". | Remove the call and correct the docstring, or open a scope around the chat stream if that was the intent. |
| D3 | `tools/{template,workflow,inventory}_tools.py` | Three identical `NoInput` models, two near-identical `_reference_text()` loaders, and `_cap` (inventory) duplicates `_cap_strings` (run). | Move them to `tools/base.py` (or `tools/common.py`). |
| D4 | `settings_service.AiRuntimeConfig` | Five `share_*` booleans duplicate `SharingPolicy` field by field. | Store a `sharing: SharingPolicy` field directly. |
| D5 | `base_url_policy.MAX_BASE_URL_CHARS` | Repeats the Pydantic `max_length=512`. | Keep one source of truth. |
| D6 | `http_common.unavailable(_exc)` | The parameter is unused. | Make it a constant/factory without the argument. |
| D7 | `frontend/.../use-assistant-chat.ts:264` | The comment "Null the ref synchronously…" sits above `setProposalState`; it belongs to `stop`/`clear`. | Move the comment. |
| D8 | 4 pages (`template-editor-page`, `workflow-builder-page`, `workflow-runs-page`, `inventory-page`) | The same `<aside>` markup (Sparkles header, close button, panel container) is copied into each page. | Extract an `AssistantSidebar` component into `features/ai-assistant/components/`. |
| D9 | `template-editor-page.tsx`, `workflow-builder-page.tsx` | Mostly **Prettier reformatting churn**: the template editor shows +295/−197, but only +104/−6 with whitespace ignored. This is why `/ultrareview` rejected the diff (13k lines > 8k limit). | In the future, reformat in a separate commit, or keep formatting out of feature diffs. |

There are no unused modules. `providers/registry.py` (44 %) and the DB readers are used but untested
(§5).

---

## 4. File and function size, and CLAUDE.md conformance

### File size (limit 800, typical 200–400)
All files are under 800 lines. The largest are `workflow_expand.py` (504),
`workflow-builder-page.tsx` (542), `ai-assistant-settings-canvas.tsx` (502), `run_tools.py` (390)
and `settings_service.py` (370). **Acceptable.** The settings canvas could split into a provider
section and a sharing section.

### Function length (rule < 50 lines): violations

| Function | Lines |
|---|---|
| `workflow_expand.expand_plan` | **151** |
| `agent_loop.run_agent` | 78 |
| `openai_compat_provider.OpenAiCompatProvider.stream` | 88 |
| `gemini_provider.GeminiProvider.stream` | 82 |
| `workflow_expand._summarize` | 64 |
| `use-assistant-chat.ts` `send` callback | ~170 |

`expand_plan` and `send` are worth splitting. For `send`, extract `handleSseEvent(event, data)` and a
`toProposalState(payload, context)` helper.

### Standards checklist

| Standard | Status |
|---|---|
| Layering Model → Pydantic → Repository → Service → Router, registered in `main.py` | ✅ |
| `BaseRepository`/whitelisted updates (`apply_updates` + `frozenset`) | ✅ (`user_ai_settings_repository.py`) |
| Model exported from `core/models/__init__.py`, timestamps, FK, index, unique | ✅ |
| `doc/claude/database.md` table list and count updated | ✅ |
| No `text()` / f-string SQL | ✅ |
| Request models `extra="forbid"` | ✅ |
| `rate_limited(...)` on endpoints that call external APIs | ✅ chat + test (PATCH settings does a DNS lookup without a limit; minor) |
| 5xx without raw exception text | ✅ (stream errors are neutral, and the guard passes) |
| `require_permission` on routes; new permission seeded | ✅ `ai_assistant:use` |
| No f-strings in logging | ✅ |
| Event-loop hygiene | ⚠️ L1 |
| Frontend: proxy only, TanStack Query + `queryKeys`, Shadcn, no raw colours, stubs-only route files | ✅ (chat uses `fetch` for SSE through the proxy, which is justified) |
| Frontend: memoised hook returns, stable callbacks | ✅ |
| Immutability | ✅ mostly. `RunViewerState.loaded` is a mutable cache inside a frozen dataclass. It is request-scoped, so this is acceptable, but note it. |
| Function size < 50 | ❌ see above |
| Tests: 80 % coverage, unit + integration + E2E | ⚠️ see §5 |

---

## 5. Tests and coverage

The backend unit tests are extensive (396 AI tests; provider adapters are tested against real SDK
types; there is a redaction corpus and hardening tests). The gaps are in the **security-critical
adapters**:

| Module | Coverage | Why it matters |
|---|---|---|
| `run_reader.py` | **33 %** | Enforces `workflow_runs:read` and private-workflow visibility |
| `inventory_reader.py` | **43 %** | Enforces `sources.nautobot:read` and private inventories |
| `workflow_reader.py` | **46 %** | RBAC per reference kind (credentials, git, sources) |
| `template_reader.py` | **55 %** | `templates:read` |
| `providers/registry.py` | 44 % | Provider dispatch |

**Recommendation:** add tests for each reader that cover a user **without** the permission, another
user's private run or inventory, and an unknown id. In-memory SQLite is fine for this.

**Frontend:** only the three pure utils have tests. `useAssistantChat` (SSE parsing into state,
proposal handling, abort and `done` handling), both proposal cards (the stale-check that blocks
Apply) and the settings form (key write-only, `clear_api_key`) have none. There is no E2E test of
any assistant surface.

**Missing regression tests for the findings:** H1 (render leak), H2 (base_url with query or
fragment), M1 (token relocation).

---

## 6. Recommended order of work

1. **H1**: stop restoring tokens in `render_template`, and add a regression test. *(small)*
2. **H2**: reject query, fragment and userinfo in `base_url`, then decide between an admin-managed
   endpoint list and a protected permission. *(small to medium)*
3. **M1**: restore tokens only at their origin path, and show the config of added nodes in the
   proposal card. *(medium)*
4. **M2**: share or close the provider clients through the lifespan. *(small)*
5. Reader RBAC tests (§5), L1 and L2. *(small)*
6. Merge to `main`.
7. Before production: M3 (render isolation), L3, L4, the frontend hook and card tests, the
   "Not verified" items in AI_ASSISTANT.md §12/§14/§15/§17 (real-model runs, browser, production
   build with SSE through the proxy), and the D-series cleanups and function splits.

---

## 7. Resolution status (2026-10-10)

| Finding | Status | What was done |
|---|---|---|
| H1 render leak | **Fixed** | `render_template` no longer restores tokens; with no `content` it renders the *redacted* editor content. Regression test `test_render_never_reveals_a_redacted_secret_to_the_model`. |
| H2 base_url SSRF | **Fixed (partly)** | Query, fragment and path params are rejected (`base_url_policy._check_shape`). Setting a base URL is **admin-only** (router 403 `ai_base_url_admin_only`); the settings form disables the field for non-admins. **Not done:** pinning the resolved IP against DNS rebinding. |
| M1 token relocation | **Fixed** | `Redactor` records the dict key each token came from; `restore_data` raises `SecretRelocationError` for any other key, and the workflow tools return it to the model as a plan error. Added steps now show their (secret-masked) config in the proposal card, and changed-step diffs are masked too. Residual: the check is by key name, so a secret can still be placed under the same key name in another step. |
| M2 unclosed clients | **Fixed** | Providers have `aclose()`; `chat_service` closes the provider after every turn and connection test. |
| M3 render threads | **Fixed** | The trial render runs in a child process (`render_isolated.py` + `render_worker.py`, started with `python -I`) that is killed at the 5 s timeout and has CPU (5 s) and address-space (1 GiB, Linux) limits. At most 4 renders run at once (otherwise a "busy" error). The sandbox also caps `*` and `**` results (`_BoundedSandbox`), so `{{ 'a' * 10**9 }}` is refused. Tests: `test_ai_render_isolation.py`. The editor preview and Hatchet template steps are unchanged (see OPEN_TODOS). |
| L1 blocking test endpoint | **Fixed** | Config lookup runs in `asyncio.to_thread`. |
| L2 prompt guidance | **Fixed** | Template and workflow prompts now state that tool results are data; test covers all four surfaces. |
| L3 usage on failed turns, L4 abort propagation | Open | |
| D1, D2, D6, D7 | **Done** | Legacy key-blob fallback and its test removed; no-op `register_secret_value` removed; `unavailable()` lost its unused argument; misplaced comment moved. |
| D3, D4, D5, D8, D9 and function splits | Open | |
| §5 reader tests | **Done** | `tests/unit/test_ai_db_readers.py` (15 tests). Reader coverage is now 80–100 % (was 33–55 %); `registry.py` 100 %. The frontend hook and card tests are still missing. |

Verification after the changes: 5196 backend tests pass, ruff, pyright and the four guards are clean,
and `tsc`, eslint, Prettier and vitest are clean.
