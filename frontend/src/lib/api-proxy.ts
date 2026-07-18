import { NextResponse } from "next/server";
import { cookies } from "next/headers";

import { AUTH_COOKIE_NAME } from "@/lib/auth";

const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);
const STRIP_REQUEST_HEADERS = new Set(["authorization", "cookie"]);
const STRIP_RESPONSE_HEADERS = new Set(["set-cookie"]);

export interface ProxyRequestOptions {
  path: string[];
  request: Request;
  authorization?: string;
  body?: BodyInit | null;
}

export async function proxyRequest({
  authorization,
  body,
  path,
  request,
}: ProxyRequestOptions) {
  const targetUrl = buildBackendUrl(path, request.url);
  const [headers, requestBody] = await Promise.all([
    buildForwardHeaders(request.headers, authorization),
    body !== undefined ? Promise.resolve(body) : readRequestBody(request),
  ]);

  try {
    const backendResponse = await fetch(targetUrl, {
      body: requestBody,
      cache: "no-store",
      headers,
      method: request.method,
      redirect: "manual",
    });

    return toNextResponse(backendResponse);
  } catch {
    return NextResponse.json({ message: "Backend unavailable" }, { status: 503 });
  }
}

export function buildBackendUrl(path: string[], requestUrl: string) {
  const backendUrl = (process.env.BACKEND_URL ?? DEFAULT_BACKEND_URL).replace(/\/$/, "");
  const sourceUrl = new URL(requestUrl);
  const normalizedPath = normalizeProxyPath(path);

  return `${backendUrl}${normalizedPath}${sourceUrl.search}`;
}

function normalizeProxyPath(path: string[]) {
  // Next.js decodes each catch-all segment before handing it to us, so a
  // literal "#" (or other reserved char) in a segment — e.g. an ISE group
  // name like "myGroup#myGroup#my-test-001" — must be re-encoded before
  // going into a plain string URL. Left decoded, fetch() treats a bare "#"
  // as the start of a URL fragment and silently drops everything after it,
  // including the query string.
  const requestedPath = path.map((segment) => encodeURIComponent(segment)).join("/");

  if (requestedPath.startsWith("api/")) {
    return `/${requestedPath}`;
  }

  return `/api/${requestedPath}`;
}

async function buildForwardHeaders(sourceHeaders: Headers, authorization?: string) {
  const headers = new Headers();

  for (const [key, value] of sourceHeaders.entries()) {
    const lowerKey = key.toLowerCase();

    if (!HOP_BY_HOP_HEADERS.has(lowerKey) && !STRIP_REQUEST_HEADERS.has(lowerKey)) {
      headers.set(key, value);
    }
  }

  const cookieToken = (await cookies()).get(AUTH_COOKIE_NAME)?.value;
  const authHeader = authorization ?? (cookieToken ? `Bearer ${cookieToken}` : null);

  if (authHeader) {
    headers.set("Authorization", authHeader);
  }

  return headers;
}

async function readRequestBody(request: Request): Promise<ArrayBuffer | null> {
  if (request.method === "GET" || request.method === "HEAD") {
    return null;
  }

  // Next.js App Router cannot forward request.body (ReadableStream) directly to
  // another fetch() call — read it into an ArrayBuffer first.
  return request.arrayBuffer();
}

async function toNextResponse(response: Response) {
  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }

  const headers = copyResponseHeaders(response.headers);
  const contentType = response.headers.get("content-type") ?? "";

  if (contentType.includes("application/json")) {
    const data = await response.json();

    return NextResponse.json(data, {
      headers,
      status: response.status,
    });
  }

  return new NextResponse(response.body, {
    headers,
    status: response.status,
  });
}

function copyResponseHeaders(sourceHeaders: Headers) {
  const headers = new Headers();

  for (const [key, value] of sourceHeaders.entries()) {
    const lowerKey = key.toLowerCase();

    if (!HOP_BY_HOP_HEADERS.has(lowerKey) && !STRIP_RESPONSE_HEADERS.has(lowerKey)) {
      headers.set(key, value);
    }
  }

  return headers;
}
