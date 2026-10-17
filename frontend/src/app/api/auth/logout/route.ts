import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAME, clearAuthCookie, cookieSecure } from "@/lib/auth";
import { isSameOriginRequest } from "@/lib/same-origin";
import { proxyRequest } from "@/lib/api-proxy";

export async function POST(request: Request) {
  if (!isSameOriginRequest(request)) {
    return NextResponse.json({ message: "Cross-origin request refused" }, { status: 403 });
  }
  const cookieStore = await cookies();
  const token = cookieStore.get(AUTH_COOKIE_NAME)?.value;
  // scope=local (idle timeout of one browser) only clears this browser's cookie; every other
  // sign-out revokes all of the user's sessions (S1-05).
  const scope = new URL(request.url).searchParams.get("scope") === "local" ? "local" : "global";

  if (token && scope === "global") {
    // Best-effort server-side revoke (bumps token_version so every other
    // session for this user dies). The cookie is cleared locally regardless.
    try {
      await proxyRequest({
        authorization: `Bearer ${token}`,
        path: ["api", "auth", "logout"],
        request,
      });
    } catch {
      // logout must never fail on the client
    }
  }

  clearAuthCookie(cookieStore, cookieSecure(request));
  return NextResponse.json({ ok: true });
}
