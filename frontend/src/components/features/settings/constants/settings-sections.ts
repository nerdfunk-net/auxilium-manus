import { Database, KeyRound, Plug, ScrollText, Settings2, Users, Workflow } from "lucide-react";

import type { AuthUser } from "@/lib/auth";
import { hasPermission } from "@/lib/permissions";

import type { SettingsSection } from "../types/settings-section";

export const SETTINGS_SECTIONS: {
  id: SettingsSection;
  label: string;
  description: string;
  icon: typeof Settings2;
  canShow: (user: AuthUser | null) => boolean;
}[] = [
  {
    id: "general",
    label: "General",
    description: "Application defaults, appearance, and regional preferences.",
    icon: Settings2,
    canShow: (user) =>
      hasPermission(user, "general_settings", "write") ||
      hasPermission(user, "settings", "read"),
  },
  {
    id: "sources",
    label: "Sources",
    description: "Nautobot, CheckMK, Git, and other external integrations.",
    icon: Plug,
    canShow: (user) =>
      hasPermission(user, "settings", "read") ||
      hasPermission(user, "sources.ise", "read") ||
      hasPermission(user, "sources.pyats", "read") ||
      hasPermission(user, "sources.nautobot", "read") ||
      hasPermission(user, "sources.git", "read"),
  },
  {
    id: "credentials",
    label: "Credentials",
    description: "Login, SNMP, and device authentication mappings.",
    icon: KeyRound,
    canShow: (user) => hasPermission(user, "credentials", "read"),
  },
  {
    id: "users",
    label: "Users & Permissions",
    description: "Accounts, roles, and permission assignments.",
    icon: Users,
    canShow: (user) => hasPermission(user, "users", "read"),
  },
  {
    id: "hatchet",
    label: "Hatchet",
    description: "Workflow execution engine configuration.",
    icon: Workflow,
    canShow: (user) => hasPermission(user, "hatchet_settings", "read"),
  },
  {
    id: "redis",
    label: "Redis",
    description: "Device cache TTL and cache management.",
    icon: Database,
    canShow: (user) => hasPermission(user, "cache_settings", "read"),
  },
  {
    id: "logging",
    label: "Logging",
    description: "Log levels, the workflow execution log, and noisy loggers to mute.",
    icon: ScrollText,
    canShow: (user) => hasPermission(user, "logging_settings", "read"),
  },
];
