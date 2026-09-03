"use client";

import { useEffect, type ReactNode } from "react";

import { ChangePasswordDialog } from "@/components/features/auth/change-password-dialog";
import { useWorkflowBuilderStore } from "@/components/features/workflows/hooks/use-workflow-builder-store";
import { useGeneralSettingsQuery } from "@/hooks/queries/use-general-settings-query";
import { useSessionManager } from "@/hooks/use-session-manager";
import { useAuthStore } from "@/lib/auth-store";

import { AppSidebar } from "./app-sidebar";

interface DashboardShellProps {
  children: ReactNode;
}

const DEFAULT_SESSION_TIMEOUT_MINUTES = 20;

export function DashboardShell({ children }: DashboardShellProps) {
  const { data: generalSettings } = useGeneralSettingsQuery();
  const mustChangePassword = useAuthStore((state) => state.user?.must_change_password === true);
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const reconcileDraftOwner = useWorkflowBuilderStore((state) => state.reconcileDraftOwner);

  // The in-progress workflow canvas lives in a module-level singleton that a
  // soft logout navigation keeps in memory (so an idle logout doesn't discard
  // unsaved edits). Once a user is known, drop any draft that belongs to
  // someone else — a different account logging in on this browser must never
  // see the previous person's canvas.
  useEffect(() => {
    if (userId === null) return;
    reconcileDraftOwner(userId);
  }, [userId, reconcileDraftOwner]);

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
      {/* Forced: no onOpenChange, so it cannot be dismissed except by a
          successful password change (which clears must_change_password). */}
      <ChangePasswordDialog open={mustChangePassword} forced />
    </div>
  );
}
