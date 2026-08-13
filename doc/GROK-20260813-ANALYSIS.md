# Frontend analysis — 13 August 2026

> **Addendum (13 Aug 2026, post `get-pyats-snapshot` / `compare-pyats-snapshot`):** all findings re-verified against the current tree and still valid. Deltas from the new steps: `step-result-viewer.tsx` grew 1,181 → **1,299** lines (new `Snapshot*` guards + `DeviceSnapshotContent`); `store-artifact/index.tsx` is now 753 and `compare-data/index.tsx` 690; new `compare-pyats-snapshot/index.tsx` (455 lines) adds one more `workflowNodes = []` default-prop violation (§4.5). The new steps introduce no new secret handling, raw `fetch`, or registry violations. `doc/refactoring/GROK-20260813-REFACTORING.md` R8/R12 have been updated accordingly.

Review of `frontend/src` against `CLAUDE.md`, file-size / maintainability, and production-readiness security. The app is not in production yet; findings are ordered so a first release can be planned against them.

**Scope:** frontend TypeScript/TSX only (411 files, ~56k lines), plus the Next.js API routes that the browser actually talks to (`/api/proxy/*`, `/api/auth/*`). Backend security already recorded in `doc/SECURITY-NOTES.md` is not re-litigated here, except where the frontend design forces secrets into the browser.

**Method:** route-stub audit, query/mutation inventory, proxy and cookie inspection, grep for disallowed patterns (`dangerouslySetInnerHTML`, `alert`/`confirm`, direct `:8000` calls, inline GraphQL, `localStorage` tokens), line-count ranking, and targeted reads of the largest and auth-critical files.

---

## 1. Executive summary

The frontend **largely follows** the architecture in `CLAUDE.md`: feature folders, route stubs, Shadcn primitives, TanStack Query + a query-key factory, Zustand for editor/auth client state, HTTP-only cookies, and same-origin proxy to FastAPI. TypeScript `strict` is on. There is no `dangerouslySetInnerHTML`, no `alert()`/`confirm()`, and no JWT in `localStorage`.

It is **not yet production-ready**. Three issues should be treated as release blockers:

1. **Nautobot (and related) API tokens are fetched into the browser and then sent back as GET query parameters.** Reverse-proxy and Next.js access logs will record those secrets.
2. **The OIDC callback skips CSRF `state` validation when `sessionStorage` is empty.**
3. **Developer tools (OIDC token debugger, live schema migration, system CA install) are reachable in the same authenticated app** as the product UI. Even with backend RBAC, they should not ship enabled in a first production build without an explicit decision.

Two files are also too large to keep evolving safely: `workflow-builder-page.tsx` (1,421 lines, one component) and `step-result-viewer.tsx` (1,181 lines, many unexported panels). Split those before adding more canvas or run-detail behaviour.

Overall CLAUDE.md grade: **solid skeleton, uneven enforcement**. Auth, proxy, and feature layout are in good shape. Data-fetching discipline, secret handling, and UI-token conventions slip in the inventory / sources / workflow-builder paths.

---

## 2. What is already in good shape

| Area | Evidence |
|---|---|
| Route stubs | All 16 `app/**/page.tsx` files are stubs or redirects. None use `'use client'`. Settings `[section]` only parses the param and calls `notFound()`. |
| Feature layout | Domain UI lives under `components/features/{auth,inventory,settings,templates,tools,workflow-steps,workflows}`. No stray components at `components/` root. |
| API proxy | Browser calls go to `/api/proxy/*` or `/api/auth/*`. `BACKEND_URL` is server-only. Incoming `Authorization`/`Cookie` are stripped; the HttpOnly cookie is re-attached as `Bearer`. |
| Auth cookie | `httpOnly`, `sameSite: "lax"`, `secure` in production, `path: "/"`. Access token never returned to the login JSON body (`{ user }` only). |
| Dashboard gate | `(dashboard)/layout.tsx` checks the cookie and calls `/api/auth/me` before rendering. Unauthenticated users redirect to `/login`. |
| Credentials store | Device SSH/TACACS passwords are **not** listed in the credentials API response (`has_password` flags only). Forms use Shadcn + Zod. |
| Query key factory | `lib/query-keys.ts` covers the domains in use. Almost every `useQuery` uses it. |
| No XSS sinks | No `dangerouslySetInnerHTML` / `eval` / `document.write`. Step output is rendered as React text / `<pre>`. |
| No inline GraphQL | No component-level GraphQL; Nautobot is reached via backend endpoints. |
| Canvas nodes | Shared `workflow-node.tsx` (`w-80` × `h-32`), registry-driven titles, plugin UI is ConfigPanel-only. |
| TypeScript | `"strict": true`. Essentially no `any` in application code. |
| Default-array constants | The worst offenders (builder page, device selector, node config modal) already use module-level `EMPTY_*` constants. |
| Session idle logout | `useSessionManager` renews the cookie while active and idle-logs out using general settings. |
| `hasPermission` comment | `lib/permissions.ts` correctly documents itself as UX gating only; backend `require_permission` is the real boundary. |

