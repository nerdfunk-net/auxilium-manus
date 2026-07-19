import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAME, type AuthUser } from "@/lib/auth";
import { proxyRequest } from "@/lib/api-proxy";

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
      cookieStore.delete(AUTH_COOKIE_NAME);

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

  cookieStore.set(AUTH_COOKIE_NAME, sessionPayload.access_token, {
    httpOnly: true,
    maxAge: sessionPayload.expires_in,
    path: "/",
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
  });

  return NextResponse.json({ user: sessionPayload.user });
}

async function parseSessionResponse(
  response: Response,
): Promise<BackendSessionResponse | null> {
  let payload: Partial<BackendSessionResponse>;

  try {
    payload = (await response.json()) as Partial<BackendSessionResponse>;
  } catch {
    return null;
  }

  if (
    typeof payload.access_token !== "string" ||
    typeof payload.expires_in !== "number" ||
    !payload.user ||
    typeof payload.user.id !== "number" ||
    typeof payload.user.username !== "string" ||
    typeof payload.user.is_active !== "boolean" ||
    !Array.isArray(payload.user.roles) ||
    !Array.isArray(payload.user.permissions)
  ) {
    return null;
  }

  return {
    access_token: payload.access_token,
    expires_in: payload.expires_in,
    user: {
      id: payload.user.id,
      is_active: payload.user.is_active,
      roles: payload.user.roles,
      permissions: payload.user.permissions,
      username: payload.user.username,
    },
  };
}
