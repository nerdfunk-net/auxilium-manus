import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAME, clearAuthCookie, type AuthUser } from "@/lib/auth";
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

  const body = await request.text();
  const backendResponse = await proxyRequest({
    authorization: `Bearer ${token}`,
    body,
    path: ["api", "auth", "change-password"],
    request,
  });

  if (!backendResponse.ok) {
    if (backendResponse.status === 401 || backendResponse.status === 403) {
      clearAuthCookie(cookieStore);
      return NextResponse.json({ message: "Authentication required" }, { status: 401 });
    }

    if (backendResponse.status === 400 || backendResponse.status === 429) {
      // Surface the backend's own message ("Current password is incorrect",
      // password-policy text, rate-limit text) so the dialog toast is useful.
      const message = await extractMessage(backendResponse);
      return NextResponse.json({ message }, { status: backendResponse.status });
    }

    return NextResponse.json(
      { message: "Password change service unavailable" },
      { status: 502 },
    );
  }

  const sessionPayload = await parseSessionResponse(backendResponse);
  if (!sessionPayload) {
    return NextResponse.json(
      { message: "Invalid authentication service response" },
      { status: 502 },
    );
  }

  cookieStore.set(AUTH_COOKIE_NAME, sessionPayload.access_token, {
    httpOnly: true,
    maxAge: sessionPayload.expires_in,
    path: "/",
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
  });

  return NextResponse.json({ user: sessionPayload.user });
}

async function extractMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown; message?: unknown };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (typeof payload.message === "string") {
      return payload.message;
    }
  } catch {
    // fall through
  }
  return "Could not change password";
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
