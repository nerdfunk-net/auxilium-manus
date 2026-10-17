export interface Permission {
  id: number;
  resource: string;
  action: string;
  description: string | null;
  created_at: string;
}

export interface PermissionWithGrant extends Permission {
  granted: boolean;
  source: "role" | "override" | null;
}

export interface Role {
  id: number;
  name: string;
  description: string | null;
  is_system: boolean;
  created_at: string;
  updated_at: string;
}

export interface RoleWithPermissions extends Role {
  permissions: PermissionWithGrant[];
}

export interface UserPermissions {
  user_id: number;
  roles: string[];
  permissions: PermissionWithGrant[];
  overrides: PermissionWithGrant[];
}

export interface RbacUser {
  id: number;
  username: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  roles: string[];
}

export interface RbacUserListResponse {
  users: RbacUser[];
}

export interface PermissionCreatePayload {
  resource: string;
  action: string;
  description?: string;
}

export interface RoleCreatePayload {
  name: string;
  description?: string;
  is_system?: boolean;
}

export interface RoleUpdatePayload {
  name?: string;
  description?: string;
}

export interface UserCreatePayload {
  username: string;
  password: string;
  is_active?: boolean;
}

export interface UserUpdatePayload {
  username?: string;
  password?: string;
  is_active?: boolean;
}
