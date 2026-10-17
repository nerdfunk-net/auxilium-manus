# Writing Jinja2 templates in Auxilium Manus

Distilled from the template editor's built-in help. Everything below is about *shape and paths*;
you are never shown real device data.

## How rendering works
- A template is rendered **once per device**; every variable is scoped to that one device. There is
  no cross-device access.
- Jinja2 sandbox with `trim_blocks` and `lstrip_blocks` enabled. Output is the device config text.
- Prefer `{% if x is defined %}` guards for optional namespaces; a missing namespace is undefined.

## Always available
```
device.name  device.hostname  device.id  device.primary_ip4
device.platform  device.network_driver  device.source  device.source_id
workflow.id  run.id  run.timestamp  run.date
```

## Populated only if a matching workflow step ran earlier
```
nautobot.*      Get Nautobot Attributes (also Config to Attributes, Set Default Attributes, Add to Nautobot)
git.*           Get Git Devices
ise.*           Get from ISE (raw ISE record: name, id, NetworkDeviceIPList, tacacsSettings...)
tacacs.shared_secret   only when the ISE device has a TACACS shared secret - guard with is defined
command, commands, commands_by_name   Run Command
parsed.*        shared namespace keyed by each step's output_key
data.*          Read from File (default destination), Update Attribute, Set Default Attributes
run_input.*     the workflow's static attributes, supplied when the workflow starts
```

## nautobot (base fields always present)
```
nautobot.name  nautobot.hostname  nautobot.serial  nautobot.primary_ip4.host / .address
nautobot.role.name  nautobot.status.name  nautobot.platform.name / .network_driver
nautobot.location.name / .parent.name  nautobot.device_type.model / .manufacturer.name
```
Optional groups appear only when selected in the editor's Attributes dialog:
`interfaces`, `custom_fields`, `tags`, `config_context`, `secret_groups`, `console_ports`,
`power_ports` (e.g. `nautobot.config_context`, `nautobot.custom_fields.<name>`).

Example:
```
{% if nautobot.role.name == 'Network' and nautobot.status.name == 'Active' %}
hostname {{ device.name }}
{% endif %}
```

## run_input (static attributes)
Declared per workflow; only exists for workflows that declare that name. A boolean renders as
`True`/`False`. If a template is shared, guard: `{% if run_input is defined %}`.
```
{% if run_input.confirm %}
vlan {{ run_input.vlan_id }}
 name {{ run_input.note }}
{% endif %}
```

## command / commands / commands_by_name (Run Command step)
Each entry: `name` (exact command), `raw` (text output), `parsed` (TextFSM rows only; null for
parser none/genie), `success`, `node_id`.
```
{% set rows = commands_by_name['show ip int brief'].parsed %}
{% for row in rows %}{{ row.interface }}: {{ row.status }}{% endfor %}
{{ command.parsed if command.parsed is not none else command.raw }}
```
`commands` is a list in execution order; `commands_by_name` is keyed by the exact command string
(only the latest run of a duplicated command).

## parsed namespace (one shared namespace, keyed by each step's output_key)
Parse Cisco Config (default key `cisco_config`), always nested under `.running` / `.startup`:
```
parsed.cisco_config.running.hostname      .vrfs        .vlans       .l3_interfaces
parsed.cisco_config.running.access_lists  .route_maps  .aaa_servers  .aaa_servers.servers
parsed.cisco_config.running.routing.static / .ospf / .eigrp / .bgp
parsed.cisco_config.running.fhrp_groups   .port_channels  .banner  .unsupported
```
```
{% for server in parsed.cisco_config.running.aaa_servers.servers %}
tacacs-server host {{ server.address }}
{% endfor %}
```
Run Command with parser textfsm/genie stores under `parsed.<parsed_output_key>` (default
`parsed`, so `parsed.parsed`), one entry per command string, each `{ parsed, error }`. Use bracket
notation: `parsed.parsed['show ip interface brief'].parsed`. Genie output appears only here.

Batfish per-device steps write `parsed.<output_key>`: Extract Facts (default
`batfish_extract_facts`) -> `.parsed.Hostname`, `.parsed.NTP_Servers`, `.parsed.TACACS_Servers`,
`.error`. Never reference a flat `batfish.*` variable in a template body (editor preview only).

## Secrets
Rendered output can contain real secrets (e.g. `tacacs.shared_secret`, config-context credentials).
Never ask the user to paste secrets into the chat; reference variables instead.

## Template types
`jinja2` (rendered), `text` (literal), `textfsm` (a TextFSM parser definition, not Jinja).
