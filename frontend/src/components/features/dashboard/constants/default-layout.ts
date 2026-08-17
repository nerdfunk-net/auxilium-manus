import type { DashboardLayoutDoc } from "@/components/features/dashboard/types/dashboard";
import { WIDGET_REGISTRY } from "@/components/features/dashboard/registry/widget-registry";

const schedulesSize = WIDGET_REGISTRY.schedules.defaultSize;
const recentRunsSize = WIDGET_REGISTRY["recent-runs"].defaultSize;

export const DEFAULT_LAYOUT: DashboardLayoutDoc = {
  version: 1,
  layouts: {
    lg: [
      { i: "schedules", x: 0, y: 0, ...schedulesSize },
      { i: "recent-runs", x: 5, y: 0, ...recentRunsSize },
    ],
    md: [
      { i: "schedules", x: 0, y: 0, ...schedulesSize },
      { i: "recent-runs", x: 4, y: 0, ...recentRunsSize },
    ],
    sm: [
      { i: "schedules", x: 0, y: 0, w: 6, h: 6, minW: 3, minH: 4 },
      { i: "recent-runs", x: 0, y: 6, w: 6, h: 6, minW: 3, minH: 4 },
    ],
    xs: [
      { i: "schedules", x: 0, y: 0, w: 4, h: 6, minW: 2, minH: 4 },
      { i: "recent-runs", x: 0, y: 6, w: 4, h: 6, minW: 2, minH: 4 },
    ],
    xxs: [
      { i: "schedules", x: 0, y: 0, w: 2, h: 6, minW: 2, minH: 4 },
      { i: "recent-runs", x: 0, y: 6, w: 2, h: 6, minW: 2, minH: 4 },
    ],
  },
};
