# Frontend production-hardening refactoring plan — 13 August 2026

Source: `doc/GROK-20260813-ANALYSIS.md`. This plan covers **P0 (critical)** and **P1 (medium)** items only. P2 backlog (inventory colour tokens, login Shadcn+Zod, artifact size caps, JWT denylist, Hatchet `javascript:` href) is out of scope.

Implement **in the order below**. Later items assume earlier contracts. Do not re-analyse call sites — every file, symbol, and replacement is listed.

---

## How to read this document

Each work item has:

- **Before** — current behaviour and the exact code to change.
- **After** — the target contract. Copy the shapes; do not invent parallel APIs.
- **Files** — every path that must change. If a path is not listed, leave it alone.
- **Verify** — how to know the item is done.

Do not change workflow-step **executors** (`backend/workflow_steps/*/executor.py`). They already load tokens via `SettingsService.get_source_config` / `get_source_config_for_step`. This plan only stops the **HTTP/UI** layer from shipping those tokens to the browser.

---

## Out of scope

- `backend/workflow_steps/**/executor.py` (already server-side source lookup).
- `models/plugins.py` `DeviceSelectionPreviewRequest` unless you find a live HTTP route still using it (registry types only; `routers/workflow_steps.py` does not expose preview-with-token).
- Semantic Tailwind cleanup in inventory (`bg-blue-*`).
- Rewriting login to Shadcn `Form` + Zod.
- Adding `BEST_PRACTICES.md` / `OPTIMISTIC_UPDATES.md`.
- Cookie revocation denylist.
- Splitting files that are 500–800 lines (store-artifact, template-editor, import dialog, etc.). Only the two 1k+ files are in this plan.

---

## Suggested PR sequence

| PR | Items | Why this grouping |
|---|---|---|
| 1 | R1 | Tiny, security, no API change. |
| 2 | R2 | Token/source_id contract. Backend + frontend together; do not split. |
| 3 | R3 + R4 | Dev-tools kill-switch + leftover `console.debug`. |
| 4 | R5 + R6 | Proxy path hardening + security headers. |
| 5 | R7 + R8 + R13 + R14 | Query-hook discipline and React default-param fixes. |
| 6 | R9 + R10 | UX gating + error boundaries. |
| 7 | R11 | Split `workflow-builder-page.tsx` (after R7). |
| 8 | R12 | Split `step-result-viewer.tsx`. |
| 9 | R15 | Tests that lock R1/R2/R5. |

---

# R1 — OIDC callback must fail closed on `state` (P0)

## Before

`frontend/src/components/features/auth/oidc-callback-page.tsx`, inside `OidcCallbackContent` `useEffect` (`handleCallback`):

```ts
const storedState = sessionStorage.getItem("oidc_state");
sessionStorage.removeItem("oidc_state");

if (storedState && state !== storedState) {
  setError("Invalid state parameter — possible CSRF attempt");
  setStatus("error");
  return;
}

const providerId = state.includes(":") ? state.split(":", 2)[0] : null;
```

If `sessionStorage` is empty, the check is skipped and the authorization `code` is POSTed to `/api/auth/oidc/${providerId}/callback`. `providerId` is taken from the attacker-controlled `state` query param.

Login still stores state correctly in `login-page.tsx`:

```ts
sessionStorage.setItem("oidc_state", data.state);
window.location.assign(data.authorization_url);
```

Backend already prefixes state as `{provider_id}:{nonce}` in `backend/routers/oidc.py` `_build_login_response`.

## After

1. Extract a pure helper (so R15 can unit-test it without React):

`frontend/src/lib/oidc-state.ts`

```ts
const PROVIDER_ID_RE = /^[a-z][a-z0-9_-]{0,63}$/;

export function parseAndVerifyOidcState(
  storedState: string | null,
  incomingState: string | null,
): { ok: true; providerId: string } | { ok: false; error: string } {
  if (!incomingState || !storedState) {
    return { ok: false, error: "Missing state parameter — possible CSRF attempt" };
  }
  if (storedState !== incomingState) {
    return { ok: false, error: "Invalid state parameter — possible CSRF attempt" };
  }
  const providerId = incomingState.includes(":")
    ? incomingState.split(":", 2)[0]
    : null;
  if (!providerId || !PROVIDER_ID_RE.test(providerId)) {
    return { ok: false, error: "Invalid state parameter" };
  }
  return { ok: true, providerId };
}
```

2. In `oidc-callback-page.tsx`, replace the `storedState && state !== storedState` block and the `state.split` provider parse with:

```ts
const storedState = sessionStorage.getItem("oidc_state");
sessionStorage.removeItem("oidc_state");
const verified = parseAndVerifyOidcState(storedState, state);
if (!verified.ok) {
  setError(verified.error);
  setStatus("error");
  return;
}
const providerId = verified.providerId;
```

3. Do **not** change the production callback URL (`/api/auth/oidc/${providerId}/callback`). That route sets the HttpOnly cookie and returns `{ user }` only.

4. `oidc-test-callback-page.tsx` currently uses a looser check (`stateValid = Boolean(state) && state === storedState`) and the generic proxy. Leave its logic until R3 (the page will be compiled out of production). If you touch it in this PR, reuse `parseAndVerifyOidcState` the same way.

## Files

- **Add:** `frontend/src/lib/oidc-state.ts`
- **Edit:** `frontend/src/components/features/auth/oidc-callback-page.tsx`

## Verify

- Start SSO, complete login: still works.
- Open `/login/callback?code=x&state=lab:forged` in a fresh tab (empty `sessionStorage`): error, no POST to `/api/auth/oidc/...`.
- Mismatched `sessionStorage` vs `state`: same error.

---

# R2 — Stop sending Nautobot/Git tokens to the browser (P0)

This is one contract change. Do backend and frontend in the same PR.

**Target model (already used by ISE and pyATS CRUD):** the UI identifies a source by `source_id`. The server looks up `url`/`token`/`verify_ssl`. The browser never reads or writes the stored token except when the operator **types a new one** into a create/edit form or a test-connection form.

Git preview already uses `git_source_id` (`backend/routers/sources/git/ops.py`). Copy that pattern for Nautobot HTTP ops.

## R2.1 Backend — redact settings GET; keep token on write

### Before

`backend/services/settings/settings_service.py` `_to_response` returns `setting.value` unchanged. Nautobot/Git sources are stored as:

- key `sources.nautobot.{source_id}` / `sources.git.{source_id}`
- value dict including `"token": "<secret>"`

`GET /api/settings` and `GET /api/settings/{key}` therefore return the raw token. The frontend parses it in `parse-source-settings.ts` and `use-nautobot-source-credentials.ts`.

On edit, `nautobot-source-dialog.tsx` `resolveToken` falls back to `initialValue.token` from that GET, so a blank field still re-sends the secret.

ISE/pyATS already omit secrets on GET (`ISESourceResponse` / `PyATSSourceResponse` have no password/token fields). Do not change those routers.

### After

In `SettingsService._to_response` (used by `list_settings`, `get_setting`, `create_setting`, `update_setting`):

1. If `parse_source_key(setting.key)` is `nautobot` or `git`:
   - shallow-copy `value`
   - `token_configured = bool(str(value.get("token") or "").strip())`
   - `value["token"] = ""`
   - `value["token_configured"] = token_configured`
2. Return that copy. Never mutate the ORM object.

In `SettingsService.update_setting` (and create is unchanged — create still requires a token in the request body):

