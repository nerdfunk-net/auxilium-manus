import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAME, type AuthUser } from "@/lib/auth";
import { proxyRequest } from "@/lib/api-proxy";

export async function GET(request: Request) {
  const cookieStore = await cookies();
  const token = cookieStore.get(AUTH_COOKIE_NAME)?.value;

  if (!token) {
    return NextResponse.json({ message: "Authentication required" }, { status: 401 });
  }

  const userResponse = await proxyRequest({
    authorization: `Bearer ${token}`,
    path: ["api", "auth", "me"],
    request,
  });

  if (!userResponse.ok) {
    if (userResponse.status === 401 || userResponse.status === 403) {
      cookieStore.delete(AUTH_COOKIE_NAME);

      return NextResponse.json(
        { message: "Authentication required" },
        { status: userResponse.status },
      );
    }

    return NextResponse.json(
      { message: "Authentication service unavailable" },
      { status: 502 },
    );
  }

  const user = await parseUserResponse(userResponse);

  if (!user) {
    return NextResponse.json(
      { message: "Invalid authentication service response" },
      { status: 502 },
    );
  }

  return NextResponse.json({ user });
}

async function parseUserResponse(response: Response): Promise<AuthUser | null> {
  let payload: Partial<AuthUser>;

  try {
    payload = (await response.json()) as Partial<AuthUser>;
  } catch {
    return null;
  }

  if (
    typeof payload.id !== "number" ||
    typeof payload.username !== "string" ||
    typeof payload.permissions !== "number" ||
    typeof payload.is_active !== "boolean"
  ) {
    return null;
  }

  return {
    id: payload.id,
    is_active: payload.is_active,
    permissions: payload.permissions,
    username: payload.username,
  };
}
