"use client";

import dynamic from "next/dynamic";
import type { ComponentType } from "react";

import type { SettingsSection } from "../types/settings-section";

// Each section brings its own dialogs and forms; only the visible one is loaded (Q5).
const SECTION_CANVASES: Partial<Record<SettingsSection, ComponentType>> = {
  "general": dynamic(() => import("./general-settings-canvas").then((m) => m.GeneralSettingsCanvas)),
  "sources": dynamic(() => import("./sources-settings-canvas").then((m) => m.SourcesSettingsCanvas)),
  "hatchet": dynamic(() => import("./hatchet-settings-canvas").then((m) => m.HatchetSettingsCanvas)),
  "redis": dynamic(() => import("./redis-settings-canvas").then((m) => m.RedisSettingsCanvas)),
  "credentials": dynamic(() => import("./credentials-settings-canvas").then((m) => m.CredentialsSettingsCanvas)),
  "users": dynamic(() => import("./permissions-settings-canvas").then((m) => m.PermissionsSettingsCanvas)),
  "logging": dynamic(() => import("./logging-settings-canvas").then((m) => m.LoggingSettingsCanvas)),
  "git-repositories": dynamic(() => import("./git-repositories-settings-canvas").then((m) => m.GitRepositoriesSettingsCanvas)),
  "secret-manager": dynamic(() => import("./secret-manager-settings-canvas").then((m) => m.SecretManagerSettingsCanvas)),
  "ai-assistant": dynamic(() => import("./ai-assistant-settings-canvas").then((m) => m.AiAssistantSettingsCanvas)),
  "mail": dynamic(() => import("./mail-settings-canvas").then((m) => m.MailSettingsCanvas)),
};

interface SettingsSectionCanvasProps {
  section: SettingsSection;
}

export function SettingsSectionCanvas({ section }: SettingsSectionCanvasProps) {
  const Canvas = SECTION_CANVASES[section];
  return Canvas ? <Canvas /> : null;
}
