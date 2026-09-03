import type { Metadata } from "next";

import { SchedulesPage } from "@/components/features/schedules/schedules-page";

export const metadata: Metadata = { title: "Schedules" };

export default function SchedulesRoute() {
  return <SchedulesPage />;
}
