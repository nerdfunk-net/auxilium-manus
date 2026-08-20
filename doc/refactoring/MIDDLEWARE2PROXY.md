# Migration Plan: `middleware.ts` → `proxy.ts`

**Direction note:** despite this file's name, the migration runs **from the deprecated `middleware`
convention to the new `proxy` convention** — i.e. `frontend/src/middleware.ts` becomes
`frontend/src/proxy.ts`. There is no `proxy.ts` in the repo today; `middleware.ts` is the one file
that exists and needs to move. See the "How this plan came about" note at the bottom for why the
file is named this way.

**Source of the deprecation:** `next build` on this repo (Next.js 16.2.12) prints, before every
build:

```
⚠ The "middleware" file convention is deprecated. Please use "proxy" instead. Learn more: https://nextjs.org/docs/messages/middleware-to-proxy
```

**Scope:** exactly one file, `frontend/src/middleware.ts`, created in the H1 CSP-nonce work
(`doc/refactoring/FRONTEND.md` H1). No other file in the repo defines middleware/proxy logic, and
`next.config.ts` sets no `experimental.middleware*` / `skipMiddlewareUrlNormalize` options, so this
migration is a pure rename + one export rename — no behavioral change, no config-shape change.

**Verified against:** Next.js 16.2.12 as installed in `frontend/node_modules/next` on
`refactoring/grok46`. The rename mechanics below were read directly out of that package's build
templates (`node_modules/next/dist/build/templates/middleware.js`) and its bundled codemod
documentation (`node_modules/next/dist/docs/01-app/02-guides/upgrading/codemods.md`), not
reconstructed from memory.

---

## Why this is safe to do now (not urgent, but low-risk)

- `middleware` and `proxy` are two file-convention names recognized by the exact same runtime
  adapter (`next/dist/build/templates/middleware.js`). The generated handler does:

  ```js
  const isProxy = page === '/proxy' || page === '/src/proxy';
  const handlerUserland = (isProxy ? mod.proxy : mod.middleware) || mod.default;
  ```

  So the only things that change are the **file name** and the **exported function name** — the
  `NextRequest`/`NextResponse` API, the `config.matcher` export, and everything inside the function
  body are untouched.
- Next.js ships an official codemod for exactly this migration (`middleware-to-proxy`), which this
  plan uses as the primary path.
- The deprecation is currently a build-time warning, not an error — `middleware.ts` still works.
  This migration removes noise from every future `next build`/`next dev` run and gets ahead of the
  convention being removed in a later major version, but it is not blocking anything today.

---

## Step 1 — Run the official codemod

```bash
cd frontend
npx @next/codemod@latest middleware-to-proxy .
```

Per Next's own codemod documentation, this:

- Renames `middleware.<extension>` to `proxy.<extension>` (here: `src/middleware.ts` → `src/proxy.ts`)
- Renames the named export `middleware` to `proxy`
- Renames `experimental.middlewarePrefetch` → `experimental.proxyPrefetch` in `next.config.ts` (not
  present in this repo's config — no-op here)
- Renames `experimental.middlewareClientMaxBodySize` → `experimental.proxyClientMaxBodySize` (not
  present — no-op here)
- Renames `experimental.externalMiddlewareRewritesResolve` → `experimental.externalProxyRewritesResolve`
  (not present — no-op here)
- Renames top-level `skipMiddlewareUrlNormalize` → `skipProxyUrlNormalize` (not present — no-op here)

Confirm the codemod ran the rename and export change as expected:

```bash
git status --short frontend/src
git diff frontend/src/proxy.ts   # (or the old path, if the tool left it in place — see Step 2)
```

If the codemod is unavailable (offline, registry blocked, etc.), Step 1 can be done by hand — see
"Manual fallback" below. The result must be identical either way.

---

## Step 2 — Verify the resulting file

### Code before — `frontend/src/middleware.ts`

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

### Code after — `frontend/src/proxy.ts` (new path, replaces `middleware.ts`)

```ts
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function proxy(request: NextRequest) {
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

Only the file name and the `middleware` → `proxy` function name change. `config` (and its
`matcher`) is read by the same file-convention-agnostic code path in both cases, so it is **not**
renamed.

**Verify:** `git status --short frontend/src` shows `middleware.ts` deleted and `proxy.ts` added
(a rename, ideally — `git status` may report it as `R` if the diff is similarity-detected). `grep -n
"export function middleware\|export function proxy" frontend/src/proxy.ts` shows only `proxy`.

---

## Step 3 — Update the two comments that name `middleware.ts`

Two comments elsewhere in the frontend reference the file by its old name — these are stale (but
harmless) if left after the rename, so fix them in the same change:

### Code before — `frontend/next.config.ts` (line 29)

```ts
// Content-Security-Policy is set in middleware.ts instead — it needs a
// per-request nonce, and next.config.ts headers are static.
```

### Code after

```ts
// Content-Security-Policy is set in proxy.ts instead — it needs a
// per-request nonce, and next.config.ts headers are static.
```

### Code before — `frontend/src/app/layout.tsx` (line 29)

```ts
  // Reading the x-nonce request header (set by middleware.ts) here is what
  // makes Next.js apply that nonce to its own inline bootstrap scripts.
```

### Code after

```ts
  // Reading the x-nonce request header (set by proxy.ts) here is what
  // makes Next.js apply that nonce to its own inline bootstrap scripts.
```

**Verify:** `grep -rn "middleware\.ts" frontend/src frontend/next.config.ts` returns nothing
(`doc/refactoring/FRONTEND.md` is historical record of the original H1 work and is intentionally
left as-is — it documents what was true at the time it was written, not the current file layout).

---

## Step 4 — Rebuild and confirm the warning is gone

```bash
cd frontend
npx tsc --noEmit
npm run lint
npm run build
```

**Verify:**
- `next build` output no longer prints the `"middleware" file convention is deprecated` warning.
- The build's route summary still shows `ƒ Proxy (Middleware)` (or equivalent) exactly as it did
  before the rename — the CSP header and matcher behavior are unchanged, only the source convention
  moved.
- Manually load any page in dev (`npm run dev`) and inspect the response headers — `Content-Security-Policy`
  should still be present with a fresh `nonce-` value per request, exactly as before.

No test suite exercises `middleware.ts` today (`frontend/src` has no middleware/proxy test file),
so there is nothing to update there.

---

## Manual fallback (if the codemod can't run)

1. `git mv frontend/src/middleware.ts frontend/src/proxy.ts`
2. In the moved file, rename `export function middleware(` to `export function proxy(`. Leave
   everything else — including `export const config = { matcher: [...] }` — untouched.
3. Apply Step 3's two comment edits.
4. Run Step 4's verification.

---

## Rollback

This is a same-behavior rename with no data migration, so rollback is just reverting the commit
(`git revert`) or, pre-commit, `git checkout -- frontend/src` plus re-creating `middleware.ts` from
`doc/refactoring/FRONTEND.md`'s H1 section if needed.

---

## Out of scope

- No change to the CSP policy itself, the nonce mechanism, or `matcher` — this plan only moves
  *where* that logic is declared to Next.js, per the framework's own renamed convention.
- Not addressed: any future Next.js major-version removal date for the `middleware` convention —
  none was found documented in the installed package; this plan proceeds on "it's deprecated now,
  migrate opportunistically," not "it breaks on version X."
