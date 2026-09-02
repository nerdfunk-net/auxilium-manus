import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAME, clearAuthCookie, type AuthUser } from "@/lib/auth";
import { proxyRequest } from "@/lib/api-proxy";
import { parseAuthUser } from "@/lib/auth-response-parser";

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
      clearAuthCookie(cookieStore);

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
  try {
    return parseAuthUser(await response.json());
  } catch {
    return null;
  }
}
