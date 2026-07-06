"use client";

import { SettingsSectionCanvas } from "./components/settings-section-canvas";
import { SettingsTopbar } from "./components/settings-topbar";
import type { SettingsSection } from "./types/settings-section";

interface SettingsPageProps {
  section: SettingsSection;
}

export function SettingsPage({ section }: SettingsPageProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <SettingsTopbar activeSection={section} />
      <main className="min-h-0 flex-1">
        <SettingsSectionCanvas section={section} />
      </main>
    </div>
  );
}
