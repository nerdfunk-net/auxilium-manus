# Frontend Analysis

**Date:** 2026-08-21 (scorecard re-check after code updates; original review 2026-08-20)  
**Scope:** `/frontend` (~560 TypeScript/TSX files under `frontend/src`).  
**Standards:** `CLAUDE.md` frontend architecture, UI, TanStack Query, React anti-patterns, auth/proxy, and security checklist.  
**Method:** Static review of App Router routes, the Next.js proxy, auth cookies, query hooks, feature modules, workflow canvas, settings/tools, and the largest source files. Runtime pentest was not performed. Scorecard statuses below were re-verified against the current tree.

This document records **compliance with `CLAUDE.md`**, **security risks**, **oversized modules**, and **duplication**. Backend-owned risks already captured in `doc/analysis/GROK_46.md` and `doc/SECURITY-NOTES.md` are referenced rather than re-litigated.

---

## 1. Executive summary

The frontend is in **good structural health** relative to `CLAUDE.md`:

- Feature-based layout under `components/features/{domain}/` is the real home of UI. Route files are stubs.
- Browser traffic goes through `/api/proxy/*` or dedicated `/api/auth/*` BFF routes. There are **no** client `fetch` calls to `localhost:8000` / `BACKEND_URL`.
- JWT lives in an **httpOnly**, `SameSite=lax` cookie (`auxilium_auth_token`). It is never written to `localStorage`.
- Dashboard routes are gated **server-side** in `(dashboard)/layout.tsx` (cookie present **and** backend `/api/auth/me` succeeds).
- TanStack Query is the default for server state. Query keys live in a central factory (`lib/query-keys.ts`).
- React Flow (`@xyflow/react`) is the canvas. Zustand holds editor UI + canvas draft, not the source of truth for saved workflows.
- Shadcn/Radix + Tailwind semantic tokens are the UI system. No `alert()` / `confirm()`. No `dangerouslySetInnerHTML`.
- Security headers (CSP, `X-Frame-Options: DENY`, `nosniff`, HSTS in production) are set in `next.config.ts`.

The main gaps are **layering inside features** (fat hooks and ConfigPanels), **almost no frontend tests**, and **hardening** that `CLAUDE.md` does not fully specify: CSP `'unsafe-eval'`/`'unsafe-inline'` (Monaco), `ENABLE_DEV_TOOLS` only gated by env (not by `NODE_ENV`), sensitive run/artifact payloads cached in the QueryClient, and product-direction drift (device-first flow, RHF on step forms). TanStack Query is now the default for the former template-editor / Netmiko-search / render / canvas-rehydrate fetches; leftover server calls are mostly event-handler `apiCall`s rather than `useEffect`.

`CLAUDE.md` itself is **stale** on the frontend port (architecture still says 3000). Next.js version and the GraphQL-helper path were brought in line. Remaining drifts are listed in §7.

---

## 2. Compliance scorecard vs `CLAUDE.md`

