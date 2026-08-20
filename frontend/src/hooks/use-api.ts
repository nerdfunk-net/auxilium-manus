"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo } from "react";

const MAX_ERROR_MESSAGE_LENGTH = 300;

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

      if (response.status === 403) {
        throw new Error("Permission denied");
      }

      if (!response.ok) {
        let message = `API request failed with status ${response.status}`;
        try {
          const body = (await response.json()) as {
            detail?: string | { message?: string };
          };
          if (typeof body.detail === "string") {
            message = body.detail;
          } else if (
            body.detail &&
            typeof body.detail === "object" &&
            "message" in body.detail &&
            typeof body.detail.message === "string"
          ) {
            message = body.detail.message;
          }
        } catch {
          // use default message
        }
        // 5xx detail is already sanitized server-side (core.safe_http_errors),
        // but cap length defensively so a future regression can't dump a
        // stack trace or long upstream error into a toast.
        if (response.status >= 500 && message.length > MAX_ERROR_MESSAGE_LENGTH) {
          message = `Server error (status ${response.status}). Check the logs for details.`;
        }
        throw new Error(message);
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
