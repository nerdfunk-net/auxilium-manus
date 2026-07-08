import type { TemplateType } from "./types";

export const TEMPLATE_CATEGORY = "netmiko";

export const TEMPLATE_TYPES: { value: TemplateType; label: string }[] = [
  { value: "jinja2", label: "Jinja2" },
  { value: "text", label: "Text" },
  { value: "textfsm", label: "TextFSM" },
];

/** Auto-filled variables available to Netmiko templates. */
export const NETMIKO_AUTO_VARIABLES: { name: string; description: string }[] = [
  { name: "devices", description: "Selected test device (id, name, primary_ip4)" },
  { name: "device_details", description: "Full Nautobot details for the test device" },
];

/**
 * Command variables, matching the "Render Jinja Template" workflow step.
 * Each entry exposes name / raw / parsed / success / node_id.
 */
export const COMMAND_VARIABLES: { name: string; description: string }[] = [
  {
    name: "command",
    description: "The most recently executed command (name, raw, parsed, success)",
  },
  {
    name: "commands",
    description: "List of every executed command, in configured order",
  },
  {
    name: "commands_by_name",
    description: "Executed commands keyed by their exact command string",
  },
];
