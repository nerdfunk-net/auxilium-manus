"use client";

import type { ReactNode } from "react";

import { useSessionManager } from "@/hooks/use-session-manager";

import { AppSidebar } from "./app-sidebar";

interface DashboardShellProps {
  children: ReactNode;
}

export function DashboardShell({ children }: DashboardShellProps) {
  useSessionManager({
    refreshInterval: 20 * 60 * 1000, // Refresh every 20 minutes while active
    activityTimeout: 15 * 60 * 1000, // Consider user inactive after 15 minutes
    checkInterval: 30 * 1000, // Check every 30 seconds
  });

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <AppSidebar />
      <div className="flex min-w-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
