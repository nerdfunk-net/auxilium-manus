import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAME, type AuthUser } from "@/lib/auth";
import { proxyRequest } from "@/lib/api-proxy";
import { parseAuthUser } from "@/lib/auth-response-parser";

interface BackendTokenResponse {
  access_token: string;
  expires_in: number;
}

interface BackendApprovalPendingResponse {
  status: "approval_pending";
  username: string;
  email?: string;
  oidc_provider: string;
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ provider: string }> },
) {
  const { provider } = await params;

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ message: "Invalid request body" }, { status: 400 });
  }

  const backendResponse = await proxyRequest({
    body: JSON.stringify(body),
    path: ["api", "auth", "oidc", provider, "callback"],
    request,
  });

  if (!backendResponse.ok) {
    if ([400, 401, 403].includes(backendResponse.status)) {
      const errorPayload = await parseErrorResponse(backendResponse);
      return NextResponse.json(
        { message: errorPayload || "Authentication failed" },
        { status: backendResponse.status },
      );
    }

    return NextResponse.json(
      { message: "Authentication service unavailable" },
      { status: 502 },
    );
  }

  const approvalPending = await parseApprovalPendingResponse(backendResponse);
  if (approvalPending) {
    return NextResponse.json(approvalPending);
  }

  const tokenPayload = await parseTokenResponse(backendResponse);
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
  cookieStore.set(AUTH_COOKIE_NAME, tokenPayload.access_token, {
    httpOnly: true,
    maxAge: tokenPayload.expires_in,
    path: "/",
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
  });

  return NextResponse.json({ user });
}

async function parseErrorResponse(response: Response): Promise<string | null> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    return typeof payload.detail === "string" ? payload.detail : null;
  } catch {
    return null;
  }
}

async function parseApprovalPendingResponse(
  response: Response,
): Promise<BackendApprovalPendingResponse | null> {
  let payload: Partial<BackendApprovalPendingResponse>;

  try {
    payload = (await response.clone().json()) as Partial<BackendApprovalPendingResponse>;
  } catch {
    return null;
  }

  if (payload.status !== "approval_pending" || typeof payload.username !== "string") {
    return null;
  }

  return {
    email: typeof payload.email === "string" ? payload.email : undefined,
    oidc_provider: typeof payload.oidc_provider === "string" ? payload.oidc_provider : "",
    status: "approval_pending",
    username: payload.username,
  };
}

async function parseTokenResponse(response: Response): Promise<BackendTokenResponse | null> {
  let payload: Partial<BackendTokenResponse>;

  try {
    payload = (await response.json()) as Partial<BackendTokenResponse>;
  } catch {
    return null;
  }

  if (typeof payload.access_token !== "string" || typeof payload.expires_in !== "number") {
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
