import type { Metadata } from "next";

import { ChangeRequestsPage } from "@/components/features/change-requests/change-requests-page";

export const metadata: Metadata = { title: "Change Requests" };

export default function ChangeRequestsRoute() {
  return <ChangeRequestsPage />;
}
