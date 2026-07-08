export const AUTH_COOKIE_NAME = "auxilium_auth_token";

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