| Rule | Status | Notes |
|------|--------|--------|
| Feature-based organization (`components/features/{domain}/`) | **Pass** | Domains: `auth`, `dashboard`, `inventory`, `settings`, `templates`, `tools`, `workflows`, `workflow-steps`. Root `components/` only has `features/`, `layout/`, `providers/`, `ui/`. |
| Route files are stubs | **Pass** (with two routing exceptions) | All `(dashboard)` and `(auth)` `page.tsx` files re-export a feature page. `settings/[section]/page.tsx` parses the section and `notFound()`s — Next.js routing, not feature logic. `tools/page.tsx` passes `ENABLE_DEV_TOOLS`. |
| No `'use client'` on route files | **Pass** | Zero matches under `app/**/page.tsx`. |
| No `components/` or `dialogs/` under `app/` | **Pass** | |
| Kebab-case feature files | **Pass** | No PascalCase `.tsx` filenames under `features/`. |
| API proxy only (never direct backend from the browser) | **Pass** | `useApi` always hits `/api/proxy/...`. Auth uses `/api/auth/*`. `BACKEND_URL` is server-only in `lib/api-proxy.ts`. |
| JWT not in `localStorage`; cookie auth | **Pass** | httpOnly cookie set by login/refresh/OIDC BFF routes. |
| Frontend permission checks are UX-only | **Pass** | `lib/permissions.ts` documents this. Sidebar/settings/tools hide UI; backend still enforces. |
| Central `queryKeys` factory | **Pass** | Two inline fallback keys for disabled queries: `use-workflow-run-query.ts` (`["workflow-runs", "disabled"]`) and `use-workflow-schedule-query.ts` (`["workflows", "schedule", "disabled"]`). |
| TanStack Query for server data (not `useState`+`useEffect`) | **Mostly pass** | Dominant pattern. Template editor (device attributes, Netmiko search, render, Get Configs) and canvas rehydrate now use `useQuery`/`useMutation`. Remaining: event-handler `apiCall` for load-workflow / load-inventory / execute-commands; ConfigPanel `useEffect` is local form init, not a fetch. |
| Query hooks in `/hooks/queries/` | **Partial** | 61 files there. Templates, credentials, and RBAC hooks still live under `features/*/hooks/` (allowed by feature layout, conflicts with the centralized-hooks sentence). |
| `DEFAULT_OPTIONS = {}` constant | **Partial** | Followed in every optional-options query hook except `use-saved-inventories-query.ts` (`options = {}` on two exports). |
| Custom hooks memoize returned objects | **Partial** | `useApi`, `useSessionManager`, `useTemplateRender`, `useSavedInventories` (fixed 2026-08-21 — see `doc/READ_BEFORE_FRONTEND_ANALYSIS.md`), and most mutation hooks now memoize. Unmemoized returns: `useToast`, `useConditionTree`, `useTemplateEditorDevice`, `useDashboardLayoutMutations`, `useNautobotSourceCredentials`. |
| Zustand for editor-only state, not server data | **Pass** | `use-workflow-builder-store.ts` is canvas draft + UI chrome. Auth store holds `/me` user (session, not a list resource). |
| React Flow for canvas; definition separate from UI state | **Pass** | Persist payload is `canvas_nodes` / `canvas_edges` / `canvas_groups` / `static_attributes`. Backend owns executable conversion. |
| Shared canvas node (`w-80` × `h-32`), registry-driven ConfigPanel | **Pass** | `workflow-node.tsx` is the shared step tile. Extra React Flow types (`groupNode`, `labelNode`, `backgroundNode`, `funnelNode`) are canvas decorations, not per-step render forks. |
| `PLUGIN_UI_REGISTRY` for step ConfigPanels | **Pass** | 49 step packages under `workflow-steps/`, registered in `lib/plugin-ui-registry.ts`. |
| React Hook Form + Zod for forms | **Partial** | Settings/source/credential/user dialogs plus workflow save-as / manage / import / run-inputs / schedule and template import use it. Login and most workflow step ConfigPanels are still uncontrolled `useState`. |
| Shadcn for all primitives | **Pass** | 17 `components/ui/*` primitives. `get-nautobot-devices/preview-dialog.tsx` now uses Shadcn `Dialog` (fixed 2026-08-21; previously a custom overlay missing Escape/focus-trap/portal behavior). |
| Tailwind semantic tokens (no `bg-blue-500`) | **Mostly pass** | Inventory condition tree and step category chips use palette colors (`purple-*`, `indigo-*`, `sky-*`). |
| No `alert()` / `confirm()` | **Pass** | Confirmations use `Dialog`. `AlertDialog` is unused. |
| No inline GraphQL in components | **Pass** | There is **no** `frontend/src/services/nautobot-graphql.ts`. Inventory/Nautobot goes through backend REST via the proxy. `CLAUDE.md` now documents this; no client GraphQL layer to add. |
| Server Components by default | **Partial / expected** | Majority of ~560 TS/TSX files are `'use client'`. Appropriate for an interactive SPA-like dashboard. Root layout, dashboard layout (auth), and route stubs are server. |
| Monaco only for advanced templates | **Pass** | `@monaco-editor/react` is used in the template editor (`code-editor-panel.tsx`), self-hosted under `public/vs` (no CDN). |
| Device-first product flow | **Gap** | Inventory is a standalone builder. Workflows pick devices **inside steps** (`get-nautobot-devices`, etc.), not “select devices, then compose steps” as the primary UI. |
| Tests / BEST_PRACTICES.md | **Fail** | Four Vitest files (`api-proxy`, `oidc-state`, `auto-layout`, `schedule-cron`). `hooks/queries/BEST_PRACTICES.md` and `OPTIMISTIC_UPDATES.md` are still missing; current `CLAUDE.md` no longer cites them. |

---

## 3. What is implemented well

### 3.1 Route stubs and feature layout

Dashboard and auth pages follow the mandated stub:

```1:4:frontend/src/app/(dashboard)/workflows/page.tsx
import { WorkflowBuilderPage } from "@/components/features/workflows/workflow-builder-page";

export default function WorkflowsRoute() {
  return <WorkflowBuilderPage />;
}
```

