"use client";

import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

/**
 * Whether the signed-in user holds `resource:action`. UX gating only (see
 * `lib/permissions.ts`): use it to skip a request that would only get a 403.
 */
export function useHasPermission(resource: string, action: string): boolean {
  return useAuthStore((state) => hasPermission(state.user, resource, action));
}