---

## 3. File size

Threshold used: **300+ lines = large**, **500+ = should split**, **800+ = blocking for further feature work in that file**.

### 3.1 Ranked large files

| Lines | File | Why it is large | Split recommendation |
|------:|---|---|---|
| 1,421 | `features/workflows/workflow-builder-page.tsx` | **Single function** owns canvas state, React Flow handlers, save/load/run, group navigation, dirty tracking, and six dialogs. Also uses raw `fetch` instead of `useWorkflowQuery`. | Extract `use-workflow-canvas.ts` (nodes/edges/groups/handlers), `use-workflow-persistence.ts` (save/load/new), `use-workflow-run-actions.ts`, and a thin page that only composes topbar + canvas + dialogs. |
| 1,181 | `features/workflows/components/step-result-viewer.tsx` | ~20 local components (device cards, genie/config/comparison panels, debug logs). | Move each `*Panel` / `*Content` into `step-result-viewer/` (e.g. `device-card.tsx`, `debug-logs-panel.tsx`, `metadata-panel.tsx`). Keep a ~150-line orchestrator. |
| 735 | `workflow-steps/store-artifact/index.tsx` | Config panel + option tables + upstream resolution UI. | Extract option lists / field blocks; keep `index.tsx` as the `PluginUIComponent`. |
| 685 | `templates/template-editor-page.tsx` | Page orchestrates editor, variables, netmiko, render, export. | Already has child components; remaining page logic should move into `use-template-editor.ts`. |
| 681 | `workflow-steps/add-to-nautobot/add-to-nautobot-dialog.tsx` | Large config dialog. | Split interface list vs. device fields. |
| 672 | `workflow-steps/compare-data/index.tsx` | Config panel + comparison source pickers. | Same pattern as store-artifact. |
| 614 | `workflows/dialogs/workflow-import-dialog.tsx` | Import + credential remap + name-check `fetch`. | Extract remap table and name-check into a hook. |
| 603 | `inventory/dialogs/manage-inventory-modal.tsx` | Tree + list + CRUD in one modal. | Extract tree pane and item row. |
| 561 | `workflow-steps/update-nautobot-device/update-device-dialog.tsx` | | Same as add-to-nautobot. |
| 558 | `workflows/components/workflow-properties-panel.tsx` | | Extract schedule / static-attributes if they are not already. |
| 541 | `inventory/components/condition-tree-builder.tsx` | | Extract toolbar vs. tree. |
| 536 | `settings/components/sources-settings-canvas.tsx` | Four source types on one canvas. | One card/list component per source type. |
| 526 | `workflows/components/node-config-modal.tsx` | | Already the right place; watch growth. |
| 525 | `workflows/dialogs/workflow-manage-dialog.tsx` | | Extract list vs. edit form. |

**Counts:** 36 files > 300 lines, 14 > 500, **2 > 1,000**.

Help panels (`*-help-panel.tsx`, 230–330 lines) are documentation, not logic. Leave them unless a step’s `index.tsx` is also huge.

### 3.2 Why the two 1k+ files matter for a first release

