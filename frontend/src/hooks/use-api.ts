"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useMemo } from "react";

import { PASSWORD_CHANGE_REQUIRED_CODE } from "@/lib/auth";
import { useAuthStore } from "@/lib/auth-store";

const MAX_ERROR_MESSAGE_LENGTH = 300;

export interface ErrorDetail {
  code?: string;
  message?: string;
  [extra: string]: unknown;
}

interface ValidationIssue {
  loc?: unknown[];
  msg?: string;
}

/**
 * FastAPI answers a failed request-body validation (422) with a list of issues. Show the first
 * one as "field: message" so the user learns what to fix instead of a bare status code.
 */
export function formatValidationDetail(issues: unknown[]): string | null {
  const first = issues[0] as ValidationIssue | undefined;
  if (!first || typeof first.msg !== "string") return null;
  const message = first.msg.replace(/^Value error, /, "");
  const path = (first.loc ?? []).filter((part) => part !== "body" && part !== "query");
  const field = path.length > 0 ? String(path[path.length - 1]) : null;
  const extra = issues.length > 1 ? ` (and ${issues.length - 1} more)` : "";
  return `${field ? `${field}: ` : ""}${message}${extra}`;
}

/** A failed API call that keeps the HTTP status (a plain `Error` subclass, so callers that only
 * read `.message` keep working). */
export class ApiError extends Error {
  readonly status: number;
  /** The structured `detail` object of the response (for example `{code, message, ...}`), if any. */
  readonly detail: ErrorDetail | null;

  constructor(message: string, status: number, detail: ErrorDetail | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function isConflictError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

/** The target of the request does not exist (any more). */
export function isNotFoundError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

/** The server understood the request and refused it: the user lacks a permission. */
export function isForbiddenError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}

/** Reads the response body once, tolerating a non-JSON body. */
async function readErrorDetail(response: Response): Promise<ErrorDetail | string | null> {
  try {
    const body = (await response.json()) as { detail?: string | ErrorDetail | unknown[] };
    if (typeof body.detail === "string") {
      return body.detail;
    }
    if (Array.isArray(body.detail)) {
      return formatValidationDetail(body.detail);
    }
    if (body.detail && typeof body.detail === "object") {
      return body.detail;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Turns a non-ok response into the message apiCall throws. Framework-free
 * (no fetch, no router) so it's unit-testable on its own — see
 * use-api-error.test.ts. `onPasswordChangeRequired` is called, not the
 * store directly, so this function has no dependency on Zustand either.
 */
export async function buildApiErrorMessage(
  response: Response,
  onPasswordChangeRequired: () => void,
): Promise<string> {
  return (await describeApiFailure(response, onPasswordChangeRequired)).message;
}

/** Like `buildApiErrorMessage`, plus the structured detail object for `ApiError.detail`. */
export async function describeApiFailure(
  response: Response,
  onPasswordChangeRequired: () => void,
): Promise<{ message: string; detail: ErrorDetail | null }> {
  const detail = await readErrorDetail(response);
  const message =
    response.status === 429
      ? rateLimitMessage(response.headers.get("Retry-After"))
      : messageFromDetail(response.status, detail, onPasswordChangeRequired);
  return { message, detail: detail !== null && typeof detail === "object" ? detail : null };
}

/** Two minutes and up are shown in minutes (rounded up), shorter waits in seconds. */
const SECONDS_SHOWN_BELOW = 120;

/**
 * The per-user rate limits (backend/core/rate_limit.py) answer 429 with a
 * `Retry-After` in whole seconds. Anything else (the HTTP-date form, junk,
 * a missing header) gets the generic wording rather than a made-up time.
 */
function rateLimitMessage(retryAfter: string | null): string {
  const seconds = retryAfter !== null && /^\d+$/.test(retryAfter) ? Number(retryAfter) : 0;
  if (seconds < 1) {
    return "Too many requests. Please wait a moment and try again.";
  }
  if (seconds < SECONDS_SHOWN_BELOW) {
    return `Too many requests. Please wait ${seconds} ${seconds === 1 ? "second" : "seconds"} and try again.`;
  }
  return `Too many requests. Please wait ${Math.ceil(seconds / 60)} minutes and try again.`;
}

function messageFromDetail(
  status: number,
  detail: ErrorDetail | string | null,
  onPasswordChangeRequired: () => void,
): string {
  const isObjectDetail = detail !== null && typeof detail === "object";

  if (status === 403) {
    if (isObjectDetail && detail.code === PASSWORD_CHANGE_REQUIRED_CODE) {
      // Every other endpoint 403s this way while must_change_password is
      // set (core/auth.py::get_current_user). The caller flips it on the
      // user already held in the auth store so DashboardShell's forced
      // dialog opens without waiting for the next /auth/me poll.
      onPasswordChangeRequired();
      return detail.message ?? "You must change your password before continuing";
    }
    // require_permission and friends (core/auth.py) send a plain string
    // detail, e.g. "Permission denied: workflows:read required" — surface
    // it rather than a generic message.
    if (typeof detail === "string") {
      return detail;
    }
    return (isObjectDetail ? detail.message : undefined) ?? "Permission denied";
  }

  let message = `API request failed with status ${status}`;
  if (typeof detail === "string") {
    message = detail;
  } else if (isObjectDetail && detail.message) {
    message = detail.message;
  }
  // 5xx detail is already sanitized server-side (core.safe_http_errors), but
  // cap length defensively so a future regression can't dump a stack trace
  // or long upstream error into a toast.
  if (status >= 500 && message.length > MAX_ERROR_MESSAGE_LENGTH) {
    message = `Server error (status ${status}). Check the logs for details.`;
  }
  return message;
}

export function useApi() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const apiCall = useCallback(
    async <TResponse>(endpoint: string, init: RequestInit = {}) => {
      const headers = new Headers(init.headers);
      // fetch() defaults a string body to Content-Type: text/plain, which the
      // backend can't parse as a Pydantic model. FormData bodies (file
      // uploads) must keep the browser-generated multipart boundary header,
      // so only fill this in when it's actually missing.
      if (typeof init.body === "string" && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
      }

      const response = await fetch(`/api/proxy/${endpoint.replace(/^\/+/, "")}`, {
        ...init,
        credentials: "include",
        headers,
      });

      if (response.status === 401) {
        useAuthStore.getState().expireSession(queryClient);
        router.replace("/login");
        throw new Error("Authentication required");
      }

      if (!response.ok) {
        const { message, detail } = await describeApiFailure(response, () =>
          useAuthStore.getState().markPasswordChangeRequired(),
        );
        throw new ApiError(message, response.status, detail);
      }

      if (response.status === 204) {
        return undefined as TResponse;
      }

      return (await response.json()) as TResponse;
    },
    [router, queryClient],
  );

  return useMemo(() => ({ apiCall }), [apiCall]);
}
