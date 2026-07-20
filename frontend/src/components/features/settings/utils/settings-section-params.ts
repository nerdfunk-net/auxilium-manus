import type { SettingsSection } from "../types/settings-section";

const VALID_SECTIONS: SettingsSection[] = [
  "general",
  "sources",
  "credentials",
  "users",
  "hatchet",
  "redis",
  "logging",
];

export function parseSettingsSection(value: string): SettingsSection | null {
  return VALID_SECTIONS.includes(value as SettingsSection)
    ? (value as SettingsSection)
    : null;
}
