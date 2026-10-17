import { notFound } from "next/navigation";

import { isDevToolsEnabled } from "@/lib/dev-tools";

export default function OidcTestLayout({ children }: { children: React.ReactNode }) {
  if (!isDevToolsEnabled()) notFound();
  return children;
}
