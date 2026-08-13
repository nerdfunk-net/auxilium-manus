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
  roles: string[];
  permissions: string[];
}

export interface LoginResponse {
  user: AuthUser;
}