- After loading the existing row, if the key is a nautobot/git source and the incoming `value` has a missing or blank `"token"`, copy `"token"` from the existing stored value before save.
- Incoming `"token_configured"` must be stripped and never persisted.

`NautobotTestConnectionRequest` stays `{ url, token, verify_ssl, timeout? }` for **unsaved** form values. Add an optional `source_id: str | None = None`. Validation:

- If `source_id` is set: ignore body token; `SettingsService.get_source_config("nautobot", source_id)` and test with stored credentials.
- Else: require `url` + `token` as today.

Same optional `source_id` on the Git test-connection request body (`backend/routers/sources/git/ops.py` test-connection handler — keep current url/token fields, add optional `source_id`).

### Files

- `backend/services/settings/settings_service.py`
- `backend/models/sources_nautobot.py` (`NautobotTestConnectionRequest`: `token` optional if `source_id` set; add `source_id: str | None = None`. Use a model validator: exactly one of (source_id) or (url+token).)
- Git test-connection Pydantic model in `backend/models/sources_git.py` (same optional `source_id`)
- `backend/routers/sources/nautobot/ops.py` `test_connection`
- `backend/routers/sources/git/ops.py` test-connection handler
- Tests: add `backend/tests/unit/test_settings_token_redaction.py` covering list/get redaction, update-with-blank-token preserves secret, create still stores token.

## R2.2 Backend — Nautobot ops take `source_id`, not query-string tokens

### Before

`backend/dependencies.py`:

```python
def nautobot_credentials_from_query(
    nautobot_url: str = Query(..., min_length=1),
    nautobot_token: str = Query(..., min_length=1),
) -> NautobotCredentials:
    return service_factory.credentials_from_connection(nautobot_url, nautobot_token)

def nautobot_credentials_from_body(connection: NautobotConnection) -> NautobotCredentials:
    return service_factory.credentials_from_connection(
        connection.nautobot_url, connection.nautobot_token, connection.timeout,
    )
```

`NautobotConnection` (`backend/models/sources_nautobot.py`) is:

```python
class NautobotConnection(BaseModel):
    nautobot_url: str
    nautobot_token: str
    timeout: float = 30.0
```

Subclasses used as POST bodies: `InventoryPreviewRequest`, `DeviceIdsPreviewRequest`, `DeviceSearchRequest`, `DeviceDetailsRequest`, `DeviceAttributesRequest`.

GET routes that inject `nautobot_credentials_from_query`:

| Method | Path in `backend/routers/sources/nautobot/ops.py` | Handler |
|---|---|---|
| GET | `/custom-fields` | `get_custom_fields` |
| GET | `/field-values/{field_name}` | `get_field_values` |
| GET | `/resolve-devices/{inventory_id}` | `resolve_inventory_to_devices` |
| GET | `/resolve-devices/detailed/{inventory_id}` | (same file, ~line 379) |
| GET | `/{inventory_id}/devices` | `get_inventory_devices` |

POST routes that call `nautobot_credentials_from_body(request)`:

| Path | Handler |
|---|---|
| `/preview` | `preview_inventory` |
| `/preview-device-ids` | `preview_device_ids` |
| `/devices/search` | `search_devices` |
| `/devices/details` | `get_device_details` |
| `/devices/attributes` | `get_device_attributes` |

`NautobotCredentialsQuery` in `models/sources_nautobot.py` (url+token query helper) is unused once the query dependency changes; delete it.

### After

Replace the two dependency helpers in `backend/dependencies.py`:

```python
def nautobot_credentials_from_source_id(
    source_id: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
) -> NautobotCredentials:
    config = SettingsService(db).get_source_config("nautobot", source_id)
    return service_factory.credentials_from_connection(
        str(config.get("url") or ""),
        str(config.get("token") or ""),
        verify_ssl=config.get("verify_ssl", True),
    )
```

For POST bodies, replace `NautobotConnection` with:

```python
class NautobotSourceRef(BaseModel):
    source_id: str = Field(..., min_length=1, max_length=64)
    timeout: float = Field(default=30.0, ge=1, le=120)
```

Then:

```python
class InventoryPreviewRequest(NautobotSourceRef):
    operations: list[LogicalOperation] = Field(default_factory=list)

class DeviceIdsPreviewRequest(NautobotSourceRef):
    device_ids: list[str] = Field(default_factory=list)

class DeviceSearchRequest(NautobotSourceRef):
    search: str = Field(..., min_length=1)
    limit: int = Field(default=20, ge=1, le=100)
```

Same for `DeviceDetailsRequest` / `DeviceAttributesRequest` (keep their extra fields, change the base).

Add:

```python
def nautobot_credentials_from_source_ref(
    ref: NautobotSourceRef,
    db: Session = Depends(get_db),
) -> NautobotCredentials:
    ...
```

Or resolve inside each handler via `SettingsService(db).get_source_config("nautobot", request.source_id)` — one helper is enough; do not duplicate.

**Do not** keep a compatibility query param `nautobot_token`. Removing it is the point.

`get_source_config` already 404s if the source is missing and 400s if `source_id` is empty/invalid.

## R2.3 Frontend — types and settings parse

### Before

`frontend/src/components/features/settings/types/settings-api.ts`:

```ts
export interface NautobotSourceValue {
  sourceId: string;
  url: string;
  token: string;
  verifySsl: boolean;
}
export interface GitSourceValue {
  sourceId: string;
  url: string;
  branch: string;
  token: string;
  username: string;
  repository_path: string;
  verifySsl: boolean;
}
```

`parse-source-settings.ts` `parseNautobotValue` / `parseGitValue` read `value.token` as a string and keep it.

`use-nautobot-source-credentials.ts` returns `{ url, token, isLoading, isError, isReady, sourceId }` and treats `isReady` as `url && token`.

### After

```ts
export interface NautobotSourceValue {
  sourceId: string;
  url: string;
  tokenConfigured: boolean;
  verifySsl: boolean;
}
export interface GitSourceValue {
  sourceId: string;
  url: string;
  branch: string;
  tokenConfigured: boolean;
  username: string;
  repository_path: string;
  verifySsl: boolean;
}
```

Parse `token_configured` (boolean) from the setting value. Ignore any `token` field (it will be `""`).

`useNautobotSourceCredentials`:

```ts
return {
  url: ...,
  sourceId: normalizedId,
  tokenConfigured: Boolean(value.token_configured),
  isReady: Boolean(normalizedId && url && tokenConfigured),
  isLoading, isError,
};
```

Delete the `token` field from this hook’s return. Fix every caller (listed in R2.4).

Nautobot/Git **create** still POST `value: { url, token, verify_ssl, ... }` with a required token.

Nautobot/Git **update**: if the password field is blank, send `value` **without** `token` (or `"token": ""`). Backend R2.1 preserves the stored secret.

`resolveToken` in both dialogs: on create, require a non-empty token. On edit, if the field is blank, do not send `token`. Test-connection on edit with blank field: POST `{ source_id, verify_ssl }` (R2.1). Test-connection on create or when the user typed a token: POST `{ url, token, verify_ssl }` as today.

### Files

- `frontend/src/components/features/settings/types/settings-api.ts`
- `frontend/src/components/features/settings/utils/parse-source-settings.ts`
- `frontend/src/hooks/queries/use-nautobot-source-credentials.ts`
- `frontend/src/components/features/settings/dialogs/nautobot-source-dialog.tsx`
- `frontend/src/components/features/settings/dialogs/git-source-dialog.tsx`
- `frontend/src/hooks/queries/use-source-test-connection-mutations.ts` — payloads gain optional `source_id`; `token` optional
- `frontend/src/components/features/settings/components/sources-settings-canvas.tsx` — stop passing `token: values.token` on update when blank; pass `tokenConfigured` through parsed configs only