`WorkflowBuilderPage` is the product. Every new step, group behaviour, or run-control change will keep landing in the same 1,400-line function. That is how save/load `fetch` bypasses and draft-rehydration bugs accumulate.

`StepResultViewer` is the operator’s window onto device output, secrets-adjacent context, and artifacts. Keeping twenty view components in one file makes it easy to accidentally render a secret field or skip a redaction path.

---

## 4. CLAUDE.md compliance

### 4.1 Frontend structure — **pass, with drift**

```
components/features/{domain}/components|dialogs|hooks|tabs|types|utils
app/(dashboard)/{feature}/page.tsx   # stubs only
```

Followed. Drift:

- Query hooks are split between `frontend/src/hooks/queries/` (shared) and `components/features/{domain}/hooks/` (templates, credentials, RBAC). That split is reasonable, but **inventory Nautobot preview/field-value hooks live in the global `hooks/queries` folder** while inventory-only UI lives under `features/inventory`. Not wrong, just inconsistent.
- `CLAUDE.md` points at `frontend/src/hooks/queries/BEST_PRACTICES.md` and `OPTIMISTIC_UPDATES.md`. **Those files do not exist.**

### 4.2 Route file rule — **pass**

No logic, state, or `'use client'` in route files. Optional `generateStaticParams` on settings is allowed.

### 4.3 Proxy-only API — **pass for origin, fail for discipline**

No `localhost:8000` from the browser. Several call sites skip `useApi()` / TanStack Query and `fetch('/api/proxy/...')` directly:

| File | What it fetches | Should be |
|---|---|---|
| `workflow-builder-page.tsx` (~223, ~756) | `GET /workflows/:id` on mount and on Open | `useWorkflowQuery` already exists and is unused by the builder |
| `workflow-save-as-dialog.tsx` | `GET /workflows/check-name` | mutation/query hook |
| `workflow-import-dialog.tsx` | same check-name | same hook |
| `login-page.tsx` | `GET /auth/oidc/providers` | query hook (public) |

Auth routes (`/api/auth/login`, `/me`, `/logout`, `/refresh`) correctly stay outside the generic proxy so Set-Cookie can happen. That is not a violation.

`useApi()` already handles 401 → `/login`, 403, and FastAPI `{detail}` / `{detail: {message}}`. Raw `fetch` duplicates none of that (builder mount catch is a generic “Failed to restore workflow canvas”).

### 4.4 TanStack Query — **mostly pass**

Dedicated hooks exist for workflows, runs, settings, sources, credentials, templates, RBAC, certificates, schema, OIDC debug. `staleTime` defaults to 30s in `query-client.ts`; run lists poll while `pending`/`running`/`paused`. Invalidation after mutations is generally present.

Gaps:

- Builder load path does not use `useWorkflowQuery`.
- `get-nautobot-devices/preview-dialog.tsx` inlines `useQuery` instead of a hook under `hooks/queries/`.
- `use-workflow-run-mutations.ts` invalidates with `[...queryKeys.workflowRuns.all, "list", workflowId]` instead of `queryKeys.workflowRuns.list(workflowId)`. Prefix invalidation is *correct* for filter variants, but it should be a named helper on the factory (e.g. `listPrefix(workflowId)`) so the “no inline keys” rule stays honest.
- `useWorkflowRunsQuery` uses the inline key `["workflow-runs", "disabled"]` when `workflowId` is null.
- Almost no optimistic updates (CLAUDE.md documents the pattern; git sync is the example). Not a blocker.

### 4.5 Default parameters / memoized hook returns — **partial fail**

**Good:** builder, device selector, node config modal, executions panel use `EMPTY_*` constants.

**Violations of the “never `= []`” rule:**

```ts
existingSourceIds = []   // nautobot/git/ise/pyats source dialogs
workflowNodes = []       // deploy-rendered-template, merge-content, route-on-content,
workflowEdges = []       // store-artifact, compare-data, filter-output
plugins = []
```

If a parent omits those props, each render is a new array. Any `useEffect`/`useMemo` that lists them will loop. `node-config-modal.tsx` currently passes `EMPTY_*` constants, which hides the bug today.

