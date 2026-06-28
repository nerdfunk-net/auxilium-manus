export const AUTH_COOKIE_NAME = "auxilium_auth_token";

export interface AuthUser {
  id: number;
  username: string;
  permissions: number;
  is_active: boolean;
}

export interface LoginResponse {
  user: AuthUser;
}
