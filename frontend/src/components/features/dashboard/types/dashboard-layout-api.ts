import type { DashboardLayoutDoc } from "@/components/features/dashboard/types/dashboard";

export interface DashboardLayoutResponse {
  layout: DashboardLayoutDoc | null;
}

export interface DashboardLayoutUpdatePayload {
  layout: DashboardLayoutDoc;
}
