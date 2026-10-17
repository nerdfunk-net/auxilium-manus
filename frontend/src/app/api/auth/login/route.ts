import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { setAuthCookie, type AuthUser } from "@/lib/auth";
import { proxyRequest } from "@/lib/api-proxy";
import { parseAuthUser } from "@/lib/auth-response-parser";

interface BackendTokenResponse {
  access_token: string;
  expires_in: number;
}

export async function POST(request: Request) {
  let credentials: unknown;

  try {
    credentials = await request.json();
  } catch {
    return NextResponse.json({ message: "Invalid request body" }, { status: 400 });
  }

  const tokenResponse = await proxyRequest({
    body: JSON.stringify(credentials),
    path: ["api", "auth", "login"],
    request,
  });

  if (!tokenResponse.ok) {
    if (tokenResponse.status === 429) {
      return NextResponse.json(
        { message: "Too many login attempts" },
        { status: 429 },
      );
    }

    if (tokenResponse.status === 401) {
      return NextResponse.json(
        { message: "Invalid username or password" },
        { status: 401 },
      );
    }

    return NextResponse.json(
      { message: "Authentication service unavailable" },
      { status: 502 },
    );
  }

  const tokenPayload = await parseTokenResponse(tokenResponse);

  if (!tokenPayload) {
    return NextResponse.json(
      { message: "Invalid authentication service response" },
      { status: 502 },
    );
  }

  const userResponse = await proxyRequest({
    authorization: `Bearer ${tokenPayload.access_token}`,
    path: ["api", "auth", "me"],
    request: new Request("http://next.internal/api/proxy/api/auth/me"),
  });

  if (!userResponse.ok) {
    return NextResponse.json(
      { message: "Could not load authenticated user" },
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

  const cookieStore = await cookies();
  setAuthCookie(cookieStore, tokenPayload.access_token, tokenPayload.expires_in, request);

  return NextResponse.json({ user, expires_in: tokenPayload.expires_in });
}

async function parseTokenResponse(response: Response): Promise<BackendTokenResponse | null> {
  let payload: Partial<BackendTokenResponse>;

  try {
    payload = (await response.json()) as Partial<BackendTokenResponse>;
  } catch {
    return null;
  }

  if (
    typeof payload.access_token !== "string" ||
    typeof payload.expires_in !== "number"
  ) {
    return null;
  }

  return {
    access_token: payload.access_token,
    expires_in: payload.expires_in,
  };
}

async function parseUserResponse(response: Response): Promise<AuthUser | null> {
  try {
    return parseAuthUser(await response.json());
  } catch {
    return null;
  }
}
