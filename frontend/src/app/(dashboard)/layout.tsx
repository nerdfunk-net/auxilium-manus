import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AUTH_COOKIE_NAME } from "@/lib/auth";
import { proxyRequest } from "@/lib/api-proxy";

export default async function DashboardLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  const cookieStore = await cookies();

  if (!cookieStore.has(AUTH_COOKIE_NAME)) {
    redirect("/login");
  }

  const token = cookieStore.get(AUTH_COOKIE_NAME)?.value;
  const userResponse = await proxyRequest({
    authorization: `Bearer ${token}`,
    path: ["api", "auth", "me"],
    request: new Request("http://next.internal/api/proxy/api/auth/me"),
  });

  if (!userResponse.ok) {
    redirect("/login");
  }

  return children;
}