## R2.4 Frontend — every live Nautobot call uses `source_id`

Replace `nautobot_url` + `nautobot_token` with `source_id` at these call sites. Keep `nautobot_url` in the UI only as a **display** string from settings (no secret).

### Query key factory

`frontend/src/lib/query-keys.ts` today:

```ts
fieldValues: (nautobotUrl: string, field: string) =>
  [...queryKeys.sourcesNautobot.all, "field-values", nautobotUrl, field]
preview: (nautobotUrl: string, operationsKey: string) =>
  [...queryKeys.sourcesNautobot.all, "preview", nautobotUrl, operationsKey]
customFields: (nautobotUrl: string) =>
  [...queryKeys.sourcesNautobot.all, "custom-fields", nautobotUrl]
```

After: first argument is `sourceId: string`, not URL.

### Hooks

| File | Before | After |
|---|---|---|
| `hooks/queries/use-get-nautobot-devices-field-values-query.ts` | GET `sources/nautobot/field-values/${field}?nautobot_url=&nautobot_token=` | GET `sources/nautobot/field-values/${field}?source_id=` |
| `hooks/queries/use-inventory-custom-fields-query.ts` | GET `.../custom-fields?nautobot_url=&nautobot_token=` | GET `.../custom-fields?source_id=` |
| `hooks/queries/use-get-nautobot-devices-preview-mutation.ts` | POST body `{ nautobot_url, nautobot_token, operations }` | POST `{ source_id, operations }` |
| `features/workflow-steps/get-nautobot-devices/preview-dialog.tsx` | POST preview and preview-device-ids with url+token; `enabled` requires token | POST `{ source_id, operations \| device_ids }`; `enabled: open && Boolean(config.source_id)` |

Add a dedicated load-devices helper (or inline in `device-selector.tsx` via `useApi`):

- Before: `GET sources/nautobot/${id}/devices?nautobot_url=&nautobot_token=`
- After: `GET sources/nautobot/${id}/devices?source_id=`

### Inventory UI

| File | Change |
|---|---|
| `features/inventory/types/device-selector.ts` `DeviceSelectorProps` | Replace `nautobot_url` + `nautobot_token` with `sourceId: string`. Keep optional `nautobotUrl?: string` only if a banner needs to show the URL. |
| `features/inventory/hooks/use-inventory-source.ts` | Return `{ sourceId, nautobotUrl, isReady, isLoading, hasSources }`. Drop `nautobot_token`. `isReady` = credentials hook `isReady`. |
| `features/inventory/inventory-page.tsx` | `<DeviceSelector sourceId={source.sourceId} sourceReady={source.isReady} ... />` |
| `features/inventory/components/device-selector.tsx` | Pass `sourceId` into `useDeviceFilter` / `useDevicePreview`. Load-inventory GET uses `source_id` query param only. |
| `features/inventory/hooks/use-device-filter.ts` | Options: `{ sourceId: string; sourceReady: boolean }`. |
| `features/inventory/hooks/use-device-preview.ts` | Options: `{ sourceId: string; sourceReady: boolean }`. Preview mutation body `{ source_id, operations }`. |

### Workflow step + templates

| File | Change |
|---|---|
| `features/workflow-steps/get-nautobot-devices/index.tsx` | Preview dialog `config` becomes `{ source_id: sourceId, inventory_type, device_filter, device_ids }`. Stop reading `credentials.token`. `isReady` from `useNautobotSourceCredentials` still gates the Preview button. |
| `features/templates/template-editor-page.tsx` | Stop passing `nautobotToken={sourceCredentials.token}`. Pass `sourceId`. |
| `features/templates/components/netmiko-options-panel.tsx` | Drop `nautobotUrl` / `nautobotToken` props. Device search POST body: `{ source_id: sourceId, search, limit: 20 }` to `sources/nautobot/devices/search`. |

### Files (complete R2.4 list)

- `frontend/src/lib/query-keys.ts`
- `frontend/src/hooks/queries/use-get-nautobot-devices-field-values-query.ts`
- `frontend/src/hooks/queries/use-inventory-custom-fields-query.ts`
- `frontend/src/hooks/queries/use-get-nautobot-devices-preview-mutation.ts`
- `frontend/src/hooks/queries/use-nautobot-source-credentials.ts` (already in R2.3)
- `frontend/src/components/features/inventory/types/device-selector.ts`
- `frontend/src/components/features/inventory/hooks/use-inventory-source.ts`
- `frontend/src/components/features/inventory/hooks/use-device-filter.ts`
- `frontend/src/components/features/inventory/hooks/use-device-preview.ts`
- `frontend/src/components/features/inventory/components/device-selector.tsx`
- `frontend/src/components/features/inventory/inventory-page.tsx`
- `frontend/src/components/features/workflow-steps/get-nautobot-devices/index.tsx`
- `frontend/src/components/features/workflow-steps/get-nautobot-devices/preview-dialog.tsx`
- `frontend/src/components/features/templates/template-editor-page.tsx`
- `frontend/src/components/features/templates/components/netmiko-options-panel.tsx`

Grep after this PR must return **no** `nautobot_token` under `frontend/src` except comments. Allowed remaining backend uses: `service_factory.credentials_from_connection`, executors, `SettingsService.get_source_config`.

## R2 verify

- Settings → Sources: create Nautobot source, reload page, token field empty, “leave blank to keep” still updates URL/verify_ssl without wiping the token (confirm by testing connection with `source_id` only).
- Network tab: no request URL contains `nautobot_token=`.
- Inventory preview, field-value dropdowns, custom fields, load saved inventory, template device search, get-nautobot-devices Preview all still work against a saved source.
- `GET /api/settings?key_prefix=sources.nautobot.` JSON has `"token": ""` and `"token_configured": true`.

---

# R3 — Gate developer tools out of production (P0)

## Before

Dashboard routes (all behind the authenticated `(dashboard)/layout.tsx` cookie check):

| Route file | Page component | Backend |
|---|---|---|
| `frontend/src/app/(dashboard)/tools/page.tsx` | `ToolsPage` | none |
| `.../tools/oidc-test/page.tsx` | `OidcTestPage` | `GET /api/auth/oidc/debug` (`system.oidc:read`) |
| `frontend/src/app/(auth)/login/oidc-test-callback/page.tsx` | `OidcTestCallbackPage` | **`POST /api/proxy/auth/oidc/{id}/callback`** — generic proxy, returns backend `TokenResponse` including `access_token`; page renders JWT header/payload/raw |
| `.../tools/database-migration/page.tsx` | `DatabaseMigrationPage` | schema + RBAC seed (`system.database:*`, `system.rbac:write`) |
| `.../tools/add-certificate/page.tsx` | `AddCertificatePage` | `system.certificates:*` |

`ToolsPage` (`frontend/src/components/features/tools/tools-page.tsx`) always lists all three cards. Comment says they are “not shown in the main navigation”. URLs are guessable.

`backend/routers/oidc.py`: `POST /{provider_id}/test-login` and `GET /debug` are permission-gated but always registered.

## After

Introduce one flag, default **off**:

- Backend: env `ENABLE_DEV_TOOLS` (`true`/`1`/`yes` = on). Read in a tiny helper `backend/core/dev_tools.py`: `def dev_tools_enabled() -> bool`.
- Frontend: same env `ENABLE_DEV_TOOLS` (Next.js server-only; **do not** prefix `NEXT_PUBLIC_`).

