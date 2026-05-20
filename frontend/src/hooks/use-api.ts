"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo } from "react";

export function useApi() {
  const router = useRouter();

  const apiCall = useCallback(
    async <TResponse>(endpoint: string, init: RequestInit = {}) => {
      const response = await fetch(`/api/proxy/${endpoint.replace(/^\/+/, "")}`, {
        ...init,
        credentials: "include",
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