**Custom hooks that return a fresh object every render** (CLAUDE.md requires `useMemo`):

All `use*Mutations()` helpers, including `useWorkflowMutations`, `useSettingsMutations`, `useISESourcesMutations`, feature-local RBAC/template/credential mutation hooks. Callers that destructure (`const { updateWorkflow } = useWorkflowMutations()`) are safe because TanStack’s mutation object identity is relatively stable. Callers that put the whole return value in a dependency array are not. Memoizing the return is still the project rule.

`useApi()` and most inventory hooks **do** memoize. `useSessionManager` memoizes its return.

### 4.6 Shadcn / Tailwind tokens — **partial fail**

Shadcn is used widely (Button, Dialog, Form, Input, Select, Tabs, Card, Badge, Switch, Table, Tooltip, Checkbox, Alert). Login, however, uses raw `<input>` instead of `@/components/ui/input`. The Nautobot preview dialog is a hand-rolled modal (`fixed inset-0 …`) instead of `Dialog`.

Arbitrary palette classes appear throughout inventory and status UI:

- `bg-blue-100`, `bg-blue-600`, `text-blue-700`, `bg-green-500`, `bg-red-50`, `border-blue-200`, …
- Files: `condition-tree-builder.tsx`, `condition-group.tsx`, `group-tree-panel.tsx`, `manage-inventory-modal.tsx`, `load-inventory-modal.tsx`, `step-visuals.ts`, `credential-status-badge.tsx`, and others.

CLAUDE.md: use `bg-background` / `text-foreground` / semantic variants, not `bg-blue-500`. Status colours are a reasonable exception **if** they go through one helper (`step-visuals.ts` already does this for the canvas). Inventory still inlines them.

Inline `style={{ paddingLeft, height, minHeight }}` is used for tree indent and pane sizing. Acceptable for computed layout; not a colour violation.

### 4.7 Forms — **mixed**

Credentials, users, roles, sources, several workflow dialogs: `react-hook-form` + `zod` + (often) Shadcn `Form`.

Login, many step ConfigPanels, and inventory condition builders: local `useState` + native inputs. Step config is inherently dynamic (registry-driven), so Zod-per-step is optional; login should still use Shadcn `Input` + Zod.

### 4.8 React Query vs `useState`+`useEffect` for server data — **partial fail**

Login OIDC providers, builder canvas load, and check-name are the main server-data `useEffect`+`fetch` cases. `useDevicePreview` wraps a mutation and local UI flags; that is fair for an on-demand POST.

### 4.9 GraphQL — **pass**

Centralized service rule is vacuously satisfied: the frontend does not speak GraphQL.

### 4.10 Workflow step UI — **pass**

`plugin-ui-registry.ts` maps step ids to ConfigPanels. `workflow-node.tsx` has no per-step render branch. Help panels are separate files.

### 4.11 Sidebar / permissions UX — **gap, not a backend hole**

`app-sidebar.tsx` shows every nav item to every authenticated user. `hasPermission` is used on tools pages, users tab, executions delete, and the settings users section. Settings, inventory, templates, and workflow run/delete are not hidden when the user lacks the matching permission. The API will 403 (`useApi` throws “Permission denied”). For a first release, hide or disable nav items the user cannot use.

### 4.12 Compliance scorecard

| Rule | Status |
|---|---|
| Route stubs only | Pass |
| Feature-based folders | Pass |
| Proxy-only (no direct backend) | Pass |
| Proxy-only *via* `useApi` / query hooks | Fail (builder, login, check-name) |
| Query key factory | Pass, with two inline-key nits |
| TanStack Query for server data | Mostly pass |
| `DEFAULT_OPTIONS = {}` on optional query args | Pass where options exist |
| No `= []` default props | Fail (source dialogs, several ConfigPanels) |
| Memoized custom-hook returns | Fail on mutation hooks |
| Shadcn for primitives | Mostly pass |
| Semantic Tailwind tokens | Fail in inventory / some badges |
| No `alert`/`confirm` | Pass (Dialog used) |
| No inline GraphQL | Pass |
| Zustand for client-only state | Pass (`auth-store`, `use-workflow-builder-store`) |
| `hasPermission` for UX | Partial |
| TypeScript strict | Pass |