**OIDC test (must not ship):**

1. Add `frontend/src/app/(dashboard)/tools/oidc-test/layout.tsx` (Server Component, no `'use client'`):

```tsx
import { notFound } from "next/navigation";

export default function OidcTestLayout({ children }: { children: React.ReactNode }) {
  if (process.env.ENABLE_DEV_TOOLS !== "true") notFound();
  return children;
}
```

2. Same `notFound()` in `frontend/src/app/(auth)/login/oidc-test-callback/layout.tsx`.

3. `ToolsPage`: only push the OIDC card onto `TOOL_LINKS` when a server-provided flag is true. Because `ToolsPage` is a client component, pass the flag from a new server wrapper or from `tools/page.tsx`:

```tsx
// tools/page.tsx (already a server stub)
import { ToolsPage } from "@/components/features/tools/tools-page";

export default function ToolsRoute() {
  return (
    <ToolsPage
      oidcTestEnabled={process.env.ENABLE_DEV_TOOLS === "true"}
    />
  );
}
```

Add `oidcTestEnabled: boolean` to `ToolsPage` props; omit the OIDC card when false.

4. Backend: at the top of `initiate_test_login` and `debug_status` in `backend/routers/oidc.py`:

```python
if not dev_tools_enabled():
    raise HTTPException(status_code=404, detail="Not found")
```

Do this **in addition to** existing `require_permission("system.oidc", "read")`.

**Keep (permission-gated admin ops, not debug):**

- `/tools/database-migration` and `/tools/add-certificate` stay. They already call `hasPermission` in the page. Do not 404 them.
- Hide a card on `ToolsPage` when the current user lacks the matching permission (`system.database:read` or `write` for migration; `system.certificates:read` or `write` for certs). Use `useAuthStore` + `hasPermission` like `OidcTestPage` already does.

**Do not** change `OidcTestCallbackPage` to use `/api/auth/oidc/.../callback` (that would mint a real session). Once the route 404s in production, the JWT-in-JSON leak is unreachable.

Document `ENABLE_DEV_TOOLS=true` in `CLAUDE.md` Environment Variables (frontend `.env.local` and backend `.env`) as a **development-only** flag.

## Files

- **Add:** `backend/core/dev_tools.py`
- **Add:** `frontend/src/app/(dashboard)/tools/oidc-test/layout.tsx`
- **Add:** `frontend/src/app/(auth)/login/oidc-test-callback/layout.tsx`
- **Edit:** `backend/routers/oidc.py`
- **Edit:** `frontend/src/app/(dashboard)/tools/page.tsx`
- **Edit:** `frontend/src/components/features/tools/tools-page.tsx`
- **Edit:** `CLAUDE.md` (env var line only)

## Verify

- Production-like: unset `ENABLE_DEV_TOOLS` → `/tools/oidc-test` and `/login/oidc-test-callback` are 404; `GET /api/proxy/auth/oidc/debug` is 404 even as admin; Tools page has no OIDC card.
- Dev: `ENABLE_DEV_TOOLS=true` restores the dashboard.
- Unprivileged user: Tools page hides migration/certs cards; visiting the URL still 403s from the API.

---

# R4 — Remove leftover debug logging (P0)

## Before

`frontend/src/hooks/queries/use-get-git-devices-preview-mutation.ts` logs request/response in `mutationFn`, `onSuccess`, `onError`, `onSettled` via `console.debug("[DEBUG] ...")`.

`frontend/src/components/features/workflow-steps/get-git-devices/index.tsx` `handleShowPreview` logs `sourceId`, `filenamePattern`, and the preview result.

## After

Delete every `console.debug` in those two files. Keep error handling via toast / thrown `Error` from `useApi`.

## Files

- `frontend/src/hooks/queries/use-get-git-devices-preview-mutation.ts`
- `frontend/src/components/features/workflow-steps/get-git-devices/index.tsx`

## Verify

`rg 'console\.debug' frontend/src` is empty.

---

# R5 — Reject `..` proxy path segments (P1)

## Before

`frontend/src/lib/api-proxy.ts` `normalizeProxyPath`:

```ts
const requestedPath = path.map((segment) => encodeURIComponent(segment)).join("/");
if (requestedPath.startsWith("api/")) {
  return `/${requestedPath}`;
}
return `/api/${requestedPath}`;
```

`encodeURIComponent("..") === ".."`, so `/api/proxy/../foo` becomes `http://BACKEND/api/../foo` → `http://BACKEND/foo`, escaping the `/api` prefix on the FastAPI host.

`buildBackendUrl` is already exported; `normalizeProxyPath` is not.

Hop-by-hop / cookie stripping stays as-is.

## After

```ts
const FORBIDDEN_SEGMENTS = new Set(["", ".", ".."]);

export function normalizeProxyPath(path: string[]) {
  if (path.some((segment) => FORBIDDEN_SEGMENTS.has(segment))) {
    throw new Error("Invalid proxy path");
  }
  const requestedPath = path.map((segment) => encodeURIComponent(segment)).join("/");
  // existing api/ prefix logic unchanged
}
```

In `proxyRequest`, catch that throw and return `NextResponse.json({ message: "Not found" }, { status: 404 })`. Do not proxy.

Export `normalizeProxyPath` for R15.

Keep the `#` re-encode comment and `encodeURIComponent` per segment (ISE group names).

## Files

- `frontend/src/lib/api-proxy.ts`

## Verify

- Unit tests in R15: `[".."]`, `["foo", "..", "bar"]`, `[""]` → throw; `["workflows", "1"]` → `/api/workflows/1`; `["api", "auth", "me"]` → `/api/auth/me`; segment `myGroup#x` still encoded.

---

# R6 — Production security headers (P1)

## Before

`frontend/next.config.ts` `securityHeaders`:

- `Content-Security-Policy: frame-ancestors 'none'`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`

Monaco is self-hosted at `/vs` (`code-editor-panel.tsx` `loader.config({ paths: { vs: "/vs" } })`). No HSTS.

Logout: `frontend/src/app/api/auth/logout/route.ts` calls `cookieStore.delete(AUTH_COOKIE_NAME)` without repeating `path: "/"`. Login sets `path: "/"`, `sameSite: "lax"`, `httpOnly: true`.

## After

Replace the CSP value with (single line, no newlines inside the header):

```
default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; worker-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'
```

`'unsafe-inline'` / `'unsafe-eval'` are required for Next.js App Router + Monaco until a nonce CSP is adopted. Do not add `https:` or CDNs; Monaco must stay on `/vs`.

Add HSTS **only when** `process.env.NODE_ENV === "production"`:

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

Add:

```
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

Logout/delete cookie with the same attributes as set (Next.js 16 `cookies().delete({ name, path: "/" })` or set `maxAge: 0` with `path: "/"`, `httpOnly: true`, `sameSite: "lax"`, `secure: process.env.NODE_ENV === "production"`). Apply the same delete helper in `frontend/src/app/api/auth/me/route.ts` and `refresh/route.ts` where they already `cookieStore.delete(AUTH_COOKIE_NAME)`.

Extract `clearAuthCookie(cookieStore)` in `frontend/src/lib/auth.ts` next to `AUTH_COOKIE_NAME` so the three routes cannot drift.

## Files

- `frontend/next.config.ts`
- `frontend/src/lib/auth.ts`
- `frontend/src/app/api/auth/logout/route.ts`
- `frontend/src/app/api/auth/me/route.ts`
- `frontend/src/app/api/auth/refresh/route.ts`

## Verify

