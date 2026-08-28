"use client";

import type { SettingsSection } from "../types/settings-section";
import { CredentialsSettingsCanvas } from "./credentials-settings-canvas";
import { GeneralSettingsCanvas } from "./general-settings-canvas";
import { HatchetSettingsCanvas } from "./hatchet-settings-canvas";
import { LoggingSettingsCanvas } from "./logging-settings-canvas";
import { PermissionsSettingsCanvas } from "./permissions-settings-canvas";
import { RedisSettingsCanvas } from "./redis-settings-canvas";
import { SourcesSettingsCanvas } from "./sources-settings-canvas";
import { VersionControlSettingsCanvas } from "./version-control-settings-canvas";

interface SettingsSectionCanvasProps {
  section: SettingsSection;
}

export function SettingsSectionCanvas({ section }: SettingsSectionCanvasProps) {
  if (section === "general") {
    return <GeneralSettingsCanvas />;
  }

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

  if (section === "version-control") {
    return <VersionControlSettingsCanvas />;
  }

  return null;
}
