"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo } from "react";

import { PASSWORD_CHANGE_REQUIRED_CODE } from "@/lib/auth";
import { useAuthStore } from "@/lib/auth-store";

const MAX_ERROR_MESSAGE_LENGTH = 300;

interface ErrorDetail {
  code?: string;
  message?: string;
}

/** Reads the response body once, tolerating a non-JSON body. */
async function readErrorDetail(response: Response): Promise<ErrorDetail | string | null> {
  try {
    const body = (await response.json()) as { detail?: string | ErrorDetail };
    if (typeof body.detail === "string") {
      return body.detail;
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
  const detail = await readErrorDetail(response);
  const isObjectDetail = detail !== null && typeof detail === "object";

  if (response.status === 403) {
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

  let message = `API request failed with status ${response.status}`;
  if (typeof detail === "string") {
    message = detail;
  } else if (isObjectDetail && detail.message) {
    message = detail.message;
  }
  // 5xx detail is already sanitized server-side (core.safe_http_errors), but
  // cap length defensively so a future regression can't dump a stack trace
  // or long upstream error into a toast.
  if (response.status >= 500 && message.length > MAX_ERROR_MESSAGE_LENGTH) {
    message = `Server error (status ${response.status}). Check the logs for details.`;
  }
  return message;
}

export function useApi() {
  const router = useRouter();

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
        router.replace("/login");
        throw new Error("Authentication required");
      }

      if (!response.ok) {
        throw new Error(
          await buildApiErrorMessage(response, () =>
            useAuthStore.getState().markPasswordChangeRequired(),
          ),
        );
      }

      if (response.status === 204) {
        return undefined as TResponse;
      }

      return (await response.json()) as TResponse;
    },
    [router],
  );

  return useMemo(() => ({ apiCall }), [apiCall]);
}
