/**
 * CSRF defence in depth (S1-09): the auth cookie is SameSite=Lax, and this adds an explicit
 * check for state-changing requests. `Sec-Fetch-Site` (all current browsers) is primary; the
 * `Origin` header compared with the host is the fallback. A request with neither header is a
 * non-browser client, which has no ambient cookie to abuse.
 */
export function isSameOriginRequest(request: Request): boolean {
  if (["GET", "HEAD", "OPTIONS"].includes(request.method)) {
    return true;
  }
  const site = request.headers.get("sec-fetch-site");
  if (site) {
    return site === "same-origin" || site === "none";
  }
  const origin = request.headers.get("origin");
  if (!origin) {
    return true;
  }
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}
