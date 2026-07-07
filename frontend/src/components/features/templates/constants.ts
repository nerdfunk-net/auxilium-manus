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

export const PRE_RUN_VARIABLES: { name: string; description: string }[] = [
  { name: "command.raw", description: "Raw output of the command" },
  { name: "command.parsed", description: "TextFSM-parsed output of the command" },
];