`curl -I https://.../login` (or `next start`) shows the new headers. Login + Monaco editor still load. Sign-out clears `auxilium_auth_token` (Application → Cookies).

---

# R7 — Replace raw `/api/proxy` `fetch` with query/mutation hooks (P1)

Auth routes (`/api/auth/login|me|logout|refresh` and `/api/auth/oidc/.../callback`) stay as raw `fetch`. They must set cookies.

## R7.1 Workflow detail — builder already has the hook

### Before

`useWorkflowQuery` exists at `frontend/src/hooks/queries/use-workflow-query.ts`:

```ts
queryKey: queryKeys.workflows.detail(workflowId ?? -1)
queryFn: () => apiCall<WorkflowResponse>(`workflows/${workflowId}`)
enabled: workflowId != null
```

`WorkflowBuilderPage` does **not** use it. Two raw fetches:

1. Mount restore `useEffect` (~line 219): `fetch(\`/api/proxy/workflows/${mountWorkflowId}\`, { credentials: "include" })` then `migrateCanvasState` / `repairOrphanGroups` / `setAllNodes`…
2. `handleLoadWorkflow` (~line 754): same URL for `summary.id`.

Neither maps 401 through `useApi` (no redirect to `/login`).

`WorkflowResponse` is `frontend/src/components/features/workflows/types/workflow-persistence.ts` (`canvas_nodes`, `canvas_edges`, `canvas_groups`, `static_attributes`, `id`, `uuid`, `name`, `description`, `folder`, …).

### After

Keep `useWorkflowQuery` as the only GET.

**Mount path:** this cannot be a simple `useQuery` in the page today because of the canvas-draft rehydration (`hasRehydratedCanvasRef` / `initialCanvasDraft`). Extract a function (used by both call sites):

`frontend/src/components/features/workflows/utils/apply-loaded-workflow.ts`

```ts
export function canvasFromWorkflowResponse(
  full: WorkflowResponse,
  plugins: PluginDefinition[],
): {
  nodes: PersistedCanvasNode[];
  edges: WorkflowCanvasEdge[];
  groups: CanvasGroup[];
  staticAttributes: StaticAttributeDef[];
  migrated: boolean;
}
```

Move the existing `migrateCanvasState` + `repairOrphanGroups` block into it.

For **Open dialog** (`handleLoadWorkflow`): use `useApi().apiCall<WorkflowResponse>(\`workflows/${summary.id}\`)` inside the existing callback (or `queryClient.fetchQuery({ queryKey: queryKeys.workflows.detail(summary.id), queryFn: ... })`). Do not use `fetch`. Then `loadWorkflow({...})` + `canvasFromWorkflowResponse`.

For **mount restore**: same `apiCall` / `fetchQuery` instead of `fetch`. Preserve `hasRehydratedCanvasRef` and draft short-circuit — only replace the transport.

Do not auto-bind `useWorkflowQuery(mountWorkflowId)` as the canvas source of truth; that would fight the unsaved draft. Transport unification only.

## R7.2 Check-name

### Before

Duplicated in:

- `frontend/src/components/features/workflows/dialogs/workflow-save-as-dialog.tsx` (~line 104)
- `frontend/src/components/features/workflows/dialogs/workflow-import-dialog.tsx` (~line 345)

```ts
const res = await fetch(`/api/proxy/workflows/check-name?${params}`, { credentials: "include" });
```

Backend: `GET /api/workflows/check-name?name&folder&visibility&exclude_id` → `WorkflowNameCheckResponse` `{ available, message, existing_id }` (`backend/routers/workflows.py`, `backend/models/workflows.py`).

### After

Add `frontend/src/hooks/queries/use-workflow-check-name.ts`:

```ts
export interface WorkflowNameCheckInput {
  name: string;
  folder: string;
  visibility: string;
  excludeId?: number;
}

export function useWorkflowCheckNameMutation() {
  const { apiCall } = useApi();
  return useMutation({
    mutationFn: (input: WorkflowNameCheckInput) => {
      const params = new URLSearchParams({
        name: input.name,
        folder: input.folder,
        visibility: input.visibility,
      });
      if (input.excludeId !== undefined) {
        params.set("exclude_id", String(input.excludeId));
      }
      return apiCall<WorkflowNameCheckResponse>(
        `workflows/check-name?${params.toString()}`,
      );
    },
  });
}
```

Both dialogs call `mutateAsync` instead of `fetch`. Keep the overwrite-confirm UX.

## R7.3 Login OIDC providers

### Before

`login-page.tsx` `useEffect` + `fetch("/api/proxy/auth/oidc/providers")` into `useState`. Endpoint is public (`backend/routers/oidc.py` `list_providers`, no auth). Response: `{ providers, allow_traditional_login }`.

### After

Add `frontend/src/hooks/queries/use-oidc-providers-query.ts`:

```ts
queryKey: queryKeys.oidc.providers()  // add to query-keys.ts oidc: { debug, providers: () => [...oidc.all, "providers"] }
queryFn: () => apiCall<OidcProvidersResponse>("auth/oidc/providers")
staleTime: 60_000
retry: false
```

`useApi` on 401 redirects to `/login`. This endpoint should not 401; if it 404/503, treat as “OIDC optional” (`placeholderData` / `throwOnError: false` / `queryFn` catch returning `{ providers: [], allow_traditional_login: true }`).

Login page: `const { data } = useOidcProvidersQuery()`; derive `oidcProviders` / `allowTraditionalLogin` with `useMemo`. Delete the `useEffect` fetch.

## Files

- `frontend/src/lib/query-keys.ts`
- `frontend/src/hooks/queries/use-workflow-query.ts` (unchanged unless you add `queryClient.fetchQuery` docs)
- **Add:** `frontend/src/components/features/workflows/utils/apply-loaded-workflow.ts`
- `frontend/src/components/features/workflows/workflow-builder-page.tsx`
- **Add:** `frontend/src/hooks/queries/use-workflow-check-name.ts`
- `frontend/src/components/features/workflows/dialogs/workflow-save-as-dialog.tsx`
- `frontend/src/components/features/workflows/dialogs/workflow-import-dialog.tsx`
- **Add:** `frontend/src/hooks/queries/use-oidc-providers-query.ts`
- `frontend/src/components/features/auth/login-page.tsx`

## Verify

`rg "fetch\\(\`/api/proxy" frontend/src` is empty. `rg "fetch\\('/api/proxy" frontend/src` is empty. Remaining `fetch` only under `lib/auth-store.ts`, `use-session-manager.ts`, `oidc-callback-page.tsx`, and (dev-only) oidc-test pages.

Open workflow, save-as name clash, import name clash, login with OIDC providers listed — all still work. Expired session on Open redirects to `/login`.

---

# R8 — Replace `= []` default props (P1)

## Before

CLAUDE.md forbids default `= []` because it allocates a new array every render.

**Already correct (do not touch):** `EMPTY_*` in `workflow-builder-page.tsx`, `device-selector.tsx`, `node-config-modal.tsx` (`EMPTY_PLUGINS`, `EMPTY_NODES`, `EMPTY_EDGES`), `workflow-properties-panel.tsx`, `workflow-executions-panel.tsx`.

**Violations to fix:**

Source dialogs (prop used in `useCallback` deps — will loop if parent omits the prop):

| File | Line (approx) | Signature |
|---|---|---|
| `features/settings/dialogs/nautobot-source-dialog.tsx` | 70 | `existingSourceIds = []` |
| `features/settings/dialogs/git-source-dialog.tsx` | 76 | same |
| `features/settings/dialogs/ise-source-dialog.tsx` | 80 | same |
| `features/settings/dialogs/pyats-source-dialog.tsx` | 78 | same |

