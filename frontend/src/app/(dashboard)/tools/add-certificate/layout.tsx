import { requirePermissionOr404 } from "@/lib/require-permission";

export default async function AddCertificateLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await requirePermissionOr404("system.certificates", "write");
  return children;
}
