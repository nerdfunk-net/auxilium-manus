"use client";

import {
  Boxes,
  FileCode,
  LogOut,
  Network,
  PlayCircle,
  Settings,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback } from "react";

import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/utils";

type NavigationItem = {
  label: string;
  icon: typeof Workflow;
  href: string;
  isActive: (pathname: string) => boolean;
};

const navigationItems: NavigationItem[] = [
  {
    label: "Workflows",
    icon: Workflow,
    href: "/workflows",
    isActive: (pathname) => pathname === "/workflows",
  },
  {
    label: "Inventory",
    icon: Network,
    href: "/inventory",
    isActive: (pathname) => pathname === "/inventory",
  },
  {
    label: "Templates",
    icon: FileCode,
    href: "/templates",
    isActive: (pathname) => pathname.startsWith("/templates"),
  },
  {
    label: "Runs",
    icon: PlayCircle,
    href: "/workflows/runs",
    isActive: (pathname) => pathname === "/workflows/runs",
  },
  {
    label: "Settings",
    icon: Settings,
    href: "/settings/general",
    isActive: (pathname) => pathname.startsWith("/settings"),
  },
];

export function AppSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);

  const handleLogout = useCallback(async () => {
    await logout();
    router.replace("/login");
    router.refresh();
  }, [logout, router]);

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
        {navigationItems.map((item) => {
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
          aria-label="Sign out"
          className="mt-3 w-full justify-start"
          onClick={handleLogout}
          size="sm"
          type="button"
          variant="ghost"
        >
          <LogOut className="size-4" />
          Sign out
        </Button>
      </div>
    </aside>
  );
}
