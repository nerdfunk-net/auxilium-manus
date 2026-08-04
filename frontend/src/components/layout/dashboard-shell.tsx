"use client";

import type { ReactNode } from "react";

import { useGeneralSettingsQuery } from "@/hooks/queries/use-general-settings-query";
import { useSessionManager } from "@/hooks/use-session-manager";

import { AppSidebar } from "./app-sidebar";

interface DashboardShellProps {
  children: ReactNode;
}

const DEFAULT_SESSION_TIMEOUT_MINUTES = 20;

export function DashboardShell({ children }: DashboardShellProps) {
  const { data: generalSettings } = useGeneralSettingsQuery();

  useSessionManager({
    refreshInterval: 15 * 60 * 1000, // Renew the session every 15 minutes while active
    idleLogoutTimeout:
      (generalSettings?.session_timeout_minutes ?? DEFAULT_SESSION_TIMEOUT_MINUTES) * 60 * 1000,
    checkInterval: 30 * 1000, // Check every 30 seconds
  });

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <AppSidebar />
      <div className="flex min-w-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