---

## 5. Security findings

Severity: **P0** = fix before first production traffic; **P1** = fix in the first production hardening sprint; **P2** = backlog / defence in depth.

The JWT itself is not in JS-accessible storage. XSS would still be serious (it could call `/api/proxy/*` with the cookie), but there is no current DOM XSS sink. The P0 items are secret *exfiltration via design*, not XSS.

### 5.1 P0 — Nautobot tokens in GET query strings

The settings API returns source `value` as an untyped dict. The frontend parses `token` and keeps it in React Query cache and component props (`useNautobotSourceCredentials`, `useInventorySource`, `InventoryPage` → `DeviceSelector`).

Three GET call sites then put that token on the URL:

```185:188:frontend/src/components/features/inventory/components/device-selector.tsx
          const params = new URLSearchParams({ nautobot_url, nautobot_token });
          const response = await apiCall<InventoryPreviewApiResponse>(
            `sources/nautobot/${id}/devices?${params.toString()}`,
```

```48:53:frontend/src/hooks/queries/use-get-nautobot-devices-field-values-query.ts
      const params = new URLSearchParams({
        nautobot_url,
        nautobot_token,
      });
      const response = await apiCall<FieldValuesResponse>(
        `sources/nautobot/field-values/${encodeURIComponent(field)}?${params.toString()}`,
```

Same pattern in `use-inventory-custom-fields-query.ts`.

**Impact:** tokens appear in Next.js / reverse-proxy / WAF access logs, browser DevTools, and any HTTP referrer if a subsequent navigation occurred (fetch itself is less referrer-prone, logs are enough). This is incompatible with a production NetDevOps controller.

**Fix (frontend + backend, but the frontend must stop sending the secret):**

1. Settings GET should return `token_configured: true` (or a redacted placeholder), never the raw token — same pattern already used for Hatchet (`token_configured`).
2. Preview / field-values / custom-fields / inventory-devices APIs should take `source_id` only. The backend looks up the token server-side.
3. Until (1)–(2) land, at least move tokens from query string to POST body (still in the browser, but not in access logs).

Device SSH passwords in the credentials feature already follow the right model (`has_password`, write-only). Sources should match.

### 5.2 P0 — OIDC `state` check is skipped when storage is empty

```39:46:frontend/src/components/features/auth/oidc-callback-page.tsx
      const storedState = sessionStorage.getItem("oidc_state");
      sessionStorage.removeItem("oidc_state");

      if (storedState && state !== storedState) {
        setError("Invalid state parameter — possible CSRF attempt");
        setStatus("error");
        return;
      }
```

If `storedState` is missing (new tab, cleared storage, or a login the victim never started), **any** `state` is accepted and the code is POSTed to `/api/auth/oidc/{provider}/callback`.

That is classic OAuth2 login CSRF: an attacker who completed an authorization as themselves can bind the victim’s browser session to the attacker’s account (or complete a code the victim did not initiate, depending on IdP mixing).

**Fix:** reject unless `storedState` is present **and** equal to `state`. Prefer `sessionStorage` + a nonce that the backend also remembers (double-submit is weaker than a server-side state store, but failing closed is the minimum).

`providerId` is parsed from the attacker-controlled `state` (`state.split(":", 2)[0]`) and interpolated into the callback URL. Constrain it to a known provider id allow-list.

### 5.3 P0 — Developer / break-glass tools in the product origin

`/tools` is not in the sidebar (good) but is a normal dashboard route. It exposes:

| Tool | Risk if reachable in production |
|---|---|
| `/tools/oidc-test` | Shows client ids, endpoints, starts logins with overridden `redirect_uri` / `client_id` / scopes. |
| `/tools/oidc-test-callback` | Exchanges the code via **`/api/proxy/auth/oidc/.../callback`**, not `/api/auth/oidc/.../callback`. The generic proxy returns the **backend JSON, including `access_token`**, and the page renders JWT header/payload/raw token. |
| `/tools/database-migration` | Live schema migrate + RBAC re-seed. Frontend gates on `system.database:write` / `system.rbac:write`. |
| `/tools/add-certificate` | Installs CAs into the **system trust store**. Frontend gates on `system.certificates:write`. |

