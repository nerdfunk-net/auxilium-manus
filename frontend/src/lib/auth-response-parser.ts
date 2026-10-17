import type { AuthUser } from "@/lib/auth";

/**
 * Validates and narrows a backend user payload (UserResponse /
 * UserAdminResponse-shaped) into an AuthUser. Shared by every Next.js route
 * handler that relays a backend auth response to the browser (login,
 * refresh, me, oidc callback) so the validation rules — and any field added
 * to AuthUser, such as must_change_password — live in exactly one place.
 */
export function parseAuthUser(payload: unknown): AuthUser | null {
  if (typeof payload !== "object" || payload === null) {
    return null;
  }

  const candidate = payload as Partial<AuthUser>;

  if (
    typeof candidate.id !== "number" ||
    typeof candidate.username !== "string" ||
    typeof candidate.is_active !== "boolean" ||
    !Array.isArray(candidate.roles) ||
    !Array.isArray(candidate.permissions)
  ) {
    return null;
  }

  return {
    id: candidate.id,
    username: candidate.username,
    is_active: candidate.is_active,
    // Optional, not required: an older backend response simply omits it,
    // and a user who isn't blocked never carries the flag either way.
    must_change_password: candidate.must_change_password === true,
    roles: candidate.roles,
    permissions: candidate.permissions,
  };
}
