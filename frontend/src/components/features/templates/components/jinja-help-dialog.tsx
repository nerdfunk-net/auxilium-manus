"use client";

import type { ReactNode } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface JinjaHelpDialogProps {
  open: boolean;
  onClose: () => void;
}

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="overflow-x-auto rounded-md border bg-muted/30 p-3 font-mono text-xs text-foreground">
      {children}
    </pre>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      <div className="space-y-2 text-sm text-muted-foreground">{children}</div>
    </section>
  );
}

export function JinjaHelpDialog({ open, onClose }: JinjaHelpDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="flex max-h-[85vh] max-w-3xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>Writing a Jinja2 template</DialogTitle>
          <DialogDescription>
            Reference for variables available when a template is rendered in a
            workflow or previewed in the template editor.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
          <Section title="How rendering works">
            <p>
              A template is rendered once per device. Every field below is
              scoped to that one device — there is no cross-device access
              inside a template.
            </p>
          </Section>

          <Section title="Device and workflow variables">
            <p>Always available, regardless of which steps ran upstream:</p>
            <CodeBlock>{`device.name              device.hostname
device.id                device.primary_ip4
device.platform          device.network_driver
device.source            device.source_id

workflow.id              run.id
run.timestamp            run.date`}</CodeBlock>
            <p>
              Populated only if the matching step ran earlier in the
              workflow:
            </p>
            <CodeBlock>{`nautobot.*        — "Get Nautobot Attributes" (or the editor preview).
                    Also written by "Config to Attributes",
                    "Set Default Attributes" and "Add to Nautobot".
git.*             — "Get Git Devices"
ise.*             — "Get from ISE"
tacacs.*          — "Get from ISE" / "Get ISE TACACS Key" (only when that
                    device has a TACACS shared secret configured in ISE)
command,          — "Run Command" — see "Accessing command output" below
commands,
commands_by_name
parsed.*          — "Parse Cisco Config", "Run Command" (parser =
                    textfsm/genie), the pyATS steps, and the
                    content/compare steps. One shared namespace, keyed by
                    each step's output_key — see "The parsed namespace".
data.*            — "Read from File" (its default destination). "Read from
                    File", "Update Attribute" and "Set Default Attributes"
                    each write to a namespace you name in their
                    destination path — "data" is only the default. In the
                    editor, "Load" a YAML/JSON file with the same
                    destination path to preview it.
pyats_testbed.*   — "Add pyATS Testbed" (internal plumbing for the pyATS
                    shim — you won't normally reference this in a template)
run_input.*       — the workflow's static attributes — see below`}</CodeBlock>
          </Section>

          <Section title="Static attributes (run_input)">
            <p>
              A workflow can declare <strong>static attributes</strong> — named
              values an operator types in when starting that workflow
              manually (workflow builder → Properties panel → Static
              Attributes, with a name, type, optional default, and whether a
              value is required). Whatever the operator supplies (or the
              declared default, if they leave it blank) is available to every
              device in the run as <code>run_input</code>:
            </p>
            <CodeBlock>{`run_input.vlan_id
run_input.note
run_input.confirm`}</CodeBlock>
            <p>
              Unlike <code>nautobot</code>, <code>ise</code> or{" "}
              <code>parsed</code>, this isn&apos;t populated by a step running
              earlier in the canvas — it comes from the workflow itself, so
              it&apos;s available to every device from the very first step
              onward. The tradeoff: a given <code>run_input.&lt;name&gt;</code>{" "}
              only exists for workflows that actually declare that attribute.
              If this template is reused by more than one workflow, only
              reference names every one of those workflows declares — or
              guard with <code>{"{% if run_input is defined %}"}</code>.
            </p>
            <p>
              Example — apply a VLAN supplied at trigger time, with a
              confirmation flag:
            </p>
            <CodeBlock>{`{% if run_input.confirm %}
vlan {{ run_input.vlan_id }}
 name {{ run_input.note }}
{% else %}
! Skipping VLAN {{ run_input.vlan_id }} — confirm was not set
{% endif %}`}</CodeBlock>
            <p>
              A boolean-typed attribute renders through <code>{"{{ }}"}</code>{" "}
              the same way any Python boolean does in Jinja —{" "}
              <code>True</code>/<code>False</code>, capitalized — even though
              <code>{"{% if %}"}</code> checks work as expected either way.
            </p>
          </Section>

          <Section title="Nautobot attributes">
            <p>
              After <strong>Get Nautobot Attributes</strong> (or when you select
              a test device in the template editor), the full Nautobot record
              for that device is available as <code>nautobot</code>. Base fields
              are always present; optional groups (config context, custom
              fields, interfaces, tags, …) appear only when you select them.
            </p>
            <p>
              For a device named <strong>lab</strong>, the bag might look like
              this (abbreviated):
            </p>
            <CodeBlock>{`{
  "name": "lab",
  "hostname": "lab",
  "serial": "12345",
  "primary_ip4": { "host": "192.168.178.240", "address": "192.168.178.240/24", ... },
  "role": { "name": "Network" },
  "status": { "name": "Active" },
  "platform": { "name": "cisco_ios", "network_driver": "cisco_ios", ... },
  "location": { "name": "City A", "parent": { "name": "State A" }, ... },
  "device_type": { "model": "virtual", "manufacturer": { "name": "Cisco" }, ... }
}`}</CodeBlock>
            <p>Common paths in templates:</p>
            <CodeBlock>{`nautobot.name                 nautobot.hostname
nautobot.role.name            nautobot.status.name
nautobot.platform.name        nautobot.platform.network_driver
nautobot.location.name        nautobot.location.parent.name
nautobot.primary_ip4.host     nautobot.device_type.model
nautobot.device_type.manufacturer.name`}</CodeBlock>
            <p>Example — branch on role and status for device <strong>lab</strong>:</p>
            <CodeBlock>{`Device: {{ device.name }}
Role: {{ nautobot.role.name }}
Status: {{ nautobot.status.name }}

{% if nautobot.role.name == 'Network' and nautobot.status.name == 'Active' %}
!
hostname {{ device.name }}
!
{% else %}
! Skipping {{ device.name }}: role={{ nautobot.role.name }}, status={{ nautobot.status.name }}
{% endif %}`}</CodeBlock>
          </Section>

          <Section title="ISE and TACACS variables">
            <p>
              After <strong>Get from ISE</strong>, the raw ISE record for
              that device is available as <code>ise</code> — the exact same
              JSON ISE&apos;s API returns, including its IP list, group
              memberships, and (if configured) TACACS/RADIUS settings:
            </p>
            <CodeBlock>{`ise.name                         ise.id
ise.description                  ise.profileName
ise.NetworkDeviceIPList          ise.NetworkDeviceGroupList
ise.is_group_or_prefix           ise.tacacsSettings.sharedSecret`}</CodeBlock>
            <p>
              Because drilling into{" "}
              <code>ise.tacacsSettings.sharedSecret</code> is easy to get
              wrong, the TACACS shared secret is also surfaced directly as
              its own variable:
            </p>
            <CodeBlock>{`tacacs.shared_secret`}</CodeBlock>
            <p>Example — a TACACS server stanza using the device&apos;s own key:</p>
            <CodeBlock>{`{% if tacacs is defined %}
tacacs-server host 10.10.10.5 key {{ tacacs.shared_secret }}
{% else %}
! No TACACS shared secret configured for {{ device.name }} in ISE
{% endif %}`}</CodeBlock>
            <p>
              <code>tacacs</code> only exists when the ISE device actually has
              a shared secret set (a RADIUS-only device won&apos;t have one)
              — always guard with{" "}
              <code>{"{% if tacacs is defined %}"}</code> rather than
              assuming it&apos;s there. Note the rendered output contains the
              real secret in plain text, so treat wherever you store or view
              it (run logs, saved artifacts) accordingly.
            </p>
          </Section>

          <Section title="The parsed namespace">
            <p>
              Several steps write structured data into one shared{" "}
              <code>parsed</code> namespace, each under its own key so they
              never collide. The key is that step&apos;s <code>output_key</code>{" "}
              (Parse Cisco Config, the pyATS steps, and the content/compare
              steps like Filter Output, Merge Content, Update Content, Compare
              Data) or <code>parsed_output_key</code> (Run Command). What
              follows is the <em>shape</em> each step writes — the namespace
              itself is always the same one.
            </p>
            <p className="font-medium text-foreground">
              Parse Cisco Config
            </p>
            <p>
              After a <strong>Parse Cisco Config</strong> step (or checking{" "}
              <strong>Get Configs</strong> in the template editor), the
              device&apos;s running and startup configuration — fetched and
              parsed with the same <code>cisco-config-parser</code> library the
              step uses — is available as <code>parsed</code>, keyed by that
              step&apos;s <code>output_key</code> (default{" "}
              <code>cisco_config</code>):
            </p>
            <CodeBlock>{`parsed.cisco_config.running.hostname     parsed.cisco_config.startup.hostname
parsed.cisco_config.running.vrfs         parsed.cisco_config.running.vlans
parsed.cisco_config.running.l3_interfaces
parsed.cisco_config.running.access_lists parsed.cisco_config.running.route_maps
parsed.cisco_config.running.aaa_servers  parsed.cisco_config.running.aaa_servers.servers
parsed.cisco_config.running.routing.static
parsed.cisco_config.running.routing.ospf
parsed.cisco_config.running.routing.eigrp
parsed.cisco_config.running.routing.bgp
parsed.cisco_config.running.fhrp_groups  parsed.cisco_config.running.port_channels
parsed.cisco_config.running.banner       parsed.cisco_config.running.unsupported`}</CodeBlock>
            <p>
              The value is always nested under <code>.running</code> /{" "}
              <code>.startup</code>, whatever the Parse Cisco Config step&apos;s{" "}
              <code>config_source</code> is — the branch it didn&apos;t parse is{" "}
              <code>null</code>. The template editor&apos;s{" "}
              <strong>Get Configs</strong> checkbox fetches both, so a preview
              here matches a real run.
            </p>
            <p>Example — render a TACACS+ stanza from the parsed AAA servers:</p>
            <CodeBlock>{`{% for server in parsed.cisco_config.running.aaa_servers.servers %}
tacacs-server host {{ server.address }}
{% endfor %}`}</CodeBlock>

            <p className="font-medium text-foreground">Run Command</p>
            <p>
              When a <strong>Run Command</strong> step has its{" "}
              <code>parser</code> set to <code>textfsm</code> or{" "}
              <code>genie</code>, it normalizes each command&apos;s output and
              stores it — one entry per command — under its{" "}
              <code>parsed_output_key</code>. That key defaults to literally{" "}
              <code>parsed</code>, so the path starts{" "}
              <code>parsed.parsed</code>. Each command string is a key holding{" "}
              <code>{"{ parsed, error }"}</code>:
            </p>
            <CodeBlock>{`parsed.parsed['show ip interface brief'].parsed   the structured rows
parsed.parsed['show ip interface brief'].error    null, or why parsing
                                                  failed for that command`}</CodeBlock>
            <p>
              Use bracket notation — the command string is the key and usually
              contains spaces. Both parsers are best-effort per command: one
              they have no template for comes back with <code>error</code> set
              and <code>parsed</code> as <code>null</code> (the device still
              succeeds). Give each Run Command step a distinct{" "}
              <code>parsed_output_key</code> if a workflow parses more than
              once.
            </p>
            <p>
              This is the <strong>only</strong> place <code>genie</code>-parsed
              output appears. <code>command.parsed</code>,{" "}
              <code>commands</code> and <code>commands_by_name</code> carry
              TextFSM rows only — for a <code>genie</code> step they stay{" "}
              <code>null</code>. See <strong>Accessing command output</strong>{" "}
              below.
            </p>
            <p>Example — loop parsed interface rows from a TextFSM Run Command:</p>
            <CodeBlock>{`{% set rows = parsed.parsed['show ip interface brief'].parsed %}
{% for row in rows %}
! {{ row.intf }} {{ row.ipaddr }} {{ row.status }}
{% endfor %}`}</CodeBlock>
          </Section>

          <Section title="Accessing command output (one command)">
            <p>
              After a <strong>Run Command</strong> step, its output is
              available as <code>command</code>:
            </p>
            <CodeBlock>{`command.name     the exact command string, e.g. "show ip int brief"
command.raw      the raw text output
command.parsed   the TextFSM-parsed rows — set only when the Run Command
                 step's "parser" was "textfsm". Stays null for "none" and
                 for "genie" (genie output lands only in the parsed
                 namespace — see "The parsed namespace" above); fall back
                 to command.raw in those cases.
command.success  whether the command ran cleanly
command.node_id  canvas node id of the Run Command step that produced it`}</CodeBlock>
            <p>Example — loop over parsed interface rows:</p>
            <CodeBlock>{`{% for row in command.parsed %}
{{ row.interface }}: {{ row.status }}/{{ row.proto }}
{% endfor %}`}</CodeBlock>
            <p>Example — fall back to raw text when nothing was parsed:</p>
            <CodeBlock>{`{{ command.parsed if command.parsed is not none else command.raw }}`}</CodeBlock>
          </Section>

          <Section title="Running multiple commands">
            <p>
              A single Run Command step can run more than one command (and a
              workflow can have more than one Run Command step). Every
              command executed upstream is collected, in execution order,
              into two variables:
            </p>
            <CodeBlock>{`commands            a list of every command, in the order it ran
commands_by_name    the same commands, keyed by their exact command string`}</CodeBlock>
            <p>
              Each entry has the same fields as <code>command</code> above:{" "}
              <code>name</code>, <code>raw</code>, <code>parsed</code>,{" "}
              <code>success</code>, <code>node_id</code>. The same{" "}
              <code>parsed</code> rule applies — it holds TextFSM rows only.
              For a <code>genie</code> step, read{" "}
              <code>parsed.&lt;parsed_output_key&gt;</code> instead (see{" "}
              <strong>The parsed namespace</strong>).
            </p>
            <p>
              Pick a specific command by name — this is the clearest option
              when you know exactly which commands ran:
            </p>
            <CodeBlock>{`{% set interfaces = commands_by_name['show ip int brief'] %}
{% set version = commands_by_name['show version'] %}

Interfaces:
{% for row in interfaces.parsed %}
  - {{ row.interface }} ({{ row.status }})
{% endfor %}

Version: {{ version.parsed[0].version if version.parsed else version.raw }}`}</CodeBlock>
            <p>Or iterate over all of them without knowing their names in advance:</p>
            <CodeBlock>{`{% for cmd in commands %}
=== {{ cmd.name }} ===
{{ cmd.parsed if cmd.parsed is not none else cmd.raw }}
{% endfor %}`}</CodeBlock>
            <p>
              Or index by position, matching the order commands were listed
              in the Run Command step (fragile if that order changes later):
            </p>
            <CodeBlock>{`{{ commands[0].parsed }}   {# first command #}
{{ commands[1].parsed }}   {# second command #}`}</CodeBlock>
            <p>
              If the exact same command string ran more than once (e.g. two
              separate Run Command steps both running{" "}
              <code>show version</code>), <code>commands_by_name</code> keeps
              only the most recent run — use <code>commands</code> to see
              every run.
            </p>
          </Section>

          <Section title="A note on the template editor's preview">
            <p>
              The template editor mirrors the workflow step: open{" "}
              <strong>Configure commands</strong>, add the commands you want,
              toggle <code>use_textfsm</code>, and click{" "}
              <strong>Execute commands</strong>. The editor runs them against
              your selected test device, in order, and populates{" "}
              <code>command</code>, <code>commands</code> and{" "}
              <code>commands_by_name</code> exactly as they appear at workflow
              runtime — so a template you write and preview here behaves the
              same once it runs after real Run Command steps.
            </p>
            <p>
              The preview covers the TextFSM path only. It does not run{" "}
              <code>genie</code>, and it does not build the per-command{" "}
              <code>parsed.&lt;parsed_output_key&gt;</code> namespace that a
              real Run Command step writes when its <code>parser</code> is{" "}
              <code>textfsm</code> or <code>genie</code>. To preview a template
              that reads that namespace, add a <code>parsed</code> variable by
              hand (or <strong>Load</strong> one from a JSON file) shaped like{" "}
              <code>{"{ parsed: { \"<command>\": { parsed: [...], error: null } } }"}</code>
              . The same applies to <code>data</code> and any other
              attribute-bag namespace written by <strong>Read from File</strong>
              , <strong>Update Attribute</strong> or{" "}
              <strong>Set Default Attributes</strong>: there is no live step in
              the editor, so add or <strong>Load</strong> the namespace to
              preview against it.
            </p>
            <p>
              Selecting a test device also populates <code>device</code> (name,
              hostname, id, primary_ip4, platform, network_driver). Use{" "}
              <strong>Attributes</strong> to choose which Nautobot attribute
              groups to fetch into <code>nautobot</code> (config context, custom
              fields, interfaces, tags, …). These use the same query and field
              names as the <strong>Get Nautobot Attributes</strong> step, so{" "}
              <code>nautobot.config_context</code>,{" "}
              <code>nautobot.custom_fields</code> and the rest resolve
              identically in the editor and at runtime.
            </p>
            <p>
              Checking <strong>Get Configs</strong> fetches the selected test
              device&apos;s running and startup configuration over SSH (using
              the selected credential) and parses it with the same logic as
              the <strong>Parse Cisco Config</strong> step, populating{" "}
              <code>parsed.cisco_config</code>. It re-fetches automatically if
              you change the test device while the checkbox stays checked.
            </p>
            <p>
              Because a template isn&apos;t tied to one specific workflow,{" "}
              <code>run_input</code> has no live device to fetch real values
              from here. Instead, click the link icon next to this help
              button (<strong>Link a workflow&apos;s static attributes</strong>
              ) and pick a workflow — its declared static attributes appear as
              a <code>run_input</code> variable showing each name and its
              default (or <code>null</code> when required with no default),
              so you can see the exact keys to reference. This link is only a
              preview for writing the template: it is <strong>not</strong>{" "}
              saved with it, and resets the next time you open the editor.
            </p>
          </Section>

          <Section title="Undefined variables">
            <p>
              Referencing a variable that doesn&apos;t exist (for example,{" "}
              <code>command.parsed</code> when no Run Command step ran
              upstream) fails that device with{" "}
              <code>Undefined template variable: {"'…'"} is undefined</code>. That
              device is routed to the step&apos;s &quot;failure&quot; outcome
              instead of &quot;success&quot;.
            </p>
          </Section>

          <Section title="Full example">
            <p>
              Combines device identity, Nautobot role/status, and command output
              for device <strong>lab</strong>:
            </p>
            <CodeBlock>{`Device: {{ device.name }} ({{ device.primary_ip4 }})
Role: {{ nautobot.role.name }}
Status: {{ nautobot.status.name }}
Platform: {{ device.platform }}

{% if nautobot.status.name != 'Active' %}
! Device {{ device.name }} is not active — no config applied.
{% else %}
!
hostname {{ device.name }}
!
{% set interfaces = commands_by_name['show ip int brief'] %}
{% if interfaces and interfaces.parsed %}
! Interfaces on {{ nautobot.role.name }} device {{ device.name }}:
{% for row in interfaces.parsed %}
!   {{ row.interface }}: {{ row.status }}/{{ row.proto }}
{% endfor %}
{% endif %}
{% endif %}`}</CodeBlock>
          </Section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