Plugin ConfigPanels (`PluginConfigPanelProps.workflowNodes?` etc.). `NodeConfigModal` always passes `workflowNodes={workflowNodes}` / `workflowEdges={edges}` / `plugins={plugins}`, and its own defaults are already `EMPTY_*`. The ConfigPanel defaults are still wrong if a test or future caller omits them:

| File | Defaults |
|---|---|
| `workflow-steps/deploy-rendered-template/index.tsx` | `workflowNodes = []` |
| `workflow-steps/merge-content/index.tsx` | `workflowNodes = []` |
| `workflow-steps/route-on-content/index.tsx` | `workflowNodes = []` |
| `workflow-steps/store-artifact/index.tsx` | `workflowNodes = []`, `workflowEdges = []`, `plugins = []` |
| `workflow-steps/compare-data/index.tsx` | same three |
| `workflow-steps/filter-output/index.tsx` | same three |

`patch: Record<string, unknown> = {}` on `build*Config` helpers is a **pure function** default, not a React prop. Leave those.

## After

At the top of each source-dialog file:

```ts
const EMPTY_SOURCE_IDS: string[] = [];
```

Use `existingSourceIds = EMPTY_SOURCE_IDS`.

In `frontend/src/components/features/workflows/types/plugin-ui.ts` you cannot put runtime constants. Put shared empties in `frontend/src/components/features/workflows/constants/empty-canvas.ts`:

```ts
import type { PluginDefinition } from "../types/plugin-registry";
import type { PersistedCanvasNode, WorkflowCanvasEdge } from "../types/workflow-canvas";

export const EMPTY_WORKFLOW_NODES: PersistedCanvasNode[] = [];
export const EMPTY_WORKFLOW_EDGES: WorkflowCanvasEdge[] = [];
export const EMPTY_PLUGINS: PluginDefinition[] = [];
```

Point **all** ConfigPanel defaults and `node-config-modal.tsx` / `workflow-builder-page.tsx` existing `EMPTY_NODES` / `EMPTY_EDGES` / `EMPTY_PLUGINS` at this module so there is one canonical empty. Optional in this item: if unifying builder constants is noisy, only fix the six ConfigPanels + four dialogs and leave builder constants local.

## Files

The 10 files in the tables above, plus optional `constants/empty-canvas.ts` and the two files that already define `EMPTY_PLUGINS` if you unify.

## Verify

`rg 'existingSourceIds = \\[\\]|workflowNodes = \\[\\]|workflowEdges = \\[\\]|plugins = \\[\\]' frontend/src` is empty. Open a source create dialog and a compare-data / store-artifact config modal: no infinite loop, no eslint `react-hooks` warning.

---

# R9 — Permission-aware navigation (P1)

Frontend gating is UX only (`lib/permissions.ts`). Backend remains the security boundary.

## Before

`frontend/src/components/layout/app-sidebar.tsx` `navigationItems` has no permission field. Every authenticated user sees Workflows, Inventory, Templates, Runs, Settings.

`settings-topbar.tsx` only hides the **users** tab without `users:read`. Other settings sections are always listed.

`ToolsPage` lists all tools (OIDC handled in R3).

## After

Extend `NavigationItem`:

```ts
type NavigationItem = {
  label: string;
  icon: typeof Workflow;
  href: string;
  isActive: (pathname: string) => boolean;
  canShow: (user: AuthUser | null) => boolean;
};
```

| Item | `canShow` |
|---|---|
| Workflows (`/workflows`) | `hasPermission(user, "workflows", "read")` |
| Inventory (`/inventory`) | `hasPermission(user, "sources.nautobot", "read")` |
| Templates (`/templates`) | `hasPermission(user, "templates", "read")` |
| Runs (`/workflows/runs`) | `hasPermission(user, "workflow_runs", "read")` |
| Settings (`/settings/general`) | `hasPermission(user, "settings", "read") \|\| hasPermission(user, "general_settings", "write") \|\| hasPermission(user, "credentials", "read") \|\| hasPermission(user, "users", "read") \|\| hasPermission(user, "hatchet_settings", "read") \|\| hasPermission(user, "cache_settings", "read") \|\| hasPermission(user, "logging_settings", "read")` |

Filter with `navigationItems.filter((item) => item.canShow(user))`.

`SETTINGS_SECTIONS` (`frontend/src/components/features/settings/constants/settings-sections.ts`): add `canShow(user)` per id:

| Section id | Permission |
|---|---|
| `general` | `general_settings:write` **or** `settings:read` (page also loads general settings; if only `settings:read`, the general canvas may 403 — hide unless `general_settings:write` OR keep visible and let the canvas show the API error. Prefer hide unless `general_settings:write` \|\| `settings:read`.) |
| `sources` | `settings:read` (Nautobot/Git live in `/settings`; ISE/pyATS have their own resources — user with `settings:read` can list keys. Also show if `sources.ise:read` \|\| `sources.pyats:read` \|\| `sources.nautobot:read` \|\| `sources.git:read`.) |
| `credentials` | `credentials:read` |
| `users` | `users:read` (already) |
| `hatchet` | `hatchet_settings:read` |
| `redis` | `cache_settings:read` |
| `logging` | `logging_settings:read` |

`settings-topbar.tsx`: `SETTINGS_SECTIONS.filter((s) => s.canShow(currentUser))`.

`settings/[section]/page.tsx` stays a stub. Optional: in `SettingsPage`, if `!canShow(section)` render a “no permission” empty state instead of a 403 toast storm. Do that in `frontend/src/components/features/settings/settings-page.tsx`.

Do **not** add Tools to the main sidebar.

## Files

- `frontend/src/components/layout/app-sidebar.tsx`
- `frontend/src/components/features/settings/constants/settings-sections.ts`
- `frontend/src/components/features/settings/types/settings-section.ts` (if the section type needs `canShow`)
- `frontend/src/components/features/settings/components/settings-topbar.tsx`
- `frontend/src/components/features/settings/settings-page.tsx`

## Verify

Log in as a user with only `workflows:read` + `workflow_runs:read`: sidebar shows Workflows + Runs only. Direct `/inventory` still hits the dashboard layout (cookie ok) then API 403 — acceptable. Settings tabs match permissions.

---

# R10 — `error.tsx` and canvas error boundary (P1)

## Before

No `frontend/src/app/**/error.tsx`, no `loading.tsx`, no React `ErrorBoundary`. A throw in the builder or Monaco takes down the whole client tree.

## After

1. `frontend/src/app/(dashboard)/error.tsx` — Client Component (`'use client'` required by Next.js):

```tsx
"use client";
export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // Shadcn Card + Button “Try again” calling reset(); do not render error.message in production
}
```

2. `frontend/src/app/(dashboard)/loading.tsx` — simple full-pane spinner using existing Tailwind (`animate-spin` + `Loader2`). Optional but cheap.

3. Canvas boundary: add `frontend/src/components/features/workflows/components/canvas-error-boundary.tsx` (class component or `react-error-boundary` — **do not add a new dependency**; use a small class boundary). Wrap `<WorkflowCanvas ...>` inside `workflow-builder-page.tsx` (after R11, wrap in the composer). Fallback: “The canvas failed to render” + button that calls `resetToNew` or `window.location.reload()`. Do not wrap the whole dashboard — keep the sidebar usable.

4. Same boundary around `<CodeEditorPanel>` in `template-editor-page.tsx` (Monaco).

