import { cookies } from "next/headers";
import { notFound } from "next/navigation";

import { proxyRequest } from "@/lib/api-proxy";
import { AUTH_COOKIE_NAME } from "@/lib/auth";
import type { AuthUser } from "@/lib/auth";

/**
 * Server-side companion to lib/permissions.ts's hasPermission — used only to
 * avoid rendering (and firing status queries for) admin-only tool pages for
 * users who lack the permission. The backend remains the real enforcement
 * point; this is defense in depth, not a new security boundary.
 */
export async function requirePermissionOr404(resource: string, action: string): Promise<void> {
  const cookieStore = await cookies();
  const token = cookieStore.get(AUTH_COOKIE_NAME)?.value;

  const userResponse = await proxyRequest({
    authorization: token ? `Bearer ${token}` : undefined,
    path: ["api", "auth", "me"],
    request: new Request("http://next.internal/api/proxy/api/auth/me"),
  });

  if (!userResponse.ok) {
    notFound();
  }

  const user = (await userResponse.json()) as AuthUser;
  if (!user.permissions.includes(`${resource}:${action}`)) {
    notFound();
  }
}
