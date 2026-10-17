"use client";

import { useMemo } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuthStore } from "@/lib/auth-store";

import { SettingsSectionCanvas } from "./components/settings-section-canvas";
import { SettingsTopbar } from "./components/settings-topbar";
import { SETTINGS_SECTIONS } from "./constants/settings-sections";
import type { SettingsSection } from "./types/settings-section";

interface SettingsPageProps {
  section: SettingsSection;
}

export function SettingsPage({ section }: SettingsPageProps) {
  const user = useAuthStore((state) => state.user);
  const sectionDef = useMemo(
    () => SETTINGS_SECTIONS.find((item) => item.id === section),
    [section],
  );
  const canShow = sectionDef?.canShow(user) ?? false;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <SettingsTopbar activeSection={section} />
      <main className="min-h-0 flex-1">
        {canShow ? (
          <SettingsSectionCanvas section={section} />
        ) : (
          <div className="flex h-full items-center justify-center p-10">
            <Card className="max-w-md">
              <CardHeader>
                <CardTitle>No permission</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                You do not have permission to view this settings section.
              </CardContent>
            </Card>
          </div>
        )}
      </main>
    </div>
  );
}
