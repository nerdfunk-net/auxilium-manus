# Read Before Frontend Analysis

Read this **before** re-analyzing the frontend for `CLAUDE.md` compliance. It records the
verdict already reached on every `Partial` (and near-`Partial`) row in
`doc/analysis/FRONTEND.md` §2 "Compliance scorecard vs `CLAUDE.md`", so a fresh pass
doesn't re-discover and re-litigate the same accepted exceptions.

**Rule:** if you find one of these again, check the verdict below first. Only re-open it if
something material changed (e.g. an unmemoized hook's return started being used as a
`useEffect`/`useMemo` dependency somewhere, which would turn a cosmetic issue into a real
one). Otherwise, leave it as documented debt and move on.

## Partial items and their verdicts

### 1. Query hooks split between `/hooks/queries/` and `features/*/hooks/`
**Verdict: accepted exception, not harmful.** Templates, credentials, and RBAC hooks live
under `components/features/*/hooks/` instead of the central `hooks/queries/`. Both
locations use the shared `queryKeys` factory correctly and invalidate caches correctly —
verified by reading every feature-local hook. This is a discoverability/consistency nit,
not a bug. Don't flag it as a new finding; only revisit if the team picks one convention.

### 2. `DEFAULT_OPTIONS = {}` missing in `use-saved-inventories-query.ts`
**Verdict: verified harmless, cosmetic only.** `useSavedInventoriesQuery`/
`useInventoryGroupsQuery` use `options: T = {}` instead of a module-level
`DEFAULT_OPTIONS` constant. Checked every call site (`load-inventory-dialog.tsx`,
`use-saved-inventories.ts`) — the `options` object is only destructured for `enabled` and
never flows into a dependency array, so the "new object every render" never triggers the
infinite-loop pattern `CLAUDE.md` warns about. Fix opportunistically if the file is
already open for another reason; not worth a dedicated change.

### 3. Custom hooks don't memoize their returned object
**Verdict: mostly harmless; one real instance found and fixed.**
- `useSavedInventories()` — **fixed 2026-08-21.** Its unmemoized return (`saved`) was a
  dependency of six `useCallback`s and a prop (`saved={saved}`) in
  `inventory/components/device-selector.tsx`, so every render defeated all of that
  downstream memoization. Fixed by wrapping the internal async functions in `useCallback`
  (depending on the stable `mutateAsync` references, not the mutation objects) and the
  final return in `useMemo`.
- `useToast()` — unmemoized return, but safe: `toast`/`dismiss` are individually
  `useCallback`-wrapped, so code that destructures `{ toast }` still gets a stable
  function. No known consumer depends on the whole toast object's identity.
- `useConditionTree`, `useTemplateEditorDevice`, `useDashboardLayoutMutations`,
  `useNautobotSourceCredentials` — unmemoized, but no consumer was found feeding the
  whole returned object into a `useEffect`/`useMemo`/`useCallback` dependency array or a
  `React.memo` prop. Treat as low-priority "fix when touching the file" debt, not an
  active bug.

**When re-checking this row:** grep for `= use<HookName>()` call sites and check whether
the destructured *whole object* (not just individual fields) ends up in a dependency
array or is passed as a prop to a memoized child. Only that pattern is worth fixing.

### 4. React Hook Form not used on step ConfigPanels / login
**Verdict: deliberate architecture choice, not a gap to close.** Workflow step
ConfigPanels (`workflow-steps/*/index.tsx`) write incremental updates directly into a
per-step JSON `config` blob via an `onChange` callback; the shape differs per plugin and
there's no submit/validate step — it's a live-bound canvas editor, not a submitted form.
Retrofitting RHF onto ~49 dynamically-shaped step panels for no functional gain is not
recommended. Settings dialogs, credential/user dialogs, and workflow save-as / manage /
import / run-inputs / schedule dialogs already use RHF + Zod correctly — that's the right
scope for the rule. Recommend eventually writing this exception into `CLAUDE.md` itself
(RHF for dialogs/settings forms, plain controlled state for step ConfigPanels) instead of
carrying it as an open item.

### 5. Server Components ratio (`'use client'` on most feature files)
**Verdict: not actually a violation.** The scorecard row itself already says
"Partial / expected." Root layout, the dashboard auth layout, and all route stubs are
Server Components; the client-heavy feature tree is expected for an interactive,
canvas-driven dashboard. Don't re-flag file counts here as a compliance gap.

## Adjacent "Mostly pass" rows — same treatment

These aren't literally `Partial` but tend to get re-flagged for the same reason; treat
them the same way:

- **Shadcn for all primitives** — **fixed 2026-08-21.** The one custom overlay modal in
  `workflow-steps/get-nautobot-devices/preview-dialog.tsx` (no Escape key, no focus trap,
  no Portal) was swapped to Shadcn `Dialog`, matching the parallel ISE preview dialog.
  This was the one item in this list with genuine user-facing impact (keyboard/focus
  accessibility), not just a style nit — worth remembering as the exception to the "these
  are all fine to leave" rule if a similar custom-overlay pattern shows up elsewhere.
- **Tailwind semantic tokens** — inventory condition tree and step-category chips use
  palette colors (`purple-*`, `indigo-*`, `sky-*`) intentionally as category color-coding,
  not as a second UI kit. Accepted visual language, not a token-system violation.
- **TanStack Query for server data** — the remaining non-`useQuery` calls are
  event-handler `apiCall`s (load-workflow, load-inventory, execute-commands), not
  `useEffect` fetches. Lower-impact than the original finding; wrap in `useMutation`
  opportunistically, don't treat as newly discovered `useState`+`useEffect` violations.

