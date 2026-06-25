# Frontend Analysis — Best-Practice Compliance, Security & Refactoring Candidates

> Generated: 2026-06-25
> Scope: `frontend/src` (150 `.ts`/`.tsx` files, ~17.9k LOC)
> Reference: `CLAUDE.md` (project standards) + `~/.claude/rules/` (global standards)

## Executive Summary

The frontend is **architecturally healthy at its core**. The proxy/auth layer is the
strongest part of the codebase: the Next.js proxy (`lib/api-proxy.ts`) correctly strips
`authorization`/`cookie` request headers and `set-cookie` response headers, removes
hop-by-hop headers, stores the JWT in an `httpOnly`, `sameSite=lax`, `secure`-in-prod
cookie, and never leaks raw backend errors to the browser. The proxy-only rule is
respected (no direct backend calls), `any` is entirely absent (0 occurrences), no
`dangerouslySetInnerHTML`/`eval`/`localStorage`-token storage exists, the `queryKeys`
factory is well-structured and used almost everywhere, route files are pure stubs, and
Zustand stores are consumed via selectors.

The issues are concentrated in three areas:

1. **Testing — total absence.** Zero test files, no Vitest/Jest/Playwright config. This
   is the single largest gap versus the mandated 80% coverage across unit / integration /
   E2E.