The same pattern holds for dashboard, inventory, templates, template editor, runs, tools, OIDC test, database migration, add-certificate, login, OIDC callback, and approval-pending.

`settings/[section]/page.tsx` is the only route with real Next.js work (`generateStaticParams`, `parseSettingsSection`, `notFound()`). That is routing, not feature logic.

### 3.2 Proxy-only API access

`hooks/use-api.ts` always calls `/api/proxy/${endpoint}` with `credentials: "include"`. The BFF (`lib/api-proxy.ts`) then:

- Builds `BACKEND_URL` (default `http://127.0.0.1:8000`) **only on the server**.
- Rejects `.` / `..` / empty path segments.
- Re-encodes segments (so `#` in ISE group names cannot become a URL fragment).
- Strips hop-by-hop headers, inbound `Cookie`/`Authorization`, and outbound `Set-Cookie`.
- Attaches `Authorization: Bearer <httpOnly cookie>`.
- Uses `redirect: "manual"` (no open-redirect follow).
- Maps backend connect failures to a generic 503.

Covered by `frontend/src/lib/api-proxy.test.ts`.

### 3.3 Auth cookie and dashboard gate

Login, refresh, and OIDC callback set:

```
httpOnly: true
sameSite: "lax"
secure: NODE_ENV === "production"
path: "/"
maxAge: expires_in from backend
```

The JWT never reaches client JS. `sessionStorage` is used only for OIDC `state` (CSRF binding), which is the normal SPA OIDC pattern.

`(dashboard)/layout.tsx` is a Server Component: missing/invalid cookie → `redirect("/login")` after a live `/api/auth/me` check. This is stronger than a client-only Zustand gate.

Idle timeout + sliding refresh live in `use-session-manager.ts` (refresh every 15 minutes while active; logout after configured idle minutes).

### 3.4 Query key factory and polling

`lib/query-keys.ts` is hierarchical and used consistently. Workflow run polling matches the documented job pattern (`staleTime: 0`, interval stops when the run is no longer active, faster poll while paused in debug mode).

### 3.5 Workflow builder split

| Concern | Where it lives |
|---------|----------------|
| Canvas UI state | `use-workflow-canvas.ts` + Zustand draft |
| Persisted definition | `canvas_*` fields sent through `use-workflow-mutations.ts` |
| Run + step results | TanStack Query (`use-workflow-run-query`, artifacts) |
| Step ConfigPanel | `workflow-steps/{id}/index.tsx` via `PLUGIN_UI_REGISTRY` |
| Shared node chrome | `workflows/components/nodes/workflow-node.tsx` (`w-80` `h-32`) |

That matches the canvas / definition / run split in `CLAUDE.md`.

### 3.6 XSS surface

No `dangerouslySetInnerHTML`, `innerHTML`, `eval`, or `new Function`. Step results and logs are rendered as React text / `<pre>` + `JSON.stringify`. Markdown is not interpreted. `target="_blank"` on the Hatchet dashboard link includes `rel="noopener noreferrer"`.

---

## 4. Standard violations

Findings are ordered by architectural impact, not file size.

### 4.1 Server fetches outside TanStack Query (low)

The `useState` + `useEffect` fetches from the first review have moved onto Query:

| Location | Current state |
|----------|----------------|
| Device attributes | `useDeviceAttributesQuery` |
| Netmiko device search | `useNetmikoDeviceSearchQuery` (debounce `useEffect` is local UI, not a fetch) |
| Template render | `useMutation` in `use-template-render.ts` |
| Get Configs (SSH) | `useMutation` + explicit button in `use-template-editor-device.ts` |
| Canvas rehydrate | `useQuery` in `use-workflow-persistence.ts` |

Remaining **event-handler** `apiCall`s (not `useEffect`, still not `useMutation`):

| Location | What it fetches |
|----------|-----------------|
| `workflows/hooks/use-workflow-persistence.ts` `handleLoadWorkflow` | `GET workflows/{id}` when opening a workflow from the dialog |
| `inventory/hooks/use-saved-inventories.ts` `loadInventory` | `GET sources/nautobot/{id}` |
| `templates/hooks/use-template-editor-device.ts` `handleExecuteCommands` | `POST netmiko/run-commands` |
| `inventory/components/device-selector.tsx` | `GET sources/nautobot/{id}/devices` after loading a static inventory |

ConfigPanel `useEffect`s only initialize node config / pick a unique upstream step. That is local form state, not a server fetch.

