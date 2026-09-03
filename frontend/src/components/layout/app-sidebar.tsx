"use client";

import {
  Boxes,
  CalendarClock,
  FileCode,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Network,
  PlayCircle,
  Settings,
  Workflow,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { ChangePasswordDialog } from "@/components/features/auth/change-password-dialog";
import { Button } from "@/components/ui/button";
import type { AuthUser } from "@/lib/auth";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";
import { cn } from "@/lib/utils";

type NavigationItem = {
  label: string;
  icon: typeof Workflow;
  href: string;
  isActive: (pathname: string) => boolean;
  canShow: (user: AuthUser | null) => boolean;
};

const navigationItems: NavigationItem[] = [
  {
    label: "Dashboard",
    icon: LayoutDashboard,
    href: "/dashboard",
    isActive: (pathname) => pathname === "/dashboard",
    canShow: () => true,
  },
  {
    label: "Workflows",
    icon: Workflow,
    href: "/workflows",
    isActive: (pathname) => pathname === "/workflows",
    canShow: (user) => hasPermission(user, "workflows", "read"),
  },
  {
    label: "Inventory",
    icon: Network,
    href: "/inventory",
    isActive: (pathname) => pathname === "/inventory",
    canShow: (user) => hasPermission(user, "sources.nautobot", "read"),
  },
  {
    label: "Templates",
    icon: FileCode,
    href: "/templates",
    isActive: (pathname) => pathname.startsWith("/templates"),
    canShow: (user) => hasPermission(user, "templates", "read"),
  },
  {
    label: "Runs",
    icon: PlayCircle,
    href: "/workflows/runs",
    isActive: (pathname) => pathname === "/workflows/runs",
    canShow: (user) => hasPermission(user, "workflow_runs", "read"),
  },
  {
    label: "Schedules",
    icon: CalendarClock,
    href: "/schedules",
    isActive: (pathname) => pathname === "/schedules",
    canShow: (user) => hasPermission(user, "workflows", "execute"),
  },
  {
    label: "Settings",
    icon: Settings,
    href: "/settings/general",
    isActive: (pathname) => pathname.startsWith("/settings"),
    canShow: (user) =>
      hasPermission(user, "settings", "read") ||
      hasPermission(user, "general_settings", "write") ||
      hasPermission(user, "credentials", "read") ||
      hasPermission(user, "users", "read") ||
      hasPermission(user, "hatchet_settings", "read") ||
      hasPermission(user, "cache_settings", "read") ||
      hasPermission(user, "logging_settings", "read"),
  },
];

export function AppSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const queryClient = useQueryClient();
  const [showChangePassword, setShowChangePassword] = useState(false);

  const visibleItems = useMemo(
    () => navigationItems.filter((item) => item.canShow(user)),
    [user],
  );

  const handleLogout = useCallback(async () => {
    await logout(queryClient);
    router.replace("/login");
    router.refresh();
  }, [logout, queryClient, router]);

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r bg-card">
      <div className="flex h-16 items-center gap-3 border-b px-5">
        <div className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <Boxes className="size-5" />
        </div>
        <div>
          <p className="text-sm font-semibold">Auxilium Manus</p>
          <p className="text-xs text-muted-foreground">NetDevOps builder</p>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-1 p-3">
        {visibleItems.map((item) => {
          const isActive = item.isActive(pathname);

          return (
            <Link
              aria-current={isActive ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
                isActive && "bg-accent text-accent-foreground",
              )}
              href={item.href}
              key={item.label}
            >
              <item.icon className="size-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t p-4">
        {user ? (
          <p className="text-xs font-medium text-foreground">{user.username}</p>
        ) : null}
        <p className="mt-1 text-xs text-muted-foreground">
          Design workflows, run against your network inventory.
        </p>
        <Button
          aria-label="Change password"
          className="mt-3 w-full justify-start"
          onClick={() => setShowChangePassword(true)}
          size="sm"
          type="button"
          variant="ghost"
        >
          <KeyRound className="size-4" />
          Change password
        </Button>
        <Button
          aria-label="Sign out"
          className="w-full justify-start"
          onClick={handleLogout}
          size="sm"
          type="button"
          variant="ghost"
        >
          <LogOut className="size-4" />
          Sign out
        </Button>
      </div>
      <ChangePasswordDialog open={showChangePassword} onOpenChange={setShowChangePassword} />
    </aside>
  );
}
