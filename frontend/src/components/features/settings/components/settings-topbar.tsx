"use client";

import Link from "next/link";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { SETTINGS_SECTIONS } from "../constants/settings-sections";
import type { SettingsSection } from "../types/settings-section";

interface SettingsTopbarProps {
  activeSection: SettingsSection;
}

export function SettingsTopbar({ activeSection }: SettingsTopbarProps) {
  return (
    <header className="flex h-16 items-center justify-between border-b bg-card px-5">
      <Tabs value={activeSection}>
        <TabsList>
          {SETTINGS_SECTIONS.map((section) => (
            <TabsTrigger asChild key={section.id} value={section.id}>
              <Link href={`/settings/${section.id}`}>{section.label}</Link>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
    </header>
  );
}
