"use client";

import { Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { formatTime } from "@/components/features/workflows/components/run-status-icon";
import { useDashboardNotificationsQuery } from "@/hooks/queries/use-dashboard-notifications-query";
import type { DashboardNotificationItem } from "@/components/features/dashboard/types/dashboard-api";

function SeverityBadge({ severity }: { severity: string }) {
  if (severity === "error") {
    return <Badge variant="destructive">error</Badge>;
  }
  if (severity === "warning") {
    return (
      <Badge className="border-amber-500/50 text-amber-600" variant="outline">
        warning
      </Badge>
    );
  }
  return <Badge variant="secondary">{severity}</Badge>;
}

function NotificationRow({ notification }: { notification: DashboardNotificationItem }) {
  const subtitleParts = [
    notification.workflow_name,
    notification.workflow_owner_username ?? "—",
    notification.device_name,
    formatTime(notification.created_at),
  ].filter(Boolean);

  return (
    <div className="flex items-start justify-between gap-3 rounded-md border border-border/60 px-3 py-2 text-sm">
      <div className="min-w-0">
        <p className="truncate font-medium">{notification.message}</p>
        <p className="truncate text-xs text-muted-foreground">{subtitleParts.join(" · ")}</p>
      </div>
      <SeverityBadge severity={notification.severity} />
    </div>
  );
}

export function NotificationsWidget() {
  const { data, isLoading, error } = useDashboardNotificationsQuery();

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="size-5 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-sm text-destructive">
        Failed to load notifications: {error.message}
      </p>
    );
  }

  const notifications = data?.notifications ?? [];

  if (notifications.length === 0) {
    return <p className="text-sm text-muted-foreground">No notifications yet.</p>;
  }

  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto">
      {notifications.map((notification) => (
        <NotificationRow key={notification.id} notification={notification} />
      ))}
    </div>
  );
}
