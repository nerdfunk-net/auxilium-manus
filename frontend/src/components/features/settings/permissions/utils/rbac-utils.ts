import type { Permission, PermissionWithGrant } from "../types";

export function groupPermissionsByResource<T extends Permission>(
  permissions: T[],
): Array<{ resource: string; permissions: T[] }> {
  const groups = new Map<string, T[]>();

  for (const permission of permissions) {
    const bucket = groups.get(permission.resource);
    if (bucket) {
      bucket.push(permission);
    } else {
      groups.set(permission.resource, [permission]);
    }
  }

  return Array.from(groups.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([resource, resourcePermissions]) => ({
      resource,
      permissions: [...resourcePermissions].sort((a, b) => a.action.localeCompare(b.action)),
    }));
}

const ACTION_BADGE_VARIANTS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  read: "secondary",
  write: "default",
  delete: "destructive",
  execute: "default",
  reveal: "destructive",
};

export function getActionVariant(
  action: string,
): "default" | "secondary" | "destructive" | "outline" {
  return ACTION_BADGE_VARIANTS[action] ?? "outline";
}

export function isPermissionGranted(
  permissions: PermissionWithGrant[],
  permissionId: number,
): boolean {
  return permissions.some((permission) => permission.id === permissionId && permission.granted);
}