**Why it matters:** One-shot open/load/execute paths skip QueryClient cache and cancellation. Lower impact than the old auto-SSH-on-select `useEffect`.

**Fix:** Wrap the remaining handlers in `useMutation` (or `useQuery` with `enabled` for load-by-id).

### 4.2 Inline `useQuery` in a dialog (fixed 2026-08-21)

`workflow-steps/get-nautobot-devices/preview-dialog.tsx` called `useQuery` directly (fine — that's compliant TanStack Query usage) but drew a **custom** modal (`fixed inset-0` + `bg-black/50`) instead of Shadcn `Dialog`. That was a real, if minor, accessibility gap versus Radix `Dialog`: no Escape-key handling, no focus trap, no Portal rendering. Fixed by swapping to `Dialog`/`DialogContent`/`DialogHeader`/`DialogFooter` (same pattern as the parallel `get-ise-devices/preview-dialog.tsx`), keeping the inline `useQuery` as-is.

The other observation — reuse `use-get-nautobot-devices-preview-mutation.ts` — turned out weaker on inspection: that hook only covers the filter-operations request, not the static device-ID preview this dialog also needs, so full reuse would require extending the hook first. Not done as part of this fix.

### 4.3 Query-hook location split (low)

`CLAUDE.md` asks for TanStack hooks in `/hooks/queries/*` **and** for feature folders to contain `hooks/`. The repo does both:

- Central (61 files): workflows, settings (hatchet/redis/logging/general), dashboard, sources, certificates, schema, artifacts, plus the newer `use-device-attributes-query` and `use-netmiko-device-search-query`.
- Feature-local: templates, credentials, RBAC users/roles/permissions.

This is readable, but invalidation and discovery suffer (e.g. `queryKeys.templates` is used from `features/templates/hooks/`). Pick one convention and document it. Feature-local hooks for a bounded domain are fine if they still use `queryKeys`.

`use-saved-inventories-query.ts` still uses `options = {}` (new object every call) on both exports. Other optional-options hooks already use `const DEFAULT_OPTIONS = {}`.

### 4.4 React Hook Form not used on step ConfigPanels (low)

Settings dialogs (Git/Nautobot/ISE/Mattermost/pyATS, credentials, users, roles) correctly use `react-hook-form` + Zod, as do workflow save-as / manage / import / run-inputs / schedule and template import.

Workflow step ConfigPanels (the majority of `workflow-steps/*/index.tsx`) and the login form are still hand-rolled `useState`. That is the largest remaining gap versus “RHF + Zod for node configuration forms.”

### 4.5 `useToast` return is not memoized (low)

```24:47:frontend/src/hooks/use-toast.ts
export function useToast() {
  const { addToast, removeToast, toasts } = useToastStore();
  // ...
  return { toast, dismiss, toasts };
}
```

This returns a new object every render and subscribes to the whole toast store (no selector). It has not produced an obvious loop, but it is exactly the anti-pattern `CLAUDE.md` calls out. Prefer `useToastStore((s) => s.addToast)` plus a memoized return.

Same unmemoized return in `inventory/hooks/use-condition-tree.ts`, `use-template-editor-device.ts`, `use-dashboard-layout-mutations.ts`, and `use-nautobot-source-credentials.ts`. `use-saved-inventories.ts` was fixed 2026-08-21 (see `doc/READ_BEFORE_FRONTEND_ANALYSIS.md`) after its unmemoized return was found to actually defeat downstream `useCallback` stability in `device-selector.tsx`. Most other mutation hooks now wrap their return in `useMemo`. `useApi` still uses `init: RequestInit = {}` as a default argument (harmless for a callback, still the documented anti-pattern).

### 4.6 Arbitrary Tailwind palette colors (low)

`CLAUDE.md` wants `bg-background` / `text-foreground`, not `bg-blue-500`. Remaining palette usage:

- Inventory condition tree: `border-purple-*`, `bg-purple-*` (`condition-group.tsx`, `condition-tree-builder.tsx`, `device-table.tsx`).
- Step category chips in `workflows/utils/step-visuals.ts`: `bg-indigo-100`, `bg-sky-100`, `bg-purple-100`, etc.

These are visual language for categories, not a second UI kit. Still a documented miss.

### 4.7 Product-direction gaps (medium, product)

- **Device-first:** The primary UI is the workflow canvas (`/` redirects to `/workflows`). Inventory is a separate page. Device targeting is a **step** (`get-nautobot-devices`, `get-ise-devices`, `get-git-devices`), not a first-class “selected inventory → then design steps” shell.
- **GraphQL helper:** Resolved in `CLAUDE.md` — it now forbids a client GraphQL layer and documents backend-proxied REST. Do not add `frontend/src/services/nautobot-graphql.ts`.
- **Port / Next version:** `package.json` runs `next dev --port 3001` and depends on Next `16.2.12`. `CLAUDE.md` now matches the Next version; the architecture bullet still says frontend port 3000 (the development-workflow section already lists 3001).

---

## 5. Security findings

Severities assume a typical private NetDevOps deployment (same threat model as `doc/SECURITY-NOTES.md`). Nothing here is a “anonymous internet user dumps the database” bug; several are “XSS or a stolen session becomes much worse.”

### 5.1 No critical, remotely exploitable frontend bugs found

In particular:

- No token in `localStorage` / `document.cookie` from client JS.
- No XSS sinks (`dangerouslySetInnerHTML`, markdown HTML, `eval`).
- Proxy path traversal (`..`) is rejected and unit-tested.
- Proxy does not forward `Set-Cookie` from the backend (JWT stays in the Next cookie).
- 401 from the proxy redirects to login; 403 is a generic “Permission denied”; 5xx bodies are not blindly interpolated as HTML.
- Login maps both 401 and 429 to “Invalid username or password” (does not advertise lockout to the client).
- OIDC callback verifies `state` against `sessionStorage` (`lib/oidc-state.ts`) before exchanging the code.
- `X-Frame-Options: DENY` + CSP `frame-ancestors 'none'` (clickjacking).
- No `NEXT_PUBLIC_*` secrets. No hardcoded credentials.

Authorization remains a **backend** property. The frontend hiding a nav item is not a security boundary (`lib/permissions.ts` says so explicitly).

### 5.2 High — CSP allows `'unsafe-inline'` and `'unsafe-eval'` on scripts

```3:7:frontend/next.config.ts
    value:
      "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; ..."
```

This is almost certainly required for Monaco (`worker-src 'self' blob:` is already present for the same reason). It **weakens XSS defense**: a single future HTML injection becomes a full XSS.

**Mitigation options:** nonce-based CSP for Next, Monaco in a tighter sandbox, or document this as an accepted risk next to `doc/SECURITY-NOTES.md`.

### 5.3 High — sensitive payloads in the React Query cache

`useArtifactQuery` stores full artifact `content` (device configs, rendered templates, diffs) in the QueryClient with `staleTime: 5 * 60 * 1000`. Run detail polling stores step metadata **and** content-shaped JSON. Step result viewers stringify attribute bags, Genie parsed configs, and logs into the DOM.

That is required for the product, but:

- A successful XSS (see §5.2) can read configs/secrets from memory.
- Shared-browser / leftover DevTools can retain the last run.
- Workflow steps such as `get-ise-tacacs-key` put shared secrets into device attributes by design; the UI then displays them as JSON.

**Hardening (optional):** `gcTime: 0` for artifacts; avoid caching TACACS/credential fields. Logout already calls `queryClient.clear()` (auth store + idle timeout).

### 5.4 High if mis-set — `ENABLE_DEV_TOOLS` is env, not `NODE_ENV`

OIDC test routes `notFound()` unless `ENABLE_DEV_TOOLS === "true"` (layouts under `tools/oidc-test` and `login/oidc-test-callback`). The tools index only shows the card when that flag is true **and** the user has `system.oidc:read`.

If that env var is set in production, the test dashboard can:

- Show OIDC `client_id`, discovery URLs, claim mappings, CA paths.
- POST `auth/oidc/{id}/test-login` with a **user-controlled** `redirect_uri` (backend must allowlist this; frontend does not).
- Use **`/login/oidc-test-callback`**, which sits under `(auth)` (no dashboard session required) and is only gated by the same env flag.
- Exchange the code via **`/api/proxy/auth/oidc/.../callback`** (generic proxy, not the BFF that sets the httpOnly cookie) and **render `access_token` in the DOM** (`JSON.stringify(result)` plus a `JwtPanel` that dumps header, payload, and raw token).

Production OIDC login does **not** do this: `/login/callback` posts to `/api/auth/oidc/.../callback` and never shows the JWT.

This matches the backend analysis: do not treat `ENABLE_DEV_TOOLS` as “dev only” unless deployment forbids it.

### 5.5 Medium — CSRF relies on `SameSite=lax` only

There is no CSRF token. Cookie is `SameSite=lax`, so cross-site **POST** from another origin should not include it. Cross-site **top-level GET** would. The proxy forwards GET/POST/PUT/PATCH/DELETE; safety depends on backend GETs being read-only.

OIDC start is a GET (`auth/oidc/{id}/login?redirect_uri=...`) from the login page; `redirect_uri` is built from `window.location.origin` (not a query `next=`). The test dashboard is the exception (user-editable redirect URI).

**Optional hardening:** `__Host-auxilium_auth_token` (requires `Secure` + `Path=/`), and/or a CSRF double-submit cookie for state-changing proxy POSTs.

### 5.6 Medium — generic proxy is an authenticated API gateway

Any page on the frontend origin can `fetch('/api/proxy/<anything>')` with the cookie. There is no frontend allow-list of backend paths. That is the intended BFF pattern; the backend RBAC is the real gate.

XSS anywhere on the origin therefore equals “call any API the user can call,” including schema migrate / RBAC seed / certificate install if the victim has those permissions.

Two extra proxy behaviours to be aware of:

- **`Location` is not stripped.** `redirect: "manual"` stops the *server* fetch from following redirects, but `copyResponseHeaders` still forwards `Location` to the browser. `useApi` uses the default `fetch` (`redirect: "follow"`), so a backend 302 to an unexpected URL could be followed in the client. Risk is real only if a backend route ever returns an open redirect.
- **Error `detail` is shown in the UI.** Auth BFF routes sanitize 5xx. The generic proxy forwards backend JSON; `useApi` copies `body.detail` into `throw new Error(message)` for every non-401/403 failure. Verbose 4xx from the backend can appear in toasts. 401/403 are already generic (“Authentication required” / “Permission denied”).

### 5.7 Medium — privileged admin tools are URL-reachable

`/tools`, `/tools/database-migration`, and `/tools/add-certificate` sit behind the dashboard auth layout (logged-in user) but **not** a permission check in the layout. Pages hide write buttons with `hasPermission`, but they still **issue queries** (`useSchemaStatusQuery`, `useCertificatesQuery`) as soon as they mount. A user without permission gets a 403 from the backend; the UI is not a second lock.

Database migration + RBAC seed are destructive. Keep them off production or require a dedicated role; that is mostly a backend/deploy concern.

### 5.8 Medium — template editor can trigger live SSH

Selecting a test device with “Get Configs” enabled calls `POST /api/proxy/netmiko/get-configs` from the browser. `doc/SECURITY-NOTES.md` notes the backend denies arbitrary hosts outside development unless `ALLOW_NETMIKO_ARBITRARY_HOSTS=true`. The frontend does not add its own host allow-list (correct — it must not be the only check).

Still: this is a powerful action. It is now an explicit “Fetch configs” button (`fetchDeviceConfigsMutation`), not a `useEffect` side effect of selecting a device. Prefer keeping it as a mutation + confirmation.

### 5.9 Low — OIDC `state` in `sessionStorage`

Standard. A same-origin XSS can forge/read it. Without XSS, CSRF of the code exchange is blocked by the state check.

Provider id is parsed from `state` (`providerId:rest`) and validated with `^[a-z][a-z0-9_-]{0,63}$` before calling `/api/auth/oidc/${providerId}/callback`.

### 5.10 Low — permissions snapshot in Zustand

`/api/auth/me` copies `roles` and `permissions` into the auth store. The JWT itself does not embed them (good). The sidebar can be stale until the 15-minute refresh. UI-only; API calls still 403.

### 5.11 Low — source/credential secrets in form state only

List APIs expose `has_password` / `token_configured`, not secrets. Create/edit dialogs use `type="password"` and placeholders like “Leave blank to keep existing token.” Secrets exist in React state only while a dialog is open. Good.

Git/Nautobot/ISE dialogs allow `verifySsl: false` (accepted backend risk; UI does not extra-gate it).

### 5.12 Low — dashboard is visible to every authenticated user

Sidebar `Dashboard` `canShow: () => true`. Backend dashboard routes are JWT-only (see backend analysis). Not a frontend vuln; worth aligning if dashboard data is considered sensitive.

### 5.13 Low — Hatchet `dashboard_url` is rendered as a link

`hatchet-settings-canvas.tsx` uses `<a href={data.dashboard_url} target="_blank" rel="noopener noreferrer">`. `rel` is correct; the frontend does not check that the scheme is `https:`. Harmless if the backend only stores its own dashboard URL.

### 5.14 Informational — dashboard `error.tsx` hides messages in production

`(dashboard)/error.tsx` shows `error.message` only when `NODE_ENV !== "production"`. Production users see a generic sentence. Good.

### 5.15 Informational — test coverage

Security-sensitive modules with tests: `api-proxy.ts`, `oidc-state.ts`. No tests for login cookie flags, dashboard layout redirects, or `useApi` 401 handling.

---

## 6. Large files and refactor targets

Threshold used here: **~400 lines** is “watch,” **~500+** is “split when touching,” **~700+** is “split soon.” Line counts from `wc -l` on 2026-08-20.

### 6.1 Priority 1 — split on next touch

| File | Lines | Why |
|------|------:|-----|
| `workflows/hooks/use-workflow-canvas.ts` | 922 | God-hook: React Flow changes, grouping, auto-layout, drop-from-catalog, projection, dirty tracking. Highest complexity in the frontend. Split into `use-canvas-nodes.ts`, `use-canvas-groups.ts`, `use-canvas-drop.ts`, `use-canvas-layout.ts` with the current hook as a facade. |
| `workflow-steps/store-artifact/index.tsx` | 770 | ConfigPanel + large duplicated `CONTENT_SOURCE_OPTIONS` picker. |
| `workflow-steps/compare-data/index.tsx` | 695 | Same picker pattern as store-artifact / upload-config / filter-output / merge-content / route-on-content. Extract `ContentSourcePicker`. |
| `templates/template-editor-page.tsx` | 684 | Page orchestrates editor + live Nautobot/SSH side effects. Keep the route stub; move fetch effects into hooks; keep panels as they already are. |
| `workflow-steps/add-to-nautobot/add-to-nautobot-dialog.tsx` | 681 | Fat dialog (device fields, interfaces, custom fields). Split field groups into components. |

### 6.2 Priority 2 — split when the feature is next edited

| File | Lines | Suggested split |
|------|------:|-----------------|
| `settings/components/sources-settings-canvas.tsx` | 638 | One canvas, five source types. Extract per-source sections (Git/Nautobot/ISE/Mattermost/pyATS already have dialogs). |
| `inventory/dialogs/manage-inventory-modal.tsx` | 603 | List + rename + import/export + tree. |
| `workflows/dialogs/workflow-import-dialog.tsx` | 603 | Parse / preview / credential remap / submit. |
| `workflows/components/workflow-properties-panel.tsx` | 573 | Catalog + edge style + schedule + static attributes already have child components; the parent still owns too much. |
| `workflow-steps/update-nautobot-device/update-device-dialog.tsx` | 561 | Same family as add-to-nautobot dialog. |
| `inventory/components/condition-tree-builder.tsx` | 541 | Tree UI; inventory and `get-nautobot-devices/condition-builder/` are parallel implementations. |
| `workflows/components/node-config-modal.tsx` | 531 | Generic shell + I/O docs + plugin panel. Could drop I/O tab into its own file. |
| `workflows/dialogs/workflow-manage-dialog.tsx` | 525 | CRUD list of workflows. |
| `workflow-steps/compare-pyats-snapshot/index.tsx` | 515 | ConfigPanel. |

Also over 400 lines (watch list): `device-selector.tsx` (470), `upload-config/index.tsx` (463), `deploy-rendered-template/index.tsx` (445), `workflow-schedule-panel.tsx` (436), `set-default-attributes-dialog.tsx` (436), `filter-output/index.tsx` (432), `use-workflow-persistence.ts` (419), `logging-settings-canvas.tsx` (399).

Help panels (many 200–350 lines of static JSX) are documentation, not logic. Do not treat them as the same class of problem as `use-workflow-canvas.ts`.

### 6.3 Duplication to collapse

1. **Content source picker** — extracted to `workflow-steps/shared/content-source-picker.tsx` and used by store-artifact, compare-data, upload-config, filter-output, merge-content, route-on-content. A few panels still keep a local options list (`MERGE_CONTENT_SOURCE_OPTIONS`, `ROUTE_ON_CONTENT_SOURCE_OPTIONS`, `update-content`).
2. **Git source select dialog** — extracted to `workflow-steps/shared/git-source-select-dialog.tsx` (the per-step copies are gone).
3. **Condition trees** — inventory builder vs `get-nautobot-devices/condition-builder/`. Different types (`ConditionTree` vs `FilterTree`) but the same UX. Long-term: one builder.
4. **`parseUserResponse`** — copy-pasted in `app/api/auth/login`, `me`, `refresh`, and OIDC callback routes. Extract next to `lib/auth.ts`.
5. **Source dialogs** — Git/Nautobot/ISE/Mattermost/pyATS dialogs are ~300–350 lines each with the same RHF + test-connection shape. A thin shared shell would shrink `sources-settings-canvas.tsx` dependents.

### 6.4 Files that look large but are fine

- `components/ui/dropdown-menu.tsx` (~240) — Shadcn generated; do not split.
- `workflow-node.tsx` (249) — shared step tile; keep one file.
- `auto-layout.ts` + `auto-layout.test.ts` — already tested; size is justified.

---

## 7. `CLAUDE.md` staleness (frontend)

| Claim in `CLAUDE.md` | Reality |
|----------------------|---------|
| Next.js 16.2.12 | Matches `frontend/package.json` (resolved since the 2026-08-20 review, which still listed 16.2.6 in `CLAUDE.md`) |
| Frontend port 3000 (architecture bullet) | `next dev --port **3001**`. The development-workflow section already lists 3001. |
| GraphQL via `frontend/src/services/nautobot-graphql.ts` | Resolved: `CLAUDE.md` now forbids a client GraphQL layer; Nautobot is backend-proxied REST |
| Query docs `hooks/queries/BEST_PRACTICES.md` and `OPTIMISTIC_UPDATES.md` | Still missing; `CLAUDE.md` no longer cites them |
| Server Components default | True for routes/layouts; the product UI is client-heavy by necessity |

---

## 8. Test and tooling gaps

| Area | State |
|------|--------|
| Vitest | 4 files: `api-proxy.test.ts`, `oidc-state.test.ts`, `auto-layout.test.ts`, `schedule-cron.test.ts` |
| ESLint | `eslint-config-next` core-web-vitals + typescript. React hooks plugin comes with that; few `eslint-disable` (OIDC callback exhaustive-deps, unused vars in Nautobot step configs). |
| Playwright / e2e | Not in `frontend/package.json` |
| Regression scripts | Backend has AST guards; frontend has none (e.g. no check that `page.tsx` stays stub-only, or that `fetch(` only targets `/api/`) |

High-value tests if the suite grows: dashboard layout redirect, cookie flags on login, `useApi` 401, settings section `notFound`, OIDC state mismatch, proxy `#` encoding (already present).

---

## 9. Recommended order of work

1. **Do not add a client GraphQL layer.** `CLAUDE.md` already matches backend-proxied sources.
2. **Finish remaining content-source option lists** — `ContentSourcePicker` and the shared Git source dialog already exist; a few panels still keep a local options array.
3. **Wrap remaining event-handler `apiCall`s in `useMutation`/`useQuery`** — load-workflow, load-inventory, execute-commands. Template-editor attributes/search/render/Get Configs already moved.
4. **Split `use-workflow-canvas.ts`** when the canvas is next changed (do not boil the ocean otherwise).
5. **Shorter `gcTime` for artifacts** (QueryClient is already cleared on logout).
6. **Document CSP `'unsafe-eval'`** and `ENABLE_DEV_TOOLS` as accepted or blocked in production (alongside `doc/SECURITY-NOTES.md`). If the OIDC test UI stays, keep token display behind the env gate and never route it through the generic proxy in production.
7. **Strip `Location` on proxy responses** (or set client `redirect: "manual"`) so a backend 302 cannot become a browser follow.
8. **Add a handful of frontend tests** around proxy, auth cookie, and OIDC state (the security-sensitive BFF).
9. Optionally align cookie name with `__Host-` and add CSRF for proxy POSTs if the app is ever exposed on a shared parent domain.

---

## 10. Scorecard (short)

| Question | Answer |
|----------|--------|
| Is the `CLAUDE.md` frontend standard implemented? | **Mostly yes.** Layout, proxy, cookies, query keys, Shadcn, React Flow, step registry, route stubs, and TanStack Query for the former template-editor fetches are in place. Gaps: RHF not on step forms, hook-folder split, `DEFAULT_OPTIONS` / hook-return memoization leftovers, almost no tests, product “device-first” not the primary shell. |
| Serious security risks in the frontend? | **No critical holes found.** Residual risk is XSS amplification (weak CSP + cached secrets), mis-set `ENABLE_DEV_TOOLS`, and admin tools reachable by URL for any login. Real enforcement is the backend. |
| Large files to refactor? | **Yes.** `use-workflow-canvas.ts` (922), then store-artifact / compare-data / template-editor / add-to-nautobot dialog, then sources canvas and inventory/workflow import modals. Prefer extracting shared pickers before heroic splits. |