## Files

- **Add:** `frontend/src/app/(dashboard)/error.tsx`
- **Add:** `frontend/src/app/(dashboard)/loading.tsx`
- **Add:** `frontend/src/components/features/workflows/components/canvas-error-boundary.tsx`
- **Edit:** `workflow-builder-page.tsx` (or the composer after R11)
- **Edit:** `template-editor-page.tsx`

## Verify

Temporarily throw in `WorkflowCanvas`: sidebar remains, fallback UI shows, Try again works. Happy path unchanged.

---

# R11 — Split `workflow-builder-page.tsx` (P1)

Do this **after R7**. Behaviour must not change. No CSS/UX work.

## Before

One component `WorkflowBuilderPage` in `frontend/src/components/features/workflows/workflow-builder-page.tsx` (~1421 lines). State and handlers:

**Dialog / flags:** `isSaveAsOpen`, `isOpenDialogOpen`, `isOpenConfirmOpen`, `isManageOpen`, `isNewConfirmOpen`, `isRunConfirmOpen`, `openAfterSave`, `runAfterSave`, `isRunInputsDialogOpen`, `pendingRunTargetId`.

**Canvas state:** `allNodes`, `allEdges`, `groups`, `staticAttributes`, `mountWorkflowId`, `initialCanvasDraft`, `hasRehydratedCanvasRef`, viewport ref, unmount `setCanvasDraft`.

**Handlers to move with canvas state:**  
`handleViewportChange`, `handleNodesChange`, `handleEdgesChange`, `handleConnect`, `handleEdgeStyleChange`, `handleEdgeLabelChange`, `handleEdgeStartLabelChange`, `handleEdgeEndLabelChange`, `handleEdgeLabelBoldChange`, `handleEdgeLabelFontSizeChange`, `handleNodeTitleChange`, `handleIncomeHandleSideChange`, `handleOutcomeHandleSideChange`, `handleAlignNodes`, `handleNodeConfigChange`, `handleAddStep`, `handleAddStepAtPosition`, `handleDeleteNodes`, `handleDeleteEdge`, `handleDuplicateNode`, `handleGroupSelectedSteps`, `handleRenameGroup`, `handleUngroupGroup`, `handleOpenGroup`, `handleStaticAttributesChange`.

**Persistence:** `handleNew`, `handleSave`, `handleSaveAs`, `handleOverwrite`, `handleOpen`, `handleSaveAndOpen`, `handleDiscardAndOpen`, `handleLoadWorkflow`, mount restore effect.

**Run:** `handleRun`, `handleSaveAndRun`, `handleRunSavedVersion`, `handleRunInputsSubmit`.

Zustand store `use-workflow-builder-store.ts` stays the source of workflow metadata (`workflowId`, dirty, draft, selection, groups navigation). Do not move canvas arrays into Zustand in this split (that is a separate, larger change).

## After

| New file | Exports | Contains |
|---|---|---|
| `features/workflows/hooks/use-workflow-canvas.ts` | `useWorkflowCanvas(...)` | Canvas `useState`, React Flow handlers, group/align/add/delete/duplicate, unmount draft snapshot, `apply-loaded-workflow` setter used by persistence |
| `features/workflows/hooks/use-workflow-persistence.ts` | `useWorkflowPersistence(...)` | save/load/new/open/overwrite, mount restore via `apiCall`/`fetchQuery` from R7, save-as dialog flags that only persistence needs |
| `features/workflows/hooks/use-workflow-run-actions.ts` | `useWorkflowRunActions(...)` | run confirm + run-inputs dialog + `useTriggerRunMutation` |
| `features/workflows/workflow-builder-page.tsx` | `WorkflowBuilderPage` | Compose hooks + `WorkflowTopbar` + `WorkflowCanvas` + `WorkflowPropertiesPanel` + dialogs + `CanvasErrorBoundary`. Target ≤ 250 lines. |

`useWorkflowCanvas` return must be `useMemo`’d (CLAUDE.md custom-hook rule) or the page must destructure stable callbacks.

Pass into `NodeConfigModal` the same props as today: `nodes={allNodes}` `edges={allEdges}` `plugins={plugins}` `workflowNodes={allNodes}` plus the node change handlers.

Route stub `app/(dashboard)/workflows/page.tsx` stays `{ <WorkflowBuilderPage /> }`.

## Files

- **Add:** the three hooks above
- **Edit:** `workflow-builder-page.tsx` (shrink)
- Reuse: `utils/apply-loaded-workflow.ts` from R7

## Verify

Manual: create workflow, add steps, group, save, reload, open, unsaved-guard, run, draft survives visiting `/workflows/runs` and back. No visual change. Line count of the page file < 300.

---

# R12 — Split `step-result-viewer.tsx` (P1)

Move-only. Do not change markup, class names, or data mapping.

## Before

`frontend/src/components/features/workflows/components/step-result-viewer.tsx` (~1181 lines) defines (in order):

| Symbol | Kind |
|---|---|
| `isDebugLogsPayload`, `extractDebugLogs`, `DebugLogsPanel` | debug logs |
| `isLogAttributesPayload`, `extractLogAttributes`, `LogAttributesPanel` | log-attributes |
| `formatLogValue` | helper |
| `summarizeDeviceStatuses`, `DeviceStatusSummary`, `DevicesSection`, `DeviceStatusIcon` | device list chrome |
| `CapabilityBadges` | badges |
| `ArtifactRefRow` | artifact |
| `isParsedTemplateEntry`, `getParsedTemplateEntries` | parsed template |
| `isComparisonResultEntry`, `isComparisonDiffEntry`, `getComparisonResultEntries`, `getComparisonDiffEntries` | compare-data |
| `isGenieParsedConfigEntry`, `getGenieParsedConfigEntries` | genie |
| `ConfigArtifactPanel` | artifact body |
| `DeviceConfigsContent` | running/startup |
| `DeviceParsedTemplatesContent` | templates |
| `DeviceGenieConfigContent` | genie view |
| `DeviceComparisonDiffsContent` | diffs |
| `DeviceCommandResultsContent` | commands |
| `DeviceErrorList` (**exported**) | errors |
| `DeviceCard` | per-device |
| `MetadataPanel` | metadata |
| `OutcomeContextView` | outcome |
| `StepResultViewer` (**exported**) | orchestrator |

Imports today: `useArtifactQuery`, `parseStepOutput`, `StepErrorAlert`, types from `workflow-context-types` / `workflow-runs`.

Callers import `{ StepResultViewer, DeviceErrorList }` from this module. Keep those two export paths working (`index.ts` re-export).

## After

```
features/workflows/components/step-result-viewer/
  index.tsx                      # StepResultViewer orchestrator only (~150–200 lines)
  types.ts                       # payload interfaces currently in the file
  format-log-value.ts
  debug-logs-panel.tsx           # extract* + DebugLogsPanel
  log-attributes-panel.tsx
  devices-section.tsx            # summary + DevicesSection + DeviceStatusIcon
  capability-badges.tsx
  artifact-ref-row.tsx
  config-artifact-panel.tsx
  device-configs-content.tsx
  device-parsed-templates-content.tsx
  device-genie-config-content.tsx
  device-comparison-diff-content.tsx
  device-command-results-content.tsx
  device-error-list.tsx          # export DeviceErrorList
  device-card.tsx
  metadata-panel.tsx
  outcome-context-view.tsx
  parsed-guards.ts               # isParsedTemplateEntry / get* helpers
```

`index.tsx` re-exports `StepResultViewer` and `DeviceErrorList`.

