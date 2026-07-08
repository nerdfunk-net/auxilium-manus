"use client";

import Link from "next/link";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import { SETTINGS_SECTIONS } from "../constants/settings-sections";
import type { SettingsSection } from "../types/settings-section";

interface SettingsTopbarProps {
  activeSection: SettingsSection;
}

export function SettingsTopbar({ activeSection }: SettingsTopbarProps) {
  const currentUser = useAuthStore((state) => state.user);
  const visibleSections = SETTINGS_SECTIONS.filter(
    (section) => section.id !== "users" || hasPermission(currentUser, "users", "read"),
  );

  return (
    <header className="flex h-16 items-center justify-between border-b bg-card px-5">
      <Tabs value={activeSection}>
        <TabsList>
          {visibleSections.map((section) => (
            <TabsTrigger asChild key={section.id} value={section.id}>
              <Link href={`/settings/${section.id}`}>{section.label}</Link>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
    </header>
  );
}
