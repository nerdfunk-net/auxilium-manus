# API proxy pattern

The frontend and backend run on different TCP ports (3000 and 8000). Allowing the browser to call the backend directly creates several problems: CORS configuration, exposed internal ports, and split-origin token handling. The API proxy pattern eliminates all of these by routing every API call through the Next.js server.

## How it works

```
Browser  →  Next.js :3000/api/proxy/*  →  Backend :8000/api/*
              ↑ public                        ↑ internal only
```

The browser never talks to port 8000. It sends all requests to `/api/proxy/<path>`, which is a Next.js Route Handler running on the same origin as the page. Next.js forwards the request to the backend server-to-server and returns the response to the browser.

## Implementation

### Proxy route handler

`frontend/src/app/api/proxy/[...path]/route.ts` catches all HTTP methods under `/api/proxy/*` and calls `handleRequest`:

```
handleRequest
  1. Reconstruct the target URL from BACKEND_URL + path + query string
  2. Copy selected request headers (Authorization, Content-Type, Accept, …)
  3. Forward the request to the backend with fetch()
  4. Return the backend response to the browser
     - JSON responses:  NextResponse.json(data)
     - Binary/file downloads (YAML, CSV, ZIP): pass through as blob
     - 204 No Content: return empty 204
     - 503 if the backend is unreachable
```

The backend URL is read from the `BACKEND_URL` environment variable, which is only visible to the Next.js server process:

```bash
# frontend/.env.local
BACKEND_URL=http://localhost:8000
```

In a containerised deployment `BACKEND_URL` points to an internal hostname such as `http://backend:8000` that is not reachable from outside the network.

### Client-side API hook

`frontend/src/hooks/use-api.ts` provides the `useApi` hook that all components use to make API calls:

```ts
const { apiCall } = useApi()
const data = await apiCall('devices', { method: 'GET' })
```

Internally, `apiCall` always prefixes the endpoint with `/api/proxy/` so components never construct backend URLs directly. The hook also:

- Attaches the JWT `Authorization` header from the Zustand auth store.
- Redirects to `/login` on a 401 response.
- Throws a descriptive error on 403.

## URL routing in the proxy

| Browser calls | Proxy forwards to |
|---|---|
| `/api/proxy/devices` | `BACKEND_URL/api/devices` |
| `/api/proxy/api/something` | `BACKEND_URL/api/something` (no double prefix) |
| `/api/proxy/auth/login` | `BACKEND_URL/api/auth/login` |
| `/api/proxy/profile` | `BACKEND_URL/api/profile` |

Paths that already start with `/api/` are forwarded as-is. All other proxy paths
are treated as backend API resources and receive the `/api/` prefix.

## Advantages

**No CORS configuration required.** The browser talks to the same origin as the page (`/api/proxy/*`), so the browser never sends a cross-origin request. The backend does not need `Access-Control-Allow-Origin` headers.

**Backend port stays internal.** Port 8000 does not have to be exposed to the network at all. In Docker, the backend container can be on an internal network with no published ports.

**Token handling is straightforward.** The JWT token is attached to requests on the same origin, which is simpler and safer than managing cross-origin credentials or cookies with `SameSite` policies.

**Single entry point.** Load balancers and firewalls only need to expose port 3000. All traffic, including API calls, enters through the Next.js server.

**Transparent to components.** Components call `apiCall('resource')` and do not know or care where the backend is. Changing the backend address only requires updating `BACKEND_URL`.

## Rule

Never call the backend directly from the browser. Always go through `/api/proxy/*` via the `useApi` hook.
