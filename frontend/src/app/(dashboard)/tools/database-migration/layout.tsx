import { requirePermissionOr404 } from "@/lib/require-permission";

export default async function DatabaseMigrationLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await requirePermissionOr404("system.database", "write");
  return children;
}