RBAC on the backend is necessary but not sufficient: a stolen admin session, or an over-broad admin role for day-one, turns these into production incident tools.

**Fix for v1:** compile them out (`NODE_ENV === "production"` or an explicit `ENABLE_DEV_TOOLS=false`), or put them on a separate bind/admin host. The OIDC test callback must never use the generic proxy (it leaks JWTs into JS).

### 5.4 P1 — Secrets in the browser more generally

Even after removing query-string tokens:

- `GET /settings?key_prefix=source.nautobot.` hydrates full tokens into React Query.
- Preview POSTs (`sources/nautobot/preview`) send `nautobot_url` + `nautobot_token` in the JSON body from the client.
- Git source configs parse `token` the same way (`parse-source-settings.ts`).
- Template editor receives `nautobotToken={sourceCredentials.token}` and can POST it for device config fetch.

Treat source secrets like credential passwords: write-only from the UI, resolved by id on the server.

ISE/Git dialogs already blank the secret on edit (“leave empty to keep”). That UX is right; the GET response still supplying the old secret so `resolveToken()` can reuse it is what keeps the secret in memory.

### 5.5 P1 — Content-Security-Policy is only clickjacking

`next.config.ts` sets:

- `Content-Security-Policy: frame-ancestors 'none'`
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`

Missing for a production HTTPS deployment:

- A real CSP (`default-src 'self'`, `script-src` with Next nonces, `connect-src 'self'`, `frame-src 'none'`, `object-src 'none'`). Monaco is self-hosted at `/vs`, which actually makes CSP *easier* than a CDN editor.
- `Strict-Transport-Security` (once TLS is on).
- `Permissions-Policy` (camera, geolocation, usb, etc. unused).
- `Cross-Origin-Opener-Policy` / `Cross-Origin-Resource-Policy` as needed.

Clickjacking is already handled. XSS blast radius is not.

### 5.6 P1 — Leftover debug logging

`use-get-git-devices-preview-mutation.ts` and `get-git-devices/index.tsx` call `console.debug("[DEBUG] …")` with request/response objects. Strip before release. Do not log preview payloads.

### 5.7 P1 — Cookie / session hardening

Current cookie is a reasonable SPA baseline (`HttpOnly` + `SameSite=Lax` + `Secure` in production). Remaining gaps:

- **Logout is local only.** `POST /api/auth/logout` deletes the cookie; it does not tell FastAPI to revoke the JWT. Stolen cookies work until `expires_in`. Fine for a short TTL; document the TTL and consider a denylist (Redis already exists) if sessions last hours.
- **`cookieStore.delete` vs set options.** Login sets `path: "/"`. Confirm logout/delete uses the same path/name so the cookie actually clears behind some proxies (Next.js 16 usually does; verify once behind Traefik/nginx).
- **No `__Host-` prefix** and no explicit `Priority`. Optional.
- **CSRF:** same-origin proxy + `SameSite=Lax` blocks cross-site POSTs. State-changing **GET**s that include secrets (see 5.1) are the real CSRF/log issue, not a missing CSRF token. Do not add a CSRF token until you have a reason; do stop putting secrets on GET.

Dashboard layout calls `/auth/me` on every navigation. That is a latency cost, not a security bug.

### 5.8 P1 — Proxy path normalization

`normalizeProxyPath` `encodeURIComponent`s each segment (good; ISE `#` in names was a real bug). `..` is *not* encoded away (`encodeURIComponent("..") === ".."`), so a request to `/api/proxy/../non-api` becomes `http://backend/api/../non-api` → `http://backend/non-api`. Same host, but it can skip the `/api` prefix.

Reject segments that are `''`, `'.'`, or `'..'` before join. Do not allow the `api/` prefix bypass to reach non-API backend mounts you did not intend.

