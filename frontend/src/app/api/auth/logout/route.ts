import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAME, clearAuthCookie } from "@/lib/auth";
import { proxyRequest } from "@/lib/api-proxy";

export async function POST(request: Request) {
  const cookieStore = await cookies();
  const token = cookieStore.get(AUTH_COOKIE_NAME)?.value;

  if (token) {
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

  clearAuthCookie(cookieStore);
  return NextResponse.json({ ok: true });
}
