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
    'Parsed config keyed by output_key ("cisco_config"), always nested under .running / .startup — e.g. parsed.cisco_config.running.hostname, .running.vlans, .running.access_lists, .running.aaa_servers. Matches the Parse Cisco Config step.',
};

/**
 * Ad-hoc Batfish query result variable, populated by the Options modal's
 * Batfish tab, matching the batfish-routing-table / batfish-path-check /
 * batfish-acl-check workflow steps' answer shape.
 *
 * PREVIEW-ONLY -- unlike every other auto-filled variable above, this one is
 * NOT populated by any real workflow step. batfish-routing-table/-path-check/
 * -acl-check store their result only as a workflow-level artifact +
 * WorkflowContext.metadata pointer (see doc/BATFISH_INTEGRATION.md "Result
 * storage") -- they never write into a DeviceContext, so a real Render Jinja
 * Template step never receives a `batfish` variable. A template that
 * references `batfish.*` will render fine here and then fail every device
 * with "Undefined template variable: 'batfish' is undefined" at actual
 * workflow runtime. Use this tab only to explore/verify a Batfish query
 * while authoring -- never reference `batfish.*` in the template body itself.
 * If you need per-device Batfish data in a real template, use the `parsed`
 * namespace populated by Extract Facts / Get OSPF Facts / Get BGP Facts /
 * Batfish Node or Interface Properties instead (see the Jinja help dialog).
 */
export const BATFISH_VARIABLE: { name: string; description: string } = {
  name: "batfish",
  description:
    "PREVIEW-ONLY. Result of an ad-hoc Batfish query (Routing Table / Path Check / ACL Check) run here for exploration — never populated by an actual workflow run. Do not reference batfish.* in the template body; use it only to inspect the shape while authoring. For real per-device Batfish data, use parsed.<output_key> from Extract Facts / Get OSPF Facts / Get BGP Facts / Batfish Node or Interface Properties instead.",
};