Grep importers (`StepResultViewer`, `DeviceErrorList`) and point them at `.../step-result-viewer` (folder index). Delete the old single file.

## Files

- **Add:** folder above
- **Delete:** `features/workflows/components/step-result-viewer.tsx`
- **Edit:** any importer (search `from \"./step-result-viewer\"` and `from \"@/components/features/workflows/components/step-result-viewer\"`)

Known likely importers: `step-result-row.tsx`, `run-detail-pane.tsx` (confirm with grep; do not miss any).

## Verify

Open a completed run with command output, config backup, compare-data, debug logs, errors: identical UI. `DeviceErrorList` still compiles wherever it is used.

---

# R13 — Memoize mutation-hook return objects (P1)

## Before

CLAUDE.md: custom hooks must `useMemo` their returned object.

These hooks `return { createX, updateX, ... }` as a new object every render:

| File |
|---|
| `frontend/src/hooks/queries/use-settings-mutations.ts` |
| `frontend/src/hooks/queries/use-workflow-mutations.ts` |
| `frontend/src/hooks/queries/use-workflow-schedule-mutations.ts` |
| `frontend/src/hooks/queries/use-certificates-mutations.ts` |
| `frontend/src/hooks/queries/use-schema-mutations.ts` |
| `frontend/src/hooks/queries/use-logging-settings-mutations.ts` |
| `frontend/src/hooks/queries/use-pyats-sources-mutations.ts` |
| `frontend/src/hooks/queries/use-hatchet-settings-mutations.ts` |
| `frontend/src/hooks/queries/use-redis-settings-mutations.ts` |
| `frontend/src/hooks/queries/use-ise-sources-mutations.ts` |
| `frontend/src/hooks/queries/use-general-settings-mutations.ts` |
| `frontend/src/components/features/templates/hooks/use-template-mutations.ts` |
| `frontend/src/components/features/settings/credentials/hooks/use-credential-mutations.ts` |
| `frontend/src/components/features/settings/permissions/hooks/use-users-mutations.ts` |
| `frontend/src/components/features/settings/permissions/hooks/use-rbac-roles-mutations.ts` |
| `frontend/src/components/features/settings/permissions/hooks/use-rbac-permissions-mutations.ts` |
| `frontend/src/components/features/settings/permissions/hooks/use-rbac-user-access-mutations.ts` |

Hooks that already `return useMutation(...)` (single mutation) are fine (`use-saved-inventory-mutations.ts` returns individual hooks, `useTriggerRunMutation`, etc.).

## After

```ts
return useMemo(
  () => ({ createSetting, updateSetting, deleteSetting, upsertSetting }),
  [createSetting, updateSetting, deleteSetting, upsertSetting],
);
```

Same pattern for every table row. Import `useMemo` from React.

## Verify

`rg -n "return \\{ create|return \\{ saveSettings|return \\{ upload" frontend/src/hooks frontend/src/components/features` — each match is inside `useMemo`. No new render loops on settings pages.

---

# R14 — Query-key factory nits (P1)

## Before

`use-workflow-run-mutations.ts` invalidates with:

```ts
queryKey: [...queryKeys.workflowRuns.all, "list", workflowId]
```

eight times. That prefix is correct for filter variants (`list(workflowId, filtersKey)`), but it is an inline key.

`use-workflow-runs-query.ts` when `workflowId` is null:

```ts
queryKey: workflowId ? queryKeys.workflowRuns.list(...) : ["workflow-runs", "disabled"]
```

## After

In `query-keys.ts` `workflowRuns`:

```ts
listPrefix: (workflowId: number) =>
  [...queryKeys.workflowRuns.all, "list", workflowId] as const,
```

Replace all eight mutation invalidations with `queryKeys.workflowRuns.listPrefix(id)`.

Replace the disabled key with `queryKeys.workflowRuns.all` and `enabled: !!workflowId` (already present). Do not use a string `"disabled"` sentinel.

## Files

- `frontend/src/lib/query-keys.ts`
- `frontend/src/hooks/queries/use-workflow-run-mutations.ts`
- `frontend/src/hooks/queries/use-workflow-runs-query.ts`

## Verify

Trigger/cancel/delete run still refreshes the list including active filters. No fetch when `workflowId` is null.

---

# R15 — Tests that lock R1 / R2 / R5 (P1)

There is no frontend test runner today (`frontend/package.json` has no `test` script). Do **not** add Playwright in this item unless you are willing to add the dependency. Prefer:

## After

1. **Node built-in test** for pure TS (no new deps): add `frontend/src/lib/api-proxy.test.ts` and `frontend/src/lib/oidc-state.test.ts`. Script in `frontend/package.json`:

```json
"test": "node --import tsx --test src/lib/api-proxy.test.ts src/lib/oidc-state.test.ts"
```

If `tsx` is undesirable, compile with `tsc` into a temp dir, or add `vitest` as a devDependency — pick **one** and use it for all three files. Recommended: `vitest` (already in the Next ecosystem; one devDependency).

Cases:

**`normalizeProxyPath` (export from R5)**

- `["workflows", "1"]` → `/api/workflows/1`
- `["api", "auth", "me"]` → `/api/auth/me`
- `["sources", "ise", "lab", "devices", "ndg", "myGroup#x"]` — `#` encoded, not treated as fragment
- `[".."]`, `["foo", ".."]`, `[""]`, `["."]` throw

**`parseAndVerifyOidcState` (R1)**

- `(null, "lab:abc")` → `{ ok: false }`
- `("lab:abc", "lab:abc")` → `{ ok: true, providerId: "lab" }`
- `("lab:abc", "lab:evil")` → `{ ok: false }`
- `("lab:abc", "LAB:abc")` → `{ ok: false }`
- `("not-a-provider", "not-a-provider")` → `{ ok: false }` (fails `PROVIDER_ID_RE` because of missing prefix form — incoming without `:` already fails provider parse)

**Backend R2** (pytest, existing runner):

- `test_settings_token_redaction.py`: GET list/detail never includes a non-empty `token` for `sources.nautobot.*` / `sources.git.*`; `token_configured` true when stored token exists; PUT with `token: ""` keeps previous token; POST create with token persists (assert via `get_source_config`, not via GET response).
- One API test: `GET /api/sources/nautobot/custom-fields` without `source_id` → 422; with `source_id` of a fixture source → does not require `nautobot_token` query param.

## Files

- **Add:** `frontend/src/lib/api-proxy.test.ts`
- **Add:** `frontend/src/lib/oidc-state.test.ts`
- **Add:** `backend/tests/unit/test_settings_token_redaction.py`
- **Edit:** `frontend/package.json` scripts
- **Edit:** existing nautobot ops tests if any assert query `nautobot_token` (none found under `backend/tests` as of 2026-08-13; re-grep when implementing)

## Verify

`cd frontend && npm test` and `cd backend && python -m pytest tests/unit/test_settings_token_redaction.py` pass in CI.

---

## Implementation notes (do not skip)

- R2 is the only item that **must** ship backend + frontend together. A frontend-only “stop putting token in the query string but still POST it” is an acceptable **hotfix** if R2.1/R2.2 slip, but it is not the After-state of this plan. Do not leave that hotfix in place.
- After R2, `rg nautobot_token frontend/src` must be empty.
- After R7, builder mount/open must not use `fetch('/api/proxy/...')`.
- After R11/R12, do not mix behaviour changes into the split PRs.
- `ENABLE_DEV_TOOLS` defaults off: local `.env` / `.env.local` for developers who need `/tools/oidc-test`; production compose files must omit it.
