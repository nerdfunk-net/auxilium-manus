import type { AuthUser } from "@/lib/auth";

/**
 * Frontend-only UX gating. The real security boundary is the backend's
 * require_permission dependency — this only controls what's shown/enabled.
 */
export function hasPermission(
  user: AuthUser | null,
  resource: string,
  action: string,
): boolean {
  if (!user) {
    return false;
  }

  return user.permissions.includes(`${resource}:${action}`);
}

export function hasRole(user: AuthUser | null, role: string): boolean {
  return user?.roles.includes(role) ?? false;
}
