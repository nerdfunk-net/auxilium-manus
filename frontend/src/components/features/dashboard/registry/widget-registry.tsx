import { Bell, CalendarClock, History } from "lucide-react";

import { NotificationsWidget } from "@/components/features/dashboard/widgets/notifications-widget";
import { RecentRunsWidget } from "@/components/features/dashboard/widgets/recent-runs-widget";
import { SchedulesWidget } from "@/components/features/dashboard/widgets/schedules-widget";
import type { WidgetDefinition, WidgetId } from "@/components/features/dashboard/types/dashboard";

export const WIDGET_REGISTRY: Record<WidgetId, WidgetDefinition> = {
  schedules: {
    id: "schedules",
    title: "Schedules",
    description: "Active workflow schedules and next run times",
    icon: CalendarClock,
    defaultSize: { w: 5, h: 6, minW: 3, minH: 4 },
    component: SchedulesWidget,
  },
  "recent-runs": {
    id: "recent-runs",
    title: "Recent Runs",
    description: "Recent workflow run history",
    icon: History,
    defaultSize: { w: 5, h: 6, minW: 3, minH: 4 },
    component: RecentRunsWidget,
  },
  notifications: {
    id: "notifications",
    title: "Notifications",
    description: "Recent notifications from workflow runs",
    icon: Bell,
    defaultSize: { w: 5, h: 6, minW: 3, minH: 4 },
    component: NotificationsWidget,
  },
};
