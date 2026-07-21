import type { TemplateType } from "./types";

export const TEMPLATE_CATEGORY = "netmiko";

export const TEMPLATE_TYPES: { value: TemplateType; label: string }[] = [
  { value: "jinja2", label: "Jinja2" },
  { value: "text", label: "Text" },
  { value: "textfsm", label: "TextFSM" },
];

/** Auto-filled variables available to Netmiko templates. */
export const NETMIKO_AUTO_VARIABLES: { name: string; description: string }[] = [
  {
    name: "device",
    description:
      "Device identity: name, hostname, id, primary_ip4, platform, network_driver",
  },
  {
    name: "nautobot",
    description:
      "Nautobot attributes (role, platform, location, config_context, custom_fields, …) — matches the Get Nautobot Attributes step",
  },
];

/**
 * Optional Nautobot attribute groups, matching the "Get Nautobot Attributes"
 * workflow step. Base fields (role, platform, location, status, primary_ip4)
 * are always fetched; these add the heavier / optional data.
 */
export const NAUTOBOT_ATTRIBUTE_GROUPS: { key: string; label: string }[] = [
  { key: "interfaces", label: "Poll all Interfaces" },
  { key: "custom_fields", label: "Poll Custom Fields" },
  { key: "tags", label: "Poll Tags" },
  { key: "config_context", label: "Poll Config Context" },
  { key: "secret_groups", label: "Poll Secret Groups" },
  { key: "console_ports", label: "Poll Console Ports and Console Server Ports" },
  { key: "power_ports", label: "Poll Power Ports and Power Outlets" },
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

/**
 * Parsed Cisco configuration variable, matching the "Parse Cisco Config" step's
 * default output_key ("cisco_config"). Populated by the "Get Configs" checkbox,
 * which fetches running + startup config from the test device and parses it
 * exactly like the workflow step.
 */
export const PARSED_CONFIG_VARIABLE: { name: string; description: string } = {
  name: "parsed",
  description:
    'Parsed running/startup config, keyed by output_key ("cisco_config") — hostname, vrfs, vlans, interfaces, access_lists, routing, aaa_servers, etc. Matches the Parse Cisco Config step.',
};
