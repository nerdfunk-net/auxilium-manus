# Frontend Refactoring Plan

**Source:** `doc/analysis/FRONTEND.md` — High and Medium findings only (§4, §5, plus the §6.1/§6.3 refactor
targets and §7 doc staleness that the analysis's own §9 "recommended order of work" ties to those findings).
**Verification:** Every finding below was re-read against the current tree on `refactoring/grok46` before being
included; line numbers are current as of 2026-08-20.
**Goal:** Implement this document top-to-bottom with no further codebase analysis.
**Out of scope:** Low/Informational findings (§4.2–§4.6, §5.9–§5.15), the product-direction "device-first shell"
redesign (§4.7 first bullet — that is a product decision, not a refactor), and the §6.2 "Priority 2" large-file
list (split those when each feature is next touched, per the analysis).

---

## How to implement

- Apply items **in the numbered order** (H-items first; M9–M11 depend on nothing else and can be reordered
  among themselves if convenient, but do them after H1–H3 and M1–M8).
- Do not change public API response shapes. Do not add a client-side GraphQL layer (§4.7 — the backend-proxied
  REST pattern is correct; only `CLAUDE.md` needs updating).
- Keep the proxy-only rule intact: nothing added here calls `BACKEND_URL` from client code.
- After each item that touches a query hook: verify the hook still uses `queryKeys` (never an inline array) and
  a `DEFAULT_OPTIONS` constant if it takes an options object.
- After each item: run `npm run lint` and `npx tsc --noEmit` from `frontend/`. Run `npx vitest run` after H1–H3
  and M1–M3 (the security-relevant items) at minimum.
- After the last item: grep for the patterns each item removes (see individual "Verify" lines) to confirm no
  second instance was missed.

---

## Work order

| ID | Severity | Item |
|----|----------|------|
| H1 | High | Nonce-based CSP — drop `'unsafe-inline'`/`'unsafe-eval'` from `script-src` |
| H2 | High | Clear the QueryClient cache on logout; short `gcTime` for artifact content |
| H3 | High | Gate `ENABLE_DEV_TOOLS` behind `NODE_ENV !== "production"` |
| M1 | Medium | Strip `Location` from proxied responses |
| M2 | Medium | Do not forward raw backend `detail` text into UI-facing errors |
| M3 | Medium | Server-side permission gate for `/tools/database-migration` and `/tools/add-certificate` |
| M4 | Medium | Template editor: turn automatic SSH `get-configs` into an explicit action |
| M5 | Medium | Template editor: move Nautobot attribute fetch onto `useQuery` |
| M6 | Medium | Netmiko device search: move onto `useQuery` |
| M7 | Medium | `use-template-render.ts`: `useState` → `useMutation` |
| M8 | Medium | `use-workflow-persistence.ts`: raw `apiCall` GET → `useQuery` |
| M9 | Medium | Extract shared `ContentSourcePicker` (collapses 6 duplicated pickers) |
| M10 | Medium | Extract shared `GitSourceSelectDialog` (collapses 2 duplicated dialogs) |
| M11 | Medium | Split `use-workflow-canvas.ts` (922 lines) into a facade over focused hooks |
| M12 | Medium | Fix `CLAUDE.md` staleness (Next version, port, GraphQL helper path) |

CSRF hardening (analysis §5.5) is intentionally **not** in this plan: the analysis itself frames it as optional
hardening on top of an already-safe `SameSite=lax` cookie, not a confirmed gap. Revisit only if the app is ever
served from a shared parent domain with other, less-trusted subdomains.

---

## H1 — Nonce-based CSP

**Files:** create `frontend/src/middleware.ts`; edit `frontend/next.config.ts`; edit
`frontend/src/app/layout.tsx` (or wherever Monaco is mounted, to read the nonce for its inline styles if needed).

### Why

`script-src 'self' 'unsafe-inline' 'unsafe-eval'` means any future HTML-injection bug becomes full script
execution. Monaco needs `'unsafe-eval'`-adjacent behavior for its web workers (already isolated via
`worker-src 'self' blob:'`), but the top-level document does not need inline/eval script execution — Next.js
supports per-request nonces for its own inline bootstrap scripts.

### Code before — `frontend/next.config.ts` (CSP header)

```1:32:frontend/next.config.ts
const securityHeaders: { key: string; value: string }[] = [
  {
    key: "Content-Security-Policy",
    value:
      "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; worker-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'",
  },
  ...
];
```

### Code after — `frontend/next.config.ts`

```ts
const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        headers: [
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          ...(process.env.NODE_ENV === "production"
            ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]
            : []),
        ],
        source: "/(.*)",
      },
    ];
  },
};

export default nextConfig;
```

The CSP header itself moves into `middleware.ts` because it needs a per-request nonce; `next.config.ts` headers
are static and cannot embed one.

### Code after — `frontend/src/middleware.ts` (new file)

```ts
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");

  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "worker-src 'self' blob:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
```

`'strict-dynamic'` + the nonce lets Next's own hydration scripts run (they're server-rendered with the nonce by
Next when `headers().get("x-nonce")` is read in the root layout — Next 16 auto-detects the `x-nonce` convention
via `next/headers`) while blocking any injected `<script>` that lacks the nonce. `style-src 'unsafe-inline'`
stays: Tailwind/Radix apply inline styles for positioning (popovers, dialogs) and a nonce on every one of those
is not practical; this is a materially smaller attack surface than script execution.

**Verify:** `grep -rn "unsafe-eval" frontend/next.config.ts frontend/src/middleware.ts` returns nothing. Load
the template editor (Monaco) and confirm it still renders — Monaco's web worker path only needed `worker-src
'self' blob:'`, which is unchanged.

---

## H2 — Clear QueryClient cache on logout; short `gcTime` for artifacts

**Files:** `frontend/src/lib/auth-store.ts`, `frontend/src/hooks/queries/use-artifact-query.ts`,
`frontend/src/components/layout/app-sidebar.tsx` (or wherever `QueryClientProvider` is reachable from the
logout call site).

### Why

`useArtifactQuery` caches full artifact `content` (device configs, rendered templates, TACACS keys via
`get-ise-tacacs-key`) for 5 minutes with the default `gcTime`. `logout()` in `auth-store.ts` only clears the
Zustand user and the httpOnly cookie — the React Query cache (device configs, run step results) survives in
memory. On a shared machine, the next person to open the app before a full page reload could still read stale
query results if any code re-renders from cache before the redirect completes.

