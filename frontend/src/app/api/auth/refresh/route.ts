import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAME, clearAuthCookie, cookieSecure, setAuthCookie, type AuthUser } from "@/lib/auth";
import { proxyRequest } from "@/lib/api-proxy";
import { parseAuthUser } from "@/lib/auth-response-parser";

interface BackendSessionResponse {
  access_token: string;
  expires_in: number;
  user: AuthUser;
}

export async function POST(request: Request) {
  const cookieStore = await cookies();
  const token = cookieStore.get(AUTH_COOKIE_NAME)?.value;

  if (!token) {
    return NextResponse.json({ message: "Authentication required" }, { status: 401 });
  }

  const sessionResponse = await proxyRequest({
    authorization: `Bearer ${token}`,
    path: ["api", "auth", "refresh"],
    request,
  });

  if (!sessionResponse.ok) {
    if (sessionResponse.status === 401 || sessionResponse.status === 403) {
      clearAuthCookie(cookieStore, cookieSecure(request));

      return NextResponse.json(
        { message: "Authentication required" },
        { status: 401 },
      );
    }

    return NextResponse.json(
      { message: "Authentication service unavailable" },
      { status: 502 },
    );
  }

  const sessionPayload = await parseSessionResponse(sessionResponse);

  if (!sessionPayload) {
    return NextResponse.json(
      { message: "Invalid authentication service response" },
      { status: 502 },
    );
  }

  setAuthCookie(cookieStore, sessionPayload.access_token, sessionPayload.expires_in, request);

  return NextResponse.json({
    user: sessionPayload.user,
    expires_in: sessionPayload.expires_in,
  });
}

async function parseSessionResponse(
  response: Response,
): Promise<BackendSessionResponse | null> {
  let payload: { access_token?: unknown; expires_in?: unknown; user?: unknown };

  try {
    payload = (await response.json()) as typeof payload;
  } catch {
    return null;
  }

  if (typeof payload.access_token !== "string" || typeof payload.expires_in !== "number") {
    return null;
  }

  const user = parseAuthUser(payload.user);
  if (!user) {
    return null;
  }

  return {
    access_token: payload.access_token,
    expires_in: payload.expires_in,
    user,
  };
}
