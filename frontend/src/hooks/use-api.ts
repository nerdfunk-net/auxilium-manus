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
        throw new Error(`API request failed with status ${response.status}`);
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
