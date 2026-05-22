import { KeyRound, Plug, Settings2, Users, Workflow } from "lucide-react";

import type { SettingsSection } from "../types/settings-section";

export const SETTINGS_SECTIONS: {
  id: SettingsSection;
  label: string;
  description: string;
  icon: typeof Settings2;
}[] = [
  {
    id: "general",
    label: "General",
    description: "Application defaults, appearance, and regional preferences.",
    icon: Settings2,
  },
  {
    id: "sources",
    label: "Sources",
    description: "Nautobot, CheckMK, Git, and other external integrations.",
    icon: Plug,
  },
  {
    id: "credentials",
    label: "Credentials",
    description: "Login, SNMP, and device authentication mappings.",
    icon: KeyRound,
  },
  {
    id: "users",
    label: "Users",
    description: "Accounts, roles, and permission assignments.",
    icon: Users,
  },
  {
    id: "hatchet",
    label: "Hatchet",
    description: "Workflow execution engine configuration.",
    icon: Workflow,
  },
];