### Code before — `frontend/src/hooks/queries/use-artifact-query.ts`

```ts
export function useArtifactQuery({
  runId,
  artifactRef,
  enabled = true,
}: UseArtifactQueryOptions) {
  const { apiCall } = useApi();
  const artifactId = artifactRef?.artifact_id ?? null;

  return useQuery({
    queryKey: queryKeys.workflowRuns.artifact(runId ?? 0, artifactId ?? ""),
    queryFn: () =>
      apiCall<ArtifactContentResponse>(`runs/${runId}/artifacts/${artifactId}`, {
        method: "GET",
      }),
    enabled: enabled && runId != null && artifactId != null,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}
```

### Code after

```ts
export function useArtifactQuery({
  runId,
  artifactRef,
  enabled = true,
}: UseArtifactQueryOptions) {
  const { apiCall } = useApi();
  const artifactId = artifactRef?.artifact_id ?? null;

  return useQuery({
    queryKey: queryKeys.workflowRuns.artifact(runId ?? 0, artifactId ?? ""),
    queryFn: () =>
      apiCall<ArtifactContentResponse>(`runs/${runId}/artifacts/${artifactId}`, {
        method: "GET",
      }),
    enabled: enabled && runId != null && artifactId != null,
    staleTime: 5 * 60 * 1000,
    // Artifact content (device configs, secrets pulled into device
    // attributes) should not linger in memory after the viewer navigates
    // away — drop the cache entry immediately once unused.
    gcTime: 30 * 1000,
    retry: false,
  });
}
```

### Code before — `frontend/src/lib/auth-store.ts` (logout)

```ts
interface AuthState {
  user: AuthUser | null;
  isLoading: boolean;
  error: string | null;
  loadCurrentUser: () => Promise<void>;
  login: (credentials: { username: string; password: string }) => Promise<void>;
  logout: () => Promise<void>;
  setUser: (user: AuthUser) => void;
}
```

### Code after — `frontend/src/lib/auth-store.ts`

```ts
import type { QueryClient } from "@tanstack/react-query";

interface AuthState {
  user: AuthUser | null;
  isLoading: boolean;
  error: string | null;
  loadCurrentUser: () => Promise<void>;
  login: (credentials: { username: string; password: string }) => Promise<void>;
  logout: (queryClient?: QueryClient) => Promise<void>;
  setUser: (user: AuthUser) => void;
}
```