## Not "Partial" — tracked separately, don't re-litigate as code defects

- **Device-first product flow (`Gap`)** — product-direction decision (inventory is a
  standalone builder; device targeting is a workflow step), not a code defect.
- **Tests / `BEST_PRACTICES.md` (`Fail`)** — known, tracked gap. Only 4 Vitest files exist
  today. Not something a single analysis pass should try to fix inline.

## Security findings (`doc/analysis/FRONTEND.md` §5) — verdicts

Same rule as above: check here before re-flagging a §5 finding as new.

### High / Medium — fixed as of 2026-08-21

- **§5.2 CSP `unsafe-inline`/`unsafe-eval`** — `middleware.ts` now issues a per-request
  nonce and sets `script-src 'self' 'nonce-<n>' 'strict-dynamic'` in production;
  `'unsafe-eval'` is appended only when `NODE_ENV !== "production"` (React dev-mode
  needs it, production doesn't). `next.config.ts` no longer sets CSP at all — it moved to
  middleware on purpose (static headers can't carry a per-request nonce). Don't flag the
  absence of CSP in `next.config.ts` as a regression; check `middleware.ts` instead.
- **§5.4 `ENABLE_DEV_TOOLS` is env, not `NODE_ENV`** — `lib/dev-tools.ts`'s
  `isDevToolsEnabled()` now requires `NODE_ENV !== "production"` **and** the flag. A
  production deployment that inherits a dev `.env` can no longer expose the OIDC test
  dashboard or the raw-JWT callback route.
- **§5.6 proxy forwards `Location`** — `api-proxy.ts`'s `STRIP_RESPONSE_HEADERS` now
  includes `"location"` alongside `"set-cookie"`. A backend 3xx can no longer be followed
  client-side via the browser's `redirect: "follow"` fetch.
- **§5.7 privileged admin tools reachable without a permission check** — `tools/add-certificate/layout.tsx`
  and `tools/database-migration/layout.tsx` now call
  `requirePermissionOr404("system.certificates" | "system.database", "write")` before
  rendering. The pages no longer rely solely on hidden buttons + backend 403.
- **§5.3 sensitive payloads in the React Query cache** — partially hardened, not fully
  closed: `useArtifactQuery` now uses `gcTime: 30 * 1000` (down from 5 min), and logout
  calls `queryClient.clear()`. Full mitigation (`gcTime: 0`, excluding credential/TACACS
  fields from the cache) is still optional hardening, not done. Don't re-flag the general
  finding, but it's fair to note the `gcTime: 0` option is still open if someone wants it.
- **§5.8 template editor can trigger live SSH** — already an explicit "Fetch configs"
  button/mutation, not a `useEffect` side effect. Confirmed still true; no action needed.
- **§5.5 CSRF relies on `SameSite=lax` only** — **not implemented**, and that's fine.
  No `__Host-` cookie prefix, no double-submit CSRF token. This was listed as "optional
  hardening" in the original finding, not a required fix — cross-site POSTs are already
  blocked by `SameSite=lax`, and the proxy's state-changing paths are gated by backend
  RBAC regardless. Don't treat its absence as an unaddressed Medium; it's an accepted,
  intentionally-skipped hardening option.

### Low — reviewed 2026-08-21, none require a fix

- **§5.9 OIDC `state` in `sessionStorage`** — standard SPA OAuth pattern; the alternative
  (server-side state before login) doesn't fit the BFF-cookie architecture. Already does
  the right thing (regex-validates `providerId` before use). Not actionable.
- **§5.10 permissions snapshot in Zustand can be stale ≤15 min** — UI-only convenience
  cache; every real action is still checked server-side (403 on stale/insufficient perms).
  Fixing would mean polling `/auth/me` more aggressively for a purely cosmetic nav-item
  delay. Not worth it.
- **§5.11 `verifySsl: false` not extra-gated in the UI** — confirmed still true across all
  five source dialogs (Git/Nautobot/ISE/Mattermost/pyATS): plain `Switch`, no warning copy
  when disabled. Legitimate but optional nicety (admin-only, per-source lab/self-signed
  cert setting behind `settings:write`). Fix opportunistically (a warning line under the
  switch) if a dialog is already open for another reason; not a dedicated task.
- **§5.12 dashboard visible to every authenticated user** — confirmed intentional
  (`canShow: () => true` in the sidebar) and backend-enforced via JWT-only routes. Product
  decision, not a gap.
- **§5.13 Hatchet `dashboard_url` rendered as `<a href>` with no scheme check** — traced to
  source: `dashboard_url` comes from the `HATCHET_DASHBOARD_URL` env var (or falls back to
  `server_url`) in `backend/services/hatchet/hatchet_settings_service.py` — it is **not** a
  user/admin-editable form field anywhere in the UI. Only someone with deployment-env
  control can set it, and they already have full infra control, so a `javascript:`-scheme
  self-XSS here isn't a realistic escalation. Not worth fixing.

**When re-checking §5:** the Low bucket only needs to be revisited if one of these facts
changes — e.g. if `dashboard_url` (§5.13) or a source's `verifySsl` (§5.11) ever becomes
settable by a lower-privileged role than today, or if the permissions snapshot (§5.10)
starts being used for something more sensitive than nav visibility.

## Maintenance

Update this file whenever a compliance scorecard row (§2) or a security finding (§5)
changes status (fixed, newly introduced, or verdict revised) so it stays the fast path
for "have we already decided this is fine?" before diving back into
`doc/analysis/FRONTEND.md`.
