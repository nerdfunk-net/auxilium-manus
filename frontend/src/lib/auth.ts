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

export function clearAuthCookie(cookieStore: AuthCookieStore) {
  cookieStore.set(AUTH_COOKIE_NAME, "", {
    httpOnly: true,
    maxAge: 0,
    path: "/",
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
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
}