2. **A few TanStack-Query / data-fetching escapes.** Two raw `fetch()` calls live inside
   components (bypassing `useApi`'s 401 handling and the query cache), and three inline
   `useQuery`/`useMutation` definitions sit in components instead of dedicated hooks.
3. **Polish gaps.** 8 leftover `console.debug` statements, 135 arbitrary Tailwind color
   classes (vs. the "semantic tokens only" rule), several oversized files (>500 lines,
   one >800), one real state bug (`workflowUuid` dropped on load), and an
   **enforcement claim in CLAUDE.md that is not backed by config** (no custom ESLint
   rules, no pre-commit/husky).

Nothing here is a critical security hole. The work is mostly hardening, consistency, and
establishing a test baseline.

---

## 1. Testing — CRITICAL GAP

| Check | Result |
|-------|--------|
| `*.test.*` / `*.spec.*` files | **0** |
| Vitest / Jest config | **none** |
| Playwright config | **none** |
| `package.json` scripts | only `lint` (no `test`, `test:e2e`) |

CLAUDE.md / `rules/common/testing.md` mandate **80% coverage** with unit, integration, and
E2E (Playwright) tests. The frontend currently has **no test infrastructure at all**. This
is the top priority — every other refactor below is safer once a baseline exists.

**Recommendation:**
- Add Vitest + React Testing Library for unit/component tests; Playwright for the critical
  flow (login → design workflow → run → inspect execution).
- Start with pure utilities that are trivial to cover and high-value:
  `utils/workflow-validation.ts`, `utils/step-result-status.ts`, `utils/workflow-folders.ts`,
  `utils/node-alignment.ts`, `condition-builder/tree-to-operation.ts`,
  `lib/api-proxy.ts` (header stripping is security-critical — test it explicitly).
- Add `test` and `test:e2e` scripts and wire them into CI.

---

## 2. Data-Fetching Escapes (TanStack Query / useApi)

### 2a. Raw `fetch()` inside components — MEDIUM

Two components call `fetch()` directly instead of going through `useApi` or a query hook:

| File | Line | Call |
|------|------|------|
| `features/workflows/workflow-builder-page.tsx` | 296 | `fetch('/api/proxy/workflows/${summary.id}')` to load a workflow |
| `features/workflows/dialogs/workflow-save-as-dialog.tsx` | 104 | `fetch('/api/proxy/workflows/check-name?...')` to check name availability |

**Why it matters:**
- Both bypass `useApi`'s centralized **401 → redirect-to-login** and 403 handling, so an
  expired session on these paths fails silently / inconsistently.
- The workflow-load path bypasses the query cache entirely (no caching, no dedupe, manual
  `.then/.catch` error handling), contradicting "MANDATORY for all data fetching: use
  TanStack Query."
- There is no `useWorkflowQuery(id)` detail hook even though `queryKeys.workflows.detail(id)`
  already exists — the factory key is defined but unused.

**Recommendation:** Add `use-workflow-query.ts` (detail) and a `useCheckWorkflowName`
mutation/query; replace both raw `fetch` calls. At minimum, route them through `apiCall`
so 401 handling is consistent.

### 2b. Inline `useQuery`/`useMutation` in components — LOW

Three components define queries inline rather than in `hooks/queries/*`:

| File | Line | What |
|------|------|------|
| `workflows/components/workflow-executions-panel.tsx` | 258 | `useQuery` for run detail (`runs/${runId}`) |
| `workflow-steps/get-nautobot-devices/preview-dialog.tsx` | 60 | `useQuery` for device preview |
| `workflows/dialogs/workflow-manage-dialog.tsx` | — | uses `useQueryClient` directly |

These **do** use the `queryKeys` factory (good), so the cache stays coherent — but they
violate "Create dedicated hooks for each resource." Extract to
`use-workflow-run-detail-query.ts` etc. for reuse and testability.

### 2c. One inline query key — LOW

`hooks/queries/use-workflow-runs-query.ts:39` uses a literal `["workflow-runs", "disabled"]`
for the disabled branch instead of the factory. Cosmetic, but add a
`queryKeys.workflowRuns.disabled()` (or reuse `.all`) for consistency.

---

## 3. Code Quality / Polish

### 3a. Leftover `console.debug` — LOW (but should be removed before prod)

8 `console.debug` statements remain, all `[DEBUG]`-prefixed development scaffolding:

- `workflow-steps/get-git-devices/index.tsx` (lines 74, 80, 84)
- `hooks/queries/use-get-git-devices-preview-mutation.ts` (lines 34, 40, 44, 47, 50)

`rules/typescript/coding-style.md` forbids `console.*` in production code. Remove these or
replace with a proper logger. (No `console.log` elsewhere — isolated to the git-devices
preview feature.)

### 3b. Arbitrary Tailwind colors — MEDIUM (consistency / theming)

135 hard-coded color utilities across `.tsx` files (e.g. `text-emerald-600`, `bg-slate-50`,
`text-amber-600 ×16`, `bg-green-500`, `text-red-500`, `bg-red-950`). CLAUDE.md UI/UX
standards say: use semantic tokens (`bg-background`, `text-foreground`, `text-destructive`,
`text-muted-foreground`), **not** `bg-blue-500`-style classes.

**Impact:** breaks dark-mode/theming consistency and the design-token system. Status
colors (run success/failure, step states) are the main offenders.

**Recommendation:** Introduce a small set of semantic status tokens (e.g. CSS variables
`--status-success/-warning/-error` or a typed `statusColor` map in one place) and replace
the scattered literals. This is a worthwhile cleanup but lower-risk than items 1–2.

### 3c. `workflowUuid` dropped on load — LOW BUG

`hooks/use-workflow-builder-store.ts` — `loadWorkflow(meta)` (line 95) sets `workflowId`,
`workflowName`, `workflowDescription`, `workflowFolder`, `workflowVisibility` but **omits
`workflowUuid`**, even though the caller
(`workflow-builder-page.tsx:308`) passes `workflowUuid: full.uuid ?? null`. Result: the
store keeps the previously-loaded workflow's UUID after loading a different workflow.

**Fix:** add `workflowUuid: meta.workflowUuid,` to the `loadWorkflow` `set(...)` call.

---

## 4. File-Size / Refactoring Candidates

Per `rules/common/coding-style.md` (200–400 typical, 800 max):

| File | Lines | Note |
|------|------:|------|
| `workflows/components/step-result-viewer.tsx` | **806** | **Over the 800 hard limit.** Mixes debug-log parsing, command-result rendering, artifact tabs, device collapsing. Extract per-result-type renderers + parsing helpers. |
| `get-nautobot-devices/condition-builder/condition-builder.tsx` | 743 | Complex recursive UI — split node/leaf renderers and the operations sidebar. |
| `render-jinja-template/template-editor-dialog.tsx` | 664 | Editor + preview + context panels in one file. |
| `workflows/workflow-builder-page.tsx` | 597 | Orchestrator with many `useCallback`s + a raw fetch (see 2a). Extract load/save/run handlers into hooks. |
| `workflow-steps/store-artifact/index.tsx` | 559 | Config panel — extract sub-sections. |
| `workflows/components/workflow-properties-panel.tsx` | 485 | Watch zone. |

Splitting `step-result-viewer.tsx` is the only **mandatory** one (exceeds 800); the rest
are "many small files > few large files" improvements, best done alongside adding tests.

---

## 5. Enforcement Claim vs. Reality — MEDIUM

CLAUDE.md (React Best Practices section) states:

> **Enforcement:** ESLint rules + pre-commit hooks block non-compliant code

This is **not currently true**:
- `eslint.config.mjs` is the stock `eslint-config-next` (core-web-vitals + typescript)
  with no custom rules. `react-hooks/exhaustive-deps` ships with Next's config but as a
  **warning**, not an error, so the "MUST follow" hook rules are not blocking.
- There is **no** `.husky/`, no `lint-staged`, no pre-commit hook.

**Recommendation:** Either (a) make the doc accurate, or (b) make it real — add husky +
lint-staged running `eslint --max-warnings 0` and `tsc --noEmit` on staged files, and
promote `react-hooks/exhaustive-deps` to `error`. Given the React-loop guidance in
CLAUDE.md is framed as critical, option (b) is preferable.

---

## 6. Security Assessment — GOOD

No critical or high-severity frontend security issues found. Positives:

| Control | Status |
|---------|--------|
| JWT in `httpOnly` + `sameSite=lax` + `secure` (prod) cookie | ✅ `api/auth/login/route.ts:73` |
| Proxy strips inbound `authorization`/`cookie` | ✅ `api-proxy.ts:19` |
| Proxy strips outbound `set-cookie`; hop-by-hop filtered | ✅ `api-proxy.ts:20,134` |
| No raw backend error text surfaced (503/502 generic messages) | ✅ `api-proxy.ts:52`, auth routes |
| Boundary validation of token/user payloads | ✅ `parseTokenResponse`/`parseUserResponse` |
| `target="_blank"` carries `rel="noopener noreferrer"` | ✅ `hatchet-settings-canvas.tsx:170` |
| `dangerouslySetInnerHTML` / `eval` / `new Function` | ✅ none |
| Token in `localStorage`/`sessionStorage` | ✅ none (cookie only) |
| `any` usage | ✅ 0 occurrences |
| `alert()`/`confirm()` | ✅ none (Dialog used) |

**Minor hardening notes (LOW):**
- `workflow-builder-page.tsx` raw-fetch error handling swallows the body; ensure no
  sensitive detail is ever rendered (it currently shows a generic toast — fine).
- The login route maps backend `429` to "Invalid username or password" (status preserved),
  which is reasonable; confirm rate-limit UX is intentional.
- Type-coercion casts like `nodes as unknown as Record<string, unknown>[]`
  (`workflow-builder-page.tsx:278`) are a type-safety smell, not a security issue — worth a
  proper serialization type when touching that area.

---

## Priority Summary

| # | Item | Severity | Effort |
|---|------|----------|--------|
| 1 | No tests / no test infra (80% mandate) | **CRITICAL** | High |
| 2a | Raw `fetch()` in 2 components (bypasses 401 + cache) | MEDIUM | Low |
| 5 | ESLint/pre-commit enforcement claim is false | MEDIUM | Low–Med |
| 3b | 135 arbitrary Tailwind colors vs. semantic tokens | MEDIUM | Med |
| 4 | `step-result-viewer.tsx` exceeds 800-line limit | MEDIUM | Med |
| 2b | 3 inline `useQuery`/`useMutation` → extract to hooks | LOW | Low |
| 3a | 8 leftover `console.debug` statements | LOW | Trivial |
| 3c | `workflowUuid` dropped in `loadWorkflow` | LOW (bug) | Trivial |
| 2c | 1 inline query key (`workflow-runs/disabled`) | LOW | Trivial |
| 4 | Other 500–700-line files | LOW | Med |

**Suggested order:** Establish test infra (#1) → fix the two quick correctness items
(#2a, #3c) → make enforcement real (#5) → then tackle consistency/refactor passes
(#3b, #4) with the new tests as a safety net.
</content>