Inside the `logout` implementation (after the existing `fetch("/api/auth/logout", ...)` call, or added if there
isn't one — check the current body before editing): add `queryClient?.clear();` as the last step, before
`set({ user: null })`.

### Code before — `frontend/src/components/layout/app-sidebar.tsx`

```ts
const handleLogout = useCallback(async () => {
  await logout();
  router.replace("/login");
  router.refresh();
}, [logout, router]);
```

### Code after

```ts
import { useQueryClient } from "@tanstack/react-query";

// inside AppSidebar():
const queryClient = useQueryClient();

const handleLogout = useCallback(async () => {
  await logout(queryClient);
  router.replace("/login");
  router.refresh();
}, [logout, queryClient, router]);
```

**Verify:** log in, open a run with an artifact, log out, log back in as a different session in the same tab
(or inspect via React Query Devtools) — the artifact query cache is empty until refetched.

---

## H3 — Gate `ENABLE_DEV_TOOLS` behind `NODE_ENV`

**Files:** `frontend/src/app/(dashboard)/tools/oidc-test/layout.tsx`,
`frontend/src/app/(auth)/login/oidc-test-callback/layout.tsx`, `frontend/src/app/(dashboard)/tools/page.tsx`.

### Why

If `ENABLE_DEV_TOOLS=true` is ever set in a production deployment (a plausible copy-paste-the-`.env` mistake —
`CLAUDE.md` lists it as a normal env var, not flagged as dev-only-enforced), three routes become reachable:
the OIDC test dashboard (renders `client_id`, discovery URLs, CA paths), a test-login flow with a
user-controlled `redirect_uri`, and `/login/oidc-test-callback` — which sits under the **unauthenticated**
`(auth)` route group and dumps the raw JWT (header/payload/signature) into the DOM via `JwtPanel`. This is the
same class of risk the backend analysis flags for the equivalent server-side flag; the frontend should not rely
on deployers setting the env var correctly.

### Code before — `frontend/src/app/(dashboard)/tools/oidc-test/layout.tsx`

```tsx
import { notFound } from "next/navigation";

export default function OidcTestLayout({ children }: { children: React.ReactNode }) {
  if (process.env.ENABLE_DEV_TOOLS !== "true") notFound();
  return children;
}
```

### Code after

```tsx
import { notFound } from "next/navigation";

import { isDevToolsEnabled } from "@/lib/dev-tools";

export default function OidcTestLayout({ children }: { children: React.ReactNode }) {
  if (!isDevToolsEnabled()) notFound();
  return children;
}
```

### Code after — `frontend/src/lib/dev-tools.ts` (new file)

```ts
/**
 * ENABLE_DEV_TOOLS alone is not enough to expose the OIDC test dashboard and
 * its raw-JWT callback route: a production deployment that inherits a dev
 * .env file would otherwise leak client_id/discovery URLs and render access
 * tokens in the DOM to any authenticated (or, for the callback, unauthenticated)
 * visitor. Require NODE_ENV !== "production" in addition to the flag.
 */
export function isDevToolsEnabled(): boolean {
  return process.env.NODE_ENV !== "production" && process.env.ENABLE_DEV_TOOLS === "true";
}
```

Apply the same `isDevToolsEnabled()` swap to:

- `frontend/src/app/(auth)/login/oidc-test-callback/layout.tsx` (same `notFound()` shape)
- `frontend/src/app/(dashboard)/tools/page.tsx` — replace
  `oidcTestEnabled={process.env.ENABLE_DEV_TOOLS === "true"}` with
  `oidcTestEnabled={isDevToolsEnabled()}`

**Verify:** `grep -rn 'ENABLE_DEV_TOOLS' frontend/src` shows every call site going through `isDevToolsEnabled()`
except the definition itself. With `NODE_ENV=production ENABLE_DEV_TOOLS=true`, all three routes 404.

---

## M1 — Strip `Location` from proxied responses

**Files:** `frontend/src/lib/api-proxy.ts`.

### Why

`redirect: "manual"` on the server-side `fetch` to the backend stops that fetch from *following* a redirect,
but `copyResponseHeaders` still copies `Location` through to the browser response. `useApi.apiCall` uses the
browser's default `fetch` (`redirect: "follow"`), so a backend route that ever returns a 3xx with an
attacker-influenced `Location` would be followed client-side. No such backend route exists today, but the proxy
should not depend on that staying true.

### Code before — `frontend/src/lib/api-proxy.ts`

```ts
const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);
const STRIP_REQUEST_HEADERS = new Set(["authorization", "cookie"]);
const STRIP_RESPONSE_HEADERS = new Set(["set-cookie"]);
```

### Code after

```ts
const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);
const STRIP_REQUEST_HEADERS = new Set(["authorization", "cookie"]);
// "location" is stripped because the server-side fetch to the backend uses
// redirect: "manual" (so *we* don't follow it), but useApi's browser fetch
// uses the default redirect: "follow" — forwarding Location would let a
// future backend 3xx be followed client-side with no proxy-side review.
const STRIP_RESPONSE_HEADERS = new Set(["set-cookie", "location"]);
```

No other change is needed — `copyResponseHeaders` already iterates `STRIP_RESPONSE_HEADERS` generically.

**Verify:** `grep -n "STRIP_RESPONSE_HEADERS" frontend/src/lib/api-proxy.ts` shows `"location"` in the set.
Existing test `frontend/src/lib/api-proxy.test.ts` should still pass; add a case asserting a `Location` header
on the mocked backend response does not appear on the `NextResponse`.

---

## M2 — Do not forward raw backend `detail` text into UI-facing errors

**Files:** `frontend/src/hooks/use-api.ts`.

### Why

`apiCall` copies `body.detail` verbatim into the `Error` it throws for every non-401/403 failure, and callers
put that message straight into a toast. 401/403 are already generic. Everything else — 400/404/409/422/5xx —
is shown to the user as-is. Most of these are legitimate validation messages the user should see (e.g. "source
name already exists"), but a small number of backend error paths are known to include internal detail (path
fragments, upstream connection errors) that `core/safe_http_errors.py` intentionally keeps out of 5xx bodies
server-side — the same discipline should extend to how the frontend *displays* whatever detail does arrive,
by capping length and only showing structured `{message}`-shaped bodies verbatim.

### Code before — `frontend/src/hooks/use-api.ts`

```ts
if (!response.ok) {
  let message = `API request failed with status ${response.status}`;
  try {
    const body = (await response.json()) as {
      detail?: string | { message?: string };
    };
    if (typeof body.detail === "string") {
      message = body.detail;
    } else if (
      body.detail &&
      typeof body.detail === "object" &&
      "message" in body.detail &&
      typeof body.detail.message === "string"
    ) {
      message = body.detail.message;
    }
  } catch {
    // use default message
  }
  throw new Error(message);
}
```

### Code after

```ts
const MAX_ERROR_MESSAGE_LENGTH = 300;

if (!response.ok) {
  let message = `API request failed with status ${response.status}`;
  try {
    const body = (await response.json()) as {
      detail?: string | { message?: string };
    };
    if (typeof body.detail === "string") {
      message = body.detail;
    } else if (
      body.detail &&
      typeof body.detail === "object" &&
      "message" in body.detail &&
      typeof body.detail.message === "string"
    ) {
      message = body.detail.message;
    }
  } catch {
    // use default message
  }
  // 5xx detail is already sanitized server-side (core.safe_http_errors), but
  // cap length defensively so a future regression can't dump a stack trace
  // or long upstream error into a toast.
  if (response.status >= 500 && message.length > MAX_ERROR_MESSAGE_LENGTH) {
    message = `Server error (status ${response.status}). Check the logs for details.`;
  }
  throw new Error(message);
}
```

4xx bodies are left untouched — those are the legitimate validation-message path (`CLAUDE.md`'s "user-friendly
error messages in UI-facing code") and the backend's `safe_http_errors` module only sanitizes 5xx.

**Verify:** trigger a 5xx from a proxied route in dev (e.g. stop the backend mid-request) and confirm the toast
shows the generic message, not a raw exception string, if one were ever returned.

---

## M3 — Server-side permission gate for privileged tools

**Files:** create `frontend/src/app/(dashboard)/tools/database-migration/layout.tsx` and
`frontend/src/app/(dashboard)/tools/add-certificate/layout.tsx`.

### Why

`(dashboard)/layout.tsx` already gates the whole dashboard on "logged in", but nothing gates these two routes
on the specific permission their pages require (`system.database:write` / `system.rbac:write` for migration,
`system.certificates:write` for certificates). The pages only use `hasPermission()` to hide buttons — that's
UX-only per `lib/permissions.ts`'s own comment — but `useSchemaStatusQuery` / `useCertificatesQuery` still fire
on mount for any authenticated user who navigates to the URL directly, and the backend correctly 403s but the
page itself renders schema/certificate status metadata before that 403 surfaces. Route-level gating avoids
issuing the request at all for users who can't act on the result, matching the pattern `(dashboard)/layout.tsx`
already established (server-side check via `proxyRequest` to `/api/auth/me`).

### Code before

No `layout.tsx` exists under `app/(dashboard)/tools/database-migration/` or `app/(dashboard)/tools/add-certificate/`
— only `page.tsx` re-exporting the feature page.

### Code after — `frontend/src/lib/require-permission.ts` (new file, shared by both layouts)

```ts
import { cookies } from "next/headers";
import { notFound } from "next/navigation";

import { proxyRequest } from "@/lib/api-proxy";
import { AUTH_COOKIE_NAME } from "@/lib/auth";
import type { AuthUser } from "@/lib/auth";

/**
 * Server-side companion to lib/permissions.ts's hasPermission — used only to
 * avoid rendering (and firing status queries for) admin-only tool pages for
 * users who lack the permission. The backend remains the real enforcement
 * point; this is defense in depth, not a new security boundary.
 */
export async function requirePermissionOr404(resource: string, action: string): Promise<void> {
  const cookieStore = await cookies();
  const token = cookieStore.get(AUTH_COOKIE_NAME)?.value;

  const userResponse = await proxyRequest({
    authorization: token ? `Bearer ${token}` : undefined,
    path: ["api", "auth", "me"],
    request: new Request("http://next.internal/api/proxy/api/auth/me"),
  });

  if (!userResponse.ok) {
    notFound();
  }

  const payload = (await userResponse.json()) as { user: AuthUser };
  if (!payload.user.permissions.includes(`${resource}:${action}`)) {
    notFound();
  }
}
```

### Code after — `frontend/src/app/(dashboard)/tools/database-migration/layout.tsx` (new file)

```tsx
import { requirePermissionOr404 } from "@/lib/require-permission";

export default async function DatabaseMigrationLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await requirePermissionOr404("system.database", "write");
  return children;
}
```

### Code after — `frontend/src/app/(dashboard)/tools/add-certificate/layout.tsx` (new file)

```tsx
import { requirePermissionOr404 } from "@/lib/require-permission";

export default async function AddCertificateLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await requirePermissionOr404("system.certificates", "write");
  return children;
}
```

`notFound()` (not a redirect) matches the existing `oidc-test` layout convention and avoids confirming to an
unauthorized-but-logged-in user that the route exists.

**Verify:** as a user without `system.database:write`, navigate directly to `/tools/database-migration` — Next
renders the 404 page and `useSchemaStatusQuery`'s network call never fires (check the Network tab). Tools index
card visibility (`hasPermission` in `tools-page.tsx`) is unchanged.

---

## M4 — Template editor: explicit action instead of automatic SSH

**Files:** `frontend/src/components/features/templates/template-editor-page.tsx`.

### Why

Selecting a test device + SSH credential with "Get Configs" enabled fires `POST netmiko/get-configs` from a
`useEffect` the moment both values are set — no confirmation step. The backend's `ALLOW_NETMIKO_ARBITRARY_HOSTS`
gate is the real control, but a live SSH connection is a powerful, observable action (it will show up in device
logs / trigger any connection alerting) and should require an explicit click, matching how every other
SSH-triggering step in the app (`get-device-configs`, etc.) is invoked from a workflow run rather than a form
`onChange`.

### Code before — `frontend/src/components/features/templates/template-editor-page.tsx` (~224–286)

```tsx
useEffect(() => {
  if (!getDeviceConfigs || !selectedDevice || credentialId === "none") {
    lastConfigsKeyRef.current = null;
    setParsedConfig(null);
    return;
  }

  const fetchKey = `${selectedDevice.id}|${credentialId}`;
  if (lastConfigsKeyRef.current === fetchKey) {
    return;
  }
  lastConfigsKeyRef.current = fetchKey;

  const host = bareIp(selectedDevice.primary_ip4) ?? selectedDevice.name ?? "";

  let active = true;
  setIsFetchingConfigs(true);
  apiCall<GetConfigsResponse>("netmiko/get-configs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      host,
      platform: selectedDevice.platform,
      network_driver: selectedDevice.network_driver,
      credential_id: Number(credentialId),
    }),
  })
    .then((response) => { /* ... */ })
    .catch((error) => { /* ... */ })
    .finally(() => {
      if (active) {
        setIsFetchingConfigs(false);
      }
    });

  return () => {
    active = false;
  };
}, [getDeviceConfigs, selectedDevice, credentialId, apiCall, toast, setParsedConfig]);
```

### Code after

```tsx
// Reset the parsed preview whenever the inputs that would invalidate it
// change — but do NOT auto-fetch. Fetching live device config over SSH is
// an explicit action (see fetchDeviceConfigs / the "Fetch configs" button).
useEffect(() => {
  if (!getDeviceConfigs || !selectedDevice || credentialId === "none") {
    lastConfigsKeyRef.current = null;
    setParsedConfig(null);
  }
}, [getDeviceConfigs, selectedDevice, credentialId]);

const fetchDeviceConfigsMutation = useMutation({
  mutationFn: async () => {
    if (!selectedDevice || credentialId === "none") {
      throw new Error("Select a device and credential first");
    }
    const host = bareIp(selectedDevice.primary_ip4) ?? selectedDevice.name ?? "";
    return apiCall<GetConfigsResponse>("netmiko/get-configs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        host,
        platform: selectedDevice.platform,
        network_driver: selectedDevice.network_driver,
        credential_id: Number(credentialId),
      }),
    });
  },
  onSuccess: (response) => {
    if (!response.success) {
      toast({
        title: "Get Configs failed",
        description: response.error ?? "Unknown error",
        variant: "destructive",
      });
      setParsedConfig(null);
      return;
    }
    setParsedConfig(response.parsed);
  },
  onError: (error) => {
    toast({
      title: "Get Configs failed",
      description: error instanceof Error ? error.message : "Unknown error",
      variant: "destructive",
    });
    setParsedConfig(null);
  },
});
```

Wire the existing "Get Configs" toggle to a `<Button onClick={() => fetchDeviceConfigsMutation.mutate()}
disabled={!selectedDevice || credentialId === "none" || fetchDeviceConfigsMutation.isPending}>` in the panel
JSX (replace whatever currently reads `isFetchingConfigs` with `fetchDeviceConfigsMutation.isPending`, and
delete the now-unused `isFetchingConfigs` state and `lastConfigsKeyRef` dedupe — the mutation is only invoked
by a click, so there's nothing to dedupe).

**Verify:** toggling "Get Configs" and picking a device no longer triggers a network request; a visible
"Fetch configs" button does, and it's disabled while pending.

---

## M5 — Template editor: Nautobot attribute fetch onto `useQuery`

**Files:** `frontend/src/components/features/templates/template-editor-page.tsx`,
`frontend/src/lib/query-keys.ts`, new `frontend/src/hooks/queries/use-device-attributes-query.ts`.

### Why

Same standards violation as M4 but read-only (no side effect beyond a GraphQL read), so the fix is a
straightforward hook extraction rather than a UX change: `CLAUDE.md` requires `useQuery`/`useMutation` for all
server data, not `useEffect` + `apiCall`.

### Code before — `frontend/src/components/features/templates/template-editor-page.tsx` (~171–219)

```tsx
useEffect(() => {
  // ... guards ...
  const fetchKey = `${selectedDevice.id}|${attributesKey}`;
  // ... dedupe against a ref ...
  apiCall<Record<string, unknown>>("sources/nautobot/devices/attributes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      device_id: selectedDevice.id,
      list_of_attributes: attributes,
    }),
  })
    .then(/* setDeviceAttributes */)
    .catch(/* toast */);
}, [
  selectedDevice,
  attributes,
  attributesKey,
  apiCall,
  /* ... */
]);
```

### Code after — `frontend/src/hooks/queries/use-device-attributes-query.ts` (new file)

```ts
"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

interface UseDeviceAttributesQueryOptions {
  deviceId: string | null;
  attributes: string[];
  enabled?: boolean;
}

export function useDeviceAttributesQuery({
  deviceId,
  attributes,
  enabled = true,
}: UseDeviceAttributesQueryOptions) {
  const { apiCall } = useApi();
  const attributesKey = [...attributes].sort().join(",");

  return useQuery({
    queryKey: queryKeys.templates.deviceAttributes(deviceId ?? "", attributesKey),
    queryFn: () =>
      apiCall<Record<string, unknown>>("sources/nautobot/devices/attributes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id: deviceId, list_of_attributes: attributes }),
      }),
    enabled: enabled && deviceId != null && attributes.length > 0,
    staleTime: 30 * 1000,
  });
}
```

Add `deviceAttributes: (deviceId: string, attributesKey: string) => [...queryKeys.templates.all, "device-attributes", deviceId, attributesKey] as const`
to the `templates` branch of `queryKeys` in `lib/query-keys.ts`.

### Code after — `template-editor-page.tsx`

```tsx
const {
  data: deviceAttributes,
  isFetching: isFetchingAttributes,
  error: attributesError,
} = useDeviceAttributesQuery({
  deviceId: selectedDevice?.id ?? null,
  attributes,
});

useEffect(() => {
  if (attributesError) {
    toast({
      title: "Failed to load attributes",
      description: attributesError instanceof Error ? attributesError.message : "Unknown error",
      variant: "destructive",
    });
  }
}, [attributesError, toast]);
```

Delete the old `useEffect`, its dedupe ref, and the manual `setDeviceAttributes`/`isFetchingAttributes` state —
`useQuery` owns caching, dedupe (by `queryKey`), and loading state now.

**Verify:** switching devices refetches attributes exactly once per `(deviceId, attributesKey)` pair (confirm
via React Query Devtools — no duplicate network calls when re-rendering with the same inputs).

---

## M6 — Netmiko device search onto `useQuery`

**Files:** `frontend/src/components/features/templates/components/netmiko-options-panel.tsx`,
new `frontend/src/hooks/queries/use-netmiko-device-search-query.ts`.

### Why

Same pattern as M5: a debounced `useEffect` + `apiCall` for `sources/nautobot/devices/search`, duplicating
what `useQuery` already does natively (`enabled` + `staleTime` replace the manual debounce timer + `active`
flag).

### Code before — `netmiko-options-panel.tsx` (~84–133)

```tsx
useEffect(() => {
  if (searchTerm.trim().length < 3 || !sourceReady) {
    setDevices([]);
    return;
  }
  const timeout = setTimeout(async () => {
    setIsSearching(true);
    try {
      const response = await apiCall<{ devices: DeviceSummary[] }>(
        "sources/nautobot/devices/search",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_id: sourceId, search: searchTerm.trim() }),
        },
      );
      setDevices(response.devices);
    } catch {
      setDevices([]);
    } finally {
      setIsSearching(false);
    }
  }, 300);
  return () => clearTimeout(timeout);
}, [searchTerm, sourceReady, sourceId, apiCall]);
```

### Code after — `frontend/src/hooks/queries/use-netmiko-device-search-query.ts` (new file)

```ts
"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";
import type { DeviceSummary } from "../types"; // adjust to the real shared type location

interface UseNetmikoDeviceSearchQueryOptions {
  sourceId: string;
  searchTerm: string;
  enabled: boolean;
}

export function useNetmikoDeviceSearchQuery({
  sourceId,
  searchTerm,
  enabled,
}: UseNetmikoDeviceSearchQueryOptions) {
  const { apiCall } = useApi();
  const [debouncedTerm, setDebouncedTerm] = useState(searchTerm);

  useEffect(() => {
    const timeout = setTimeout(() => setDebouncedTerm(searchTerm), 300);
    return () => clearTimeout(timeout);
  }, [searchTerm]);

  return useQuery({
    queryKey: queryKeys.sources.deviceSearch(sourceId, debouncedTerm.trim()),
    queryFn: () =>
      apiCall<{ devices: DeviceSummary[] }>("sources/nautobot/devices/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_id: sourceId, search: debouncedTerm.trim() }),
      }),
    enabled: enabled && debouncedTerm.trim().length >= 3,
    staleTime: 30 * 1000,
  });
}
```

Add `deviceSearch: (sourceId: string, term: string) => [...queryKeys.sources.all, "device-search", sourceId, term] as const`
to `queryKeys.sources` in `lib/query-keys.ts`.

### Code after — `netmiko-options-panel.tsx`

```tsx
const { data, isFetching: isSearching } = useNetmikoDeviceSearchQuery({
  sourceId,
  searchTerm,
  enabled: sourceReady,
});
const devices = data?.devices ?? EMPTY_DEVICES;
```

(`EMPTY_DEVICES` — a module-level `const EMPTY_DEVICES: DeviceSummary[] = []` — avoids the "inline array
literal default" anti-pattern from `CLAUDE.md`.)

**Verify:** typing in the search box still debounces (no request per keystroke); the 300ms debounce now lives
in the hook, not the component.

---

## M7 — `use-template-render.ts`: `useState` → `useMutation`

**Files:** `frontend/src/components/features/templates/hooks/use-template-render.ts` (or wherever it
currently lives).

### Code before

```ts
export function useTemplateRender() {
  const { apiCall } = useApi();
  const { toast } = useToast();
  const [isRendering, setIsRendering] = useState(false);
  const [result, setResult] = useState<TemplateRenderResponse | null>(null);
  const [showDialog, setShowDialog] = useState(false);

  const render = useCallback(
    async (content: string, variables: EditorVariable[]) => {
      setIsRendering(true);
      try {
        const response = await apiCall<TemplateRenderResponse>("templates/render", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            template_content: content,
            variables: buildVariablesContext(variables),
          }),
        });
        setResult(response);
        setShowDialog(true);
      } catch (error) {
        toast({
          title: "Render failed",
          description: error instanceof Error ? error.message : "Unknown error",
          variant: "destructive",
        });
      } finally {
        setIsRendering(false);
      }
    },
    [apiCall, toast],
  );

  return useMemo(
    () => ({ render, isRendering, result, showDialog, setShowDialog }),
    [render, isRendering, result, showDialog],
  );
}
```

### Code after

```ts
export function useTemplateRender() {
  const { apiCall } = useApi();
  const { toast } = useToast();
  const [showDialog, setShowDialog] = useState(false);

  const renderMutation = useMutation({
    mutationFn: (input: { content: string; variables: EditorVariable[] }) =>
      apiCall<TemplateRenderResponse>("templates/render", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template_content: input.content,
          variables: buildVariablesContext(input.variables),
        }),
      }),
    onSuccess: () => setShowDialog(true),
    onError: (error) => {
      toast({
        title: "Render failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    },
  });

  const render = useCallback(
    (content: string, variables: EditorVariable[]) => {
      renderMutation.mutate({ content, variables });
    },
    [renderMutation],
  );

  return useMemo(
    () => ({
      render,
      isRendering: renderMutation.isPending,
      result: renderMutation.data ?? null,
      showDialog,
      setShowDialog,
    }),
    [render, renderMutation.isPending, renderMutation.data, showDialog],
  );
}
```

Template rendering has no side effects on the backend worth caching, so a bare `useMutation` (no
`invalidateQueries`) is correct — this is purely about routing the call through the QueryClient for consistent
loading/error state, not about cache semantics.

**Verify:** render dialog still opens with the rendered content; render failures still toast.

---

## M8 — `use-workflow-persistence.ts`: raw GET → `useQuery`

**Files:** `frontend/src/components/features/workflows/hooks/use-workflow-persistence.ts`.

### Why

Create/update already go through `useWorkflowMutations` (TanStack). The initial load-by-id
(`apiCall<WorkflowResponse>('workflows/${mountWorkflowId}')` inside a `useEffect`) is the one remaining raw
fetch in this file, and it's the entry point for every existing workflow the canvas opens.

### Code before — `use-workflow-persistence.ts` (~74–99)

```ts
const { apiCall } = useApi();
// ...
useEffect(() => {
  if (!mountWorkflowId) {
    return;
  }
  apiCall<WorkflowResponse>(`workflows/${mountWorkflowId}`)
    .then((workflow) => {
      applyLoadedCanvas(/* derived from workflow */);
    })
    .catch((error) => {
      markError(error instanceof Error ? error.message : "Failed to load workflow");
    });
}, [
  mountWorkflowId,
  apiCall,
  applyLoadedCanvas,
  markError,
  /* ... */
]);
```

### Code after

```ts
const workflowQuery = useQuery({
  queryKey: queryKeys.workflows.detail(mountWorkflowId ?? ""),
  queryFn: () => apiCall<WorkflowResponse>(`workflows/${mountWorkflowId}`),
  enabled: mountWorkflowId != null,
  staleTime: 0, // canvas load must always reflect the latest saved definition
  retry: false,
});

useEffect(() => {
  if (workflowQuery.data) {
    applyLoadedCanvas(/* derived from workflowQuery.data, same mapping as before */);
  }
}, [workflowQuery.data, applyLoadedCanvas]);

useEffect(() => {
  if (workflowQuery.error) {
    markError(
      workflowQuery.error instanceof Error
        ? workflowQuery.error.message
        : "Failed to load workflow",
    );
  }
}, [workflowQuery.error, markError]);
```

Check `lib/query-keys.ts` — `queryKeys.workflows.detail` already exists for the mutation-side invalidation, so
no new key is needed here.

**Verify:** opening an existing workflow still populates the canvas; opening a nonexistent `workflowId` still
surfaces the same error path via `markError`.

---

## M9 — Extract shared `ContentSourcePicker`

**Files:** new `frontend/src/components/features/workflow-steps/shared/content-source-picker.tsx` and
`frontend/src/components/features/workflow-steps/shared/content-source-options.ts`; edit
`store-artifact/index.tsx`, `compare-data/index.tsx`, `upload-config/index.tsx`, `filter-output/index.tsx`,
`merge-content/index.tsx`, `route-on-content/index.tsx` (and their `*-config.ts` companions where the option
list is re-declared).

### Why

`CONTENT_SOURCE_OPTIONS` (11 entries: `upstream_output`, `running_config`, `startup_config`, `command_output`,
`latest_command_output`, `rendered_template`, `merged_content`, `comparison_diff`, `filtered_output`,
`pyats_snapshot`, `updated_content`) is copy-pasted verbatim in `store-artifact/index.tsx` and
`compare-data/index.tsx` (confirmed identical `value`/`label` pairs), and the analysis found the same shape in
four more step packages. A single source-of-truth module removes six maintenance sites for one concept and
shrinks `store-artifact/index.tsx` (770 lines) and `compare-data/index.tsx` (695 lines) meaningfully.

### Code before — `workflow-steps/store-artifact/index.tsx` (~31–89, and duplicated near-verbatim in
`workflow-steps/compare-data/index.tsx` ~31–90)

```tsx
const CONTENT_SOURCE_OPTIONS = [
  { value: "upstream_output", label: "Upstream output (auto-detected)", hint: "..." },
  { value: "running_config", label: "Running configuration", hint: "..." },
  { value: "startup_config", label: "Startup configuration", hint: "..." },
  { value: "command_output", label: "Command output (specific step)", hint: "..." },
  { value: "latest_command_output", label: "Latest command output", hint: "..." },
  { value: "rendered_template", label: "Rendered template", hint: "..." },
  { value: "merged_content", label: "Merged content", hint: "..." },
  { value: "comparison_diff", label: "Comparison diff", hint: "..." },
  { value: "filtered_output", label: "Filtered output", hint: "..." },
  { value: "pyats_snapshot", label: "pyATS snapshot", hint: "..." },
  { value: "updated_content", label: "Updated content", hint: "..." },
] as const;

type ContentSource = (typeof CONTENT_SOURCE_OPTIONS)[number]["value"];

// ...later, in the JSX...
<Select value={contentSource} onValueChange={handleContentSourceChange}>
  <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
  <SelectContent>
    {CONTENT_SOURCE_OPTIONS.map((option) => (
      <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
    ))}
  </SelectContent>
</Select>
```

### Code after — `workflow-steps/shared/content-source-options.ts` (new file)

```ts
export const CONTENT_SOURCE_OPTIONS = [
  { value: "upstream_output", label: "Upstream output (auto-detected)", hint: "Automatically resolved from the nearest content-producing upstream step." },
  { value: "running_config", label: "Running configuration", hint: "Requires an upstream get-device-configs (or similar) step." },
  { value: "startup_config", label: "Startup configuration", hint: "Requires startup config on the device context." },
  { value: "command_output", label: "Command output (specific step)", hint: "Choose the run-command step that produced the output." },
  { value: "latest_command_output", label: "Latest command output", hint: "Uses the most recent command result on the device." },
  { value: "rendered_template", label: "Rendered template", hint: "Choose the render-jinja-template step that produced the template." },
  { value: "merged_content", label: "Merged content", hint: "Choose the merge-content step that combined multiple command outputs." },
  { value: "comparison_diff", label: "Comparison diff", hint: "Choose the compare-data step that produced a unified diff on mismatch." },
  { value: "filtered_output", label: "Filtered output", hint: "Choose the filter-output step that removed volatile fields." },
  { value: "pyats_snapshot", label: "pyATS snapshot", hint: "Choose the get-pyats-snapshot step that produced the snapshot." },
  { value: "updated_content", label: "Updated content", hint: "Choose the update-content step that produced the edited config." },
] as const;

export type ContentSource = (typeof CONTENT_SOURCE_OPTIONS)[number]["value"];
```

Before deleting each step's local copy, diff it against this list — `compare-data`'s array must be checked
value-for-value (confirmed identical for the two verified above); if any of the other four packages restricts
the list to a subset, export a filtered constant (e.g. `FILTER_OUTPUT_SOURCE_OPTIONS`) from the same shared
file rather than forcing every step to accept all 11 options.

### Code after — `workflow-steps/shared/content-source-picker.tsx` (new file)

```tsx
"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import { CONTENT_SOURCE_OPTIONS, type ContentSource } from "./content-source-options";

interface ContentSourcePickerProps {
  value: ContentSource;
  onChange: (value: ContentSource) => void;
  options?: readonly (typeof CONTENT_SOURCE_OPTIONS)[number][];
}

export function ContentSourcePicker({
  value,
  onChange,
  options = CONTENT_SOURCE_OPTIONS,
}: ContentSourcePickerProps) {
  return (
    <Select value={value} onValueChange={(next) => onChange(next as ContentSource)}>
      <SelectTrigger className="h-8 text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
```

### Code after — `workflow-steps/store-artifact/index.tsx`

```tsx
import { ContentSourcePicker } from "@/components/features/workflow-steps/shared/content-source-picker";
import type { ContentSource } from "@/components/features/workflow-steps/shared/content-source-options";

// delete the local CONTENT_SOURCE_OPTIONS array and `type ContentSource = ...` line

// ...in the JSX...
<ContentSourcePicker value={contentSource} onChange={handleContentSourceChange} />
```

Repeat for `compare-data`, `upload-config`, `filter-output`, `merge-content`, `route-on-content`.

**Verify:** `grep -rn "CONTENT_SOURCE_OPTIONS = \[" frontend/src/components/features/workflow-steps` returns
exactly one match (the shared file). Each step's `hint` text under the dropdown still matches what it showed
before the extraction.

---

## M10 — Extract shared `GitSourceSelectDialog`

**Files:** new `frontend/src/components/features/workflow-steps/shared/git-source-select-dialog.tsx`; delete
`workflow-steps/get-git-devices/git-source-select-dialog.tsx` and
`workflow-steps/set-default-attributes/git-source-select-dialog.tsx`; update both steps' imports.

### Why

The two files are 140 and 128 lines with only cosmetic differences confirmed by diff: element `id` strings
(`git-source-select` vs `set-default-attributes-git-source-select`), one sentence of helper copy, and whether a
"reference this ID" hint paragraph is shown. Neither difference is load-bearing — both dialogs let the user
pick a configured Git source and return its `sourceId`.

### Code before — two near-identical files

```tsx
// workflow-steps/get-git-devices/git-source-select-dialog.tsx (140 lines)
export function GitSourceSelectDialog({ /* ... */ }) {
  // ...
  <Label htmlFor="git-source-select">Source ID</Label>
  <SelectTrigger id="git-source-select">
  // ...
  <p className="text-[11px] text-muted-foreground">
    Reference this ID when wiring sources in workflow steps (e.g. ...)
  </p>
}

// workflow-steps/set-default-attributes/git-source-select-dialog.tsx (128 lines)
export function GitSourceSelectDialog({ /* ... */ }) {
  // ...
  <Label htmlFor="set-default-attributes-git-source-select">Source ID</Label>
  <SelectTrigger id="set-default-attributes-git-source-select">
  // (no "reference this ID" paragraph)
}
```

### Code after — `workflow-steps/shared/git-source-select-dialog.tsx` (new file, merges both)

```tsx
"use client";

// ... same imports as the two originals ...

interface GitSourceSelectDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sourceId: string;
  onSourceIdChange: (id: string) => void;
  onConfirm: () => void;
  /** Distinct DOM id so two instances on the same page (unlikely, but both
   * steps can appear on one canvas) don't collide. */
  idPrefix: string;
  /** Only get-git-devices shows the "reference this ID" hint — its steps are
   * the primary place the source id is copy-pasted into other config. */
  showReferenceHint?: boolean;
}

export function GitSourceSelectDialog({
  open,
  onOpenChange,
  sourceId,
  onSourceIdChange,
  onConfirm,
  idPrefix,
  showReferenceHint = false,
}: GitSourceSelectDialogProps) {
  const fieldId = `${idPrefix}-git-source-select`;
  // ... shared body, using fieldId for Label htmlFor / SelectTrigger id ...
  // ... showReferenceHint && <p className="text-[11px] text-muted-foreground">...</p>
}
```

### Code after — call sites

```tsx
// get-git-devices/index.tsx
<GitSourceSelectDialog
  {...sharedProps}
  idPrefix="git-source-select"
  showReferenceHint
/>

// set-default-attributes/index.tsx
<GitSourceSelectDialog
  {...sharedProps}
  idPrefix="set-default-attributes-git-source-select"
/>
```

Import from `@/components/features/workflow-steps/shared/git-source-select-dialog` in both.

**Verify:** both steps' "select Git source" dialogs still work; `grep -rn "git-source-select-dialog.tsx"
frontend/src/components/features/workflow-steps` shows only the shared file plus the two import lines.

---

## M11 — Split `use-workflow-canvas.ts` into a facade

**Files:** `frontend/src/components/features/workflows/hooks/use-workflow-canvas.ts` (922 lines) and four new
sibling hooks in the same directory.

### Why

One hook currently owns React Flow node/edge change handlers, edge styling, node title/handle-side editing,
alignment, auto-layout, step-node construction, grouping (group/ungroup/rename/append/open), deletion,
duplication, and static-attribute editing — 30+ `useCallback`s in a single closure. This is the highest-impact
split in the codebase per the analysis (highest line count, highest handler count of any hook). Split by
concern, keep `useWorkflowCanvas()` as the public API so no call site changes.

### Code before — `use-workflow-canvas.ts` (structure)

```ts
export function useWorkflowCanvas() {
  // 30+ useCallback handlers covering: node/edge changes, connect, edge
  // style, edge labels, node title, handle sides, alignment, auto-layout,
  // node config change, step-node building, group add/rename/ungroup/open,
  // add/delete/duplicate steps, delete edges, static attributes...
  return useMemo(() => ({ /* ~40 fields */ }), [/* ~40 deps */]);
}
```

### Code after — split by concern, `use-workflow-canvas.ts` becomes a thin facade

```ts
"use client";

import { useWorkflowCanvasCore } from "./use-workflow-canvas-core";
import { useCanvasGroups } from "./use-canvas-groups";
import { useCanvasLayout } from "./use-canvas-layout";
import { useCanvasSteps } from "./use-canvas-steps";

export function useWorkflowCanvas() {
  const core = useWorkflowCanvasCore();
  const layout = useCanvasLayout(core);
  const groups = useCanvasGroups(core);
  const steps = useCanvasSteps(core, groups);

  return useMemo(
    () => ({ ...core, ...layout, ...groups, ...steps }),
    [core, layout, groups, steps],
  );
}
```

- **`use-workflow-canvas-core.ts`** — state (`nodes`, `edges`, `groups`, `staticAttributes`, dirty tracking),
  `handleNodesChange`, `handleEdgesChange`, `handleConnect`, `handleViewportChange`, `applyLoadedCanvas`,
  `clearCanvas`, `projected` (the `useMemo` projection). Everything else depends on this state, so it's the
  base every other hook takes as a parameter.
- **`use-canvas-layout.ts`** — `handleEdgeStyleChange`, `updateEdgeData`, `handleEdgeLabelChange` /
  `handleEdgeStartLabelChange` / `handleEdgeEndLabelChange` / `handleEdgeLabelBoldChange` /
  `handleEdgeLabelFontSizeChange`, `handleNodeTitleChange`, `handleIncomeHandleSideChange` /
  `handleOutcomeHandleSideChange`, `handleAlignNodes`, `handleAutoLayout`.
- **`use-canvas-groups.ts`** — `handleGroupSelectedSteps`, `handleRenameGroup`, `handleUngroupGroup`,
  `handleOpenGroup`, `appendToActiveGroup`.
- **`use-canvas-steps.ts`** — `buildStepNode`, `handleAddStep`, `handleAddStepAtPosition`,
  `handleDeleteNodes`, `handleDeleteEdge`, `handleDuplicateNode`, `handleNodeConfigChange`,
  `handleStaticAttributesChange`.

Example extraction (`use-canvas-groups.ts` — one of the four new files):

```ts
"use client";

import { useCallback } from "react";

import {
  findGroupContainingNode,
  groupIdFromNodeId,
  groupNodeId,
  ungroupNode,
} from "../utils/canvas-group-projection";
import type { useWorkflowCanvasCore } from "./use-workflow-canvas-core";

export function useCanvasGroups(core: ReturnType<typeof useWorkflowCanvasCore>) {
  const { nodes, setNodes, groups, setGroups, markDirty } = core;

  const handleGroupSelectedSteps = useCallback(
    (selectedIds: string[], label: string) => {
      // moved verbatim from use-workflow-canvas.ts ~778–807
    },
    [nodes, setNodes, groups, setGroups, markDirty],
  );

  const handleRenameGroup = useCallback(
    (groupId: string, label: string) => {
      // moved verbatim from ~808–815
    },
    [setGroups, markDirty],
  );

  const handleUngroupGroup = useCallback(
    (groupId: string) => {
      // moved verbatim from ~816–824
    },
    [nodes, setNodes, groups, setGroups, markDirty],
  );

  const handleOpenGroup = useCallback(
    (groupId: string) => {
      // moved verbatim from ~825–831
    },
    [/* ... */],
  );

  const appendToActiveGroup = useCallback(
    (nodeId: string) => {
      // moved verbatim from ~672–683
    },
    [/* ... */],
  );

  return { handleGroupSelectedSteps, handleRenameGroup, handleUngroupGroup, handleOpenGroup, appendToActiveGroup };
}
```

Each extracted hook takes `core` (the return of `use-workflow-canvas-core.ts`) as its single argument rather
than re-deriving state, so `nodes`/`setNodes`/etc. stay a single source of truth. `use-canvas-steps.ts` also
takes the `groups` object from `use-canvas-groups.ts` where step-building needs `appendToActiveGroup`.

**Do this split as one PR, not incrementally** — the callbacks share closure state too tightly to split safely
half-done. Before starting, write down (or diff against) the full current field list returned by
`useWorkflowCanvas()` so the facade's final `{ ...core, ...layout, ...groups, ...steps }` is verified to expose
the identical field set with `npx tsc --noEmit` (a removed or renamed field breaks every call site with a type
error, which is the safety net here).

**Verify:** `wc -l` on the five new/changed files — no single file should exceed ~350 lines. Every existing
call site of `useWorkflowCanvas()` (the canvas page, node/edge components) compiles unchanged. Manually exercise:
add step, group/ungroup, auto-layout, rename edge label, delete node — the canvas behaves identically.

---

## M12 — Fix `CLAUDE.md` staleness

**Files:** `/Users/mp/programming/auxilium-manus/CLAUDE.md`.

### Code before

```
**Frontend:** Next.js 16.2.6 (App Router), React 19, ...
```
```
cd frontend && npm run dev
...
# Frontend: http://localhost:3000
```
Nautobot GraphQL section still directs new code at `frontend/src/services/nautobot-graphql.ts`.

### Code after

```
**Frontend:** Next.js 16.2.12 (App Router), React 19, ...
```
```
cd frontend && npm run dev
...
# Frontend: http://localhost:3001
```

Replace the "GraphQL Integration" section's `services/nautobot-graphql.ts` guidance with a short note that
Nautobot/source data is fetched through backend REST endpoints under `/api/proxy/sources/nautobot/*` — no
client-side GraphQL client exists or should be added; add new source data needs as backend endpoints per the
"Adding New Backend Endpoint" section instead.

Also add the two missing doc files `CLAUDE.md` cites (`hooks/queries/BEST_PRACTICES.md`,
`hooks/queries/OPTIMISTIC_UPDATES.md`) — or drop the citation if the team decides not to maintain them; either
resolves the staleness, but a citation to a nonexistent file should not ship either way.

**Verify:** `grep -n "16.2.6\|localhost:3000\|nautobot-graphql" /Users/mp/programming/auxilium-manus/CLAUDE.md`
returns nothing.
