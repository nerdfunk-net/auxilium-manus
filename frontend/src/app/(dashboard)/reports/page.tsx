import type { Metadata } from "next";

import { ReportsPage } from "@/components/features/reports/reports-page";

export const metadata: Metadata = { title: "Reports" };

export default function ReportsRoute() {
  return <ReportsPage />;
}