The proxy is **not** an open SSRF (fixed `BACKEND_URL` only). Hop-by-hop and `Set-Cookie` stripping is correct.

### 5.9 P2 — Hatchet dashboard URL

`hatchet-settings-canvas.tsx` links `data.dashboard_url` with `target="_blank"` `rel="noopener noreferrer"`. The value comes from server env (`HATCHET_DASHBOARD_URL`), not users. Still validate `https:` (or `http:` for lab) before rendering `href`, so a future misconfig cannot become `javascript:`.

### 5.10 P2 — Permission freshness

Permissions live in Zustand after `/api/auth/me`. They refresh on the 15-minute session renew. A revoke is not visible until then; the **API still denies**. Acceptable if documented. Optional: refetch `/me` on window focus (Query already refetches other resources on focus; auth does not).

### 5.11 P2 — OIDC test callback vs production callback

Production callback correctly uses `/api/auth/oidc/.../callback` (sets cookie, returns `{ user }`). Test callback uses the proxy and displays tokens. See 5.3.

### 5.12 What we did *not* find (do not re-investigate without new evidence)

- JWT or passwords in `localStorage` (OIDC `state` in `sessionStorage` is expected).
- Browser talking to FastAPI CORS / `:8000`.
- `dangerouslySetInnerHTML` of device output.
- Credential list returning plaintext passwords.
- Login JSON returning `access_token` to the SPA.
- Missing 401 handling on the shared `useApi` path.

Backend items in `doc/SECURITY-NOTES.md` (`verify_ssl=False`, Netmiko host keys, git argv, pyATS HTTP) remain accepted risks on the **server** side; they are not frontend defects.

---

## 6. Production-readiness (non-security)

### 6.1 No frontend tests

There are **zero** `*.test.ts(x)` / `*.spec.ts(x)` files under `frontend/`. Backend has a substantial unit suite. For v1, add at least:

- `buildBackendUrl` / `normalizeProxyPath` (including `#`, `..`, `api/` prefix).
- `hasPermission` precedence is backend, but the helper still needs tests.
- OIDC callback fail-closed `state` behaviour (once fixed).
- Query-key factory stability.

Playwright for login → proxy 401 → redirect is the highest-value E2E.

### 6.2 No `error.tsx` / `loading.tsx` / error boundary

A render throw in a client tree takes down the whole dashboard. Add `app/(dashboard)/error.tsx` and a React error boundary around the canvas (React Flow + Monaco are the crashy parts).

### 6.3 No Next.js middleware

Auth is enforced in the dashboard **layout** (RSC + cookie + `/me`). That is valid. Middleware would let you skip rendering for anonymous users earlier and protect `/tools` by env flag. Optional, not required if layout stays the source of truth.

### 6.4 Login UX / lockout

429 from login is mapped to “Invalid username or password”. That avoids user enumeration of rate limits; it also hides “try later”. Fine. Ensure the backend lockout is actually enabled for v1.

Raw login inputs skip Shadcn focus rings used elsewhere; small a11y inconsistency.

### 6.5 Accessibility

Login labels are associated with inputs. Several custom overlays (Nautobot preview dialog, inventory context menus) are not `Dialog` and have incomplete focus trap / `aria-modal` behaviour. The preview dialog sets `role="dialog"` and `aria-modal` but not `Dialog` focus management.

### 6.6 Bundle / Monaco

Monaco is copied to `public/vs` (air-gap friendly). Confirm `next build` does not also pull the CDN. CSP in 5.5 must allow `/vs`.

### 6.7 Query cache and large artifacts

`useArtifactQuery` pulls artifact `content` as a string into React Query (`staleTime` 5 minutes). Large config backups will live in memory for every open run detail. Consider streaming / size caps in the viewer (related to splitting `step-result-viewer.tsx`).

### 6.8 CLAUDE.md version drift

CLAUDE.md lists Next.js **16.2.6**; `package.json` has **16.2.12**. Harmless; update the doc when convenient. Port in CLAUDE.md is 3000; `npm run dev` uses **3001**.

---

## 7. Suggested split for the two blocking files

### 7.1 `workflow-builder-page.tsx`

