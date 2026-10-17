export const AUTH_COOKIE_NAME = "auxilium_auth_token";

type AuthCookieStore = {
  set: (
    name: string,
    value: string,
    options: {
      httpOnly: boolean;
      maxAge: number;
      path: string;
      sameSite: "lax";
      secure: boolean;
    },
  ) => void;
};

/**
 * Whether the auth cookie gets the `Secure` flag: decided by the connection (S1-11), not by
 * NODE_ENV, so a TLS-terminating ingress (x-forwarded-proto: https) gets a Secure cookie and a
 * plain-HTTP evaluation setup still works. `COOKIE_SECURE=true|false` forces it.
 */
export function cookieSecure(request: Request): boolean {
  const forced = process.env.COOKIE_SECURE;
  if (forced === "true" || forced === "false") {
    return forced === "true";
  }
  const forwarded = request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim();
  const proto = forwarded || new URL(request.url).protocol.replace(":", "");
  return proto === "https";
}

/**
 * The one place that sets the session cookie, so login, OIDC callback, refresh and password
 * change cannot drift apart on HttpOnly / SameSite / Secure / Max-Age.
 */
export function setAuthCookie(
  cookieStore: AuthCookieStore,
  token: string,
  maxAgeSeconds: number,
  request: Request,
) {
  cookieStore.set(AUTH_COOKIE_NAME, token, {
    httpOnly: true,
    maxAge: maxAgeSeconds,
    path: "/",
    sameSite: "lax",
    secure: cookieSecure(request),
  });
}

export function clearAuthCookie(
  cookieStore: AuthCookieStore,
  secure: boolean = process.env.NODE_ENV === "production",
) {
  cookieStore.set(AUTH_COOKIE_NAME, "", {
    httpOnly: true,
    maxAge: 0,
    path: "/",
    sameSite: "lax",
    secure,
  });
}

export interface AuthUser {
  id: number;
  username: string;
  is_active: boolean;
  must_change_password: boolean;
  roles: string[];
  permissions: string[];
}

// Matches core.auth.PASSWORD_CHANGE_REQUIRED_DETAIL["code"] on the backend.
// useApi checks a 403 response body for this to trigger the forced
// change-password dialog even on a route the frontend hasn't special-cased.
export const PASSWORD_CHANGE_REQUIRED_CODE = "password_change_required";

export interface LoginResponse {
  user: AuthUser;
  /** Lifetime of the access token in seconds (login, refresh, password change). */
  expires_in?: number;
}
