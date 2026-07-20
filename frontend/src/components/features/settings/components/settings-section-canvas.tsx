"use client";

import { SETTINGS_SECTIONS } from "../constants/settings-sections";
import type { SettingsSection } from "../types/settings-section";
import { CredentialsSettingsCanvas } from "./credentials-settings-canvas";
import { HatchetSettingsCanvas } from "./hatchet-settings-canvas";
import { LoggingSettingsCanvas } from "./logging-settings-canvas";
import { PermissionsSettingsCanvas } from "./permissions-settings-canvas";
import { RedisSettingsCanvas } from "./redis-settings-canvas";
import { SourcesSettingsCanvas } from "./sources-settings-canvas";

type MockPlaceholderSection = Exclude<
  SettingsSection,
  "sources" | "hatchet" | "redis" | "credentials" | "users" | "logging"
>;

const MOCK_PLACEHOLDERS: Record<
  MockPlaceholderSection,
  { title: string; items: string[] }
> = {
  general: {
    title: "General settings",
    items: [
      "Application name and branding",
      "Default workflow folder",
      "Timezone and locale",
    ],
  },
};

interface SettingsSectionCanvasProps {
  section: SettingsSection;
}

export function SettingsSectionCanvas({ section }: SettingsSectionCanvasProps) {
  if (section === "sources") {
    return <SourcesSettingsCanvas />;
  }

  if (section === "hatchet") {
    return <HatchetSettingsCanvas />;
  }

  if (section === "redis") {
    return <RedisSettingsCanvas />;
  }

  if (section === "credentials") {
    return <CredentialsSettingsCanvas />;
  }

  if (section === "users") {
    return <PermissionsSettingsCanvas />;
  }

  if (section === "logging") {
    return <LoggingSettingsCanvas />;
  }

  const sectionMeta = SETTINGS_SECTIONS.find((s) => s.id === section);
  const placeholder = MOCK_PLACEHOLDERS[section as MockPlaceholderSection];

  if (!sectionMeta || !placeholder) {
    return null;
  }

  const SectionIcon = sectionMeta.icon;

  return (
    <div className="flex h-full items-center justify-center bg-slate-50 p-10">
      <div className="w-full max-w-3xl rounded-2xl border bg-card p-6 shadow-sm">
        <div className="mb-6 flex items-start gap-4">
          <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <SectionIcon className="size-6" />
          </div>
          <div>
            <p className="text-sm font-semibold">{sectionMeta.label}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {sectionMeta.description}
            </p>
          </div>
        </div>

        <div className="rounded-xl border border-dashed bg-muted/30 p-6">
          <p className="text-sm font-medium text-muted-foreground">
            Mock canvas — {placeholder.title}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Preview only. Configuration forms and API wiring will be added later.
          </p>
          <ul className="mt-4 space-y-2">
            {placeholder.items.map((item) => (
              <li
                key={item}
                className="flex items-center gap-2 rounded-lg border bg-background px-4 py-3 text-sm"
              >
                <span className="size-2 shrink-0 rounded-full bg-muted-foreground/40" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