Keep the page as a composer (~200 lines): topbar, canvas, properties, dialogs.

Move out:

1. **Canvas state + React Flow handlers** → `hooks/use-workflow-canvas.ts` (already has Zustand for metadata/draft; canvas arrays should stay in one hook, not more Zustand, unless you want time-travel).
2. **Persistence** → `hooks/use-workflow-persistence.ts` using `useWorkflowQuery` + `useWorkflowMutations` (delete the raw `fetch`).
3. **Run / save-and-run** → `hooks/use-workflow-run-actions.ts`.
4. Confirm dialogs can stay inline or become `dialogs/unsaved-changes-dialog.tsx`.

### 7.2 `step-result-viewer.tsx`

Folder:

```
components/features/workflows/components/step-result-viewer/
  index.tsx                 # orchestrator
  device-card.tsx
  device-configs-content.tsx
  debug-logs-panel.tsx
  log-attributes-panel.tsx
  metadata-panel.tsx
  comparison-diff-content.tsx
  ...
```

Do not change rendering behaviour in the same PR as the split.

---

## 8. Recommended order for a first production release

**Stop-ship**

1. Stop putting source tokens on GET URLs; switch those endpoints to `source_id` (and stop returning tokens from `GET /settings`).
2. Fail closed on OIDC `state`.
3. Disable or isolate `/tools` (especially OIDC test callback JWT display) in production builds.
4. Remove `[DEBUG] console.debug` call sites.

**Before or immediately after first deploy**

5. Split `workflow-builder-page.tsx` and `step-result-viewer.tsx`.
6. Replace remaining raw `/api/proxy` `fetch` with query/mutation hooks (`useWorkflowQuery` is already written).
7. Replace `= []` default props with module constants.
8. Real CSP + HSTS once HTTPS is on.
9. Reject `..` path segments in the proxy.
10. Permission-aware sidebar.
11. `error.tsx` + canvas error boundary.
12. Proxy unit tests + one Playwright login path.

**Backlog (does not block a cautious internal v1)**

13. Semantic colours in inventory.
14. Login Shadcn + Zod.
15. Memoize mutation-hook return objects.
16. Restore or delete the `BEST_PRACTICES.md` references in CLAUDE.md.
17. Hide Settings sub-pages the user cannot use.
18. Artifact viewer size limits.

---

## 9. Appendix — inventory of notable call sites

### Raw `fetch` (browser)

- `lib/auth-store.ts` — `/api/auth/me|login|logout` (correct)
- `hooks/use-session-manager.ts` — `/api/auth/refresh` (correct)
- `features/auth/login-page.tsx` — `/api/proxy/auth/oidc/providers` and OIDC authorize start
- `features/auth/oidc-callback-page.tsx` — `/api/auth/oidc/:id/callback` (correct route; broken `state` logic)
- `features/tools/oidc-test/*` — proxy callback (wrong for JWT handling)
- `workflow-builder-page.tsx` — `GET /api/proxy/workflows/:id`
- `workflow-save-as-dialog.tsx` / `workflow-import-dialog.tsx` — `GET /api/proxy/workflows/check-name`

### Tokens on the wire from the SPA

- GET query: `device-selector.tsx`, `use-get-nautobot-devices-field-values-query.ts`, `use-inventory-custom-fields-query.ts`
- POST body: `use-get-nautobot-devices-preview-mutation.ts`, `get-nautobot-devices/preview-dialog.tsx`, template editor config fetch, `use-source-test-connection-mutations.ts`

### Files > 500 lines (complete)

`workflow-builder-page.tsx`, `step-result-viewer.tsx`, `store-artifact/index.tsx`, `template-editor-page.tsx`, `add-to-nautobot-dialog.tsx`, `compare-data/index.tsx`, `workflow-import-dialog.tsx`, `manage-inventory-modal.tsx`, `update-device-dialog.tsx`, `workflow-properties-panel.tsx`, `condition-tree-builder.tsx`, `sources-settings-canvas.tsx`, `node-config-modal.tsx`, `workflow-manage-dialog.tsx`.
