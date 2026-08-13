import { notFound } from "next/navigation";

export default function OidcTestCallbackLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  if (process.env.ENABLE_DEV_TOOLS !== "true") notFound();
  return children;
}
