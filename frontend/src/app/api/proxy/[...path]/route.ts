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

async function handleProxyRequest(request: Request, context: ProxyRouteContext) {
  const { path } = await context.params;

  return proxyRequest({ path, request });
}
