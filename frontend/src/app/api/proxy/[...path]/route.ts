import { NextResponse } from "next/server";

import { proxyRequest } from "@/lib/api-proxy";

interface ProxyRouteContext {
  params: Promise<{
    path: string[];
  }>;
}

export async function GET(request: Request, context: ProxyRouteContext) {
  return handleProxyRequest(request, context);
}

export async function POST(request: Request, context: ProxyRouteContext) {
  return handleProxyRequest(request, context);
}

export async function PUT(request: Request, context: ProxyRouteContext) {
  return handleProxyRequest(request, context);
}

export async function PATCH(request: Request, context: ProxyRouteContext) {
  return handleProxyRequest(request, context);
}

export async function DELETE(request: Request, context: ProxyRouteContext) {
  return handleProxyRequest(request, context);
}

// Token-minting endpoints are reachable only through their dedicated routes, which keep the
// token in an HttpOnly cookie. Through this generic route they would return `access_token`
// to page JavaScript (S1-03).
const TOKEN_MINTING = [
  /^auth\/login$/,
  /^auth\/refresh$/,
  /^auth\/change-password$/,
  /^auth\/oidc\/[^/]+\/callback$/,
];

async function handleProxyRequest(request: Request, context: ProxyRouteContext) {
  const { path } = await context.params;
  const joined = path.join("/").replace(/^api\//, "");
  if (TOKEN_MINTING.some((pattern) => pattern.test(joined))) {
    return NextResponse.json({ message: "Not found" }, { status: 404 });
  }

  return proxyRequest({ path, request });
}
