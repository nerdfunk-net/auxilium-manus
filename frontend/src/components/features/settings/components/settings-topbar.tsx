"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuthStore } from "@/lib/auth-store";

import { SETTINGS_SECTIONS } from "../constants/settings-sections";
import { useWorkspaceStore } from "../hooks/use-workspace-store";
import type { SettingsSection } from "../types/settings-section";

export function SettingsTopbar() {
  const router = useRouter();
  const logout = useAuthStore((state) => state.logout);
  const settingsSection = useWorkspaceStore((state) => state.settingsSection);
  const setSettingsSection = useWorkspaceStore(
    (state) => state.setSettingsSection,
  );

  const handleLogout = useCallback(async () => {
    await logout();
    router.replace("/login");
    router.refresh();
  }, [logout, router]);

  return (
    <header className="flex h-16 items-center justify-between border-b bg-card px-5">
      <Tabs
        value={settingsSection}
        onValueChange={(value) =>
          setSettingsSection(value as SettingsSection)
        }
      >
        <TabsList>
          {SETTINGS_SECTIONS.map((section) => (
            <TabsTrigger key={section.id} value={section.id}>
              {section.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <Button
        aria-label="Sign out"
        onClick={handleLogout}
        size="icon"
        variant="ghost"
      >
        <LogOut className="size-4" />
      </Button>
    </header>
  );
}
