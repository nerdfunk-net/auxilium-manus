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
run.timestamp`}</CodeBlock>
            <p>
              Populated only if the matching step ran earlier in the
              workflow:
            </p>
            <CodeBlock>{`nautobot.*   — from "Get Nautobot Attributes" (or the editor preview)
git.*        — from "Get Git Devices"
ise.*        — from "Get from ISE"
tacacs.*     — from "Get from ISE" (only when that device has a
               TACACS shared secret configured in ISE)`}</CodeBlock>
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

          <Section title="Parsed Cisco configuration">
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
              When the workflow&apos;s Parse Cisco Config step is configured
              for only <code>running</code> or only <code>startup</code>{" "}
              (instead of the default <code>both</code>), the model sits
              directly under <code>cisco_config</code> — e.g.{" "}
              <code>parsed.cisco_config.hostname</code> — rather than nested
              under <code>.running</code>/<code>.startup</code>. The template
              editor&apos;s <strong>Get Configs</strong> checkbox always
              fetches both, matching the nested shape above.
            </p>
            <p>Example — render a TACACS+ stanza from the parsed AAA servers:</p>
            <CodeBlock>{`{% for server in parsed.cisco_config.running.aaa_servers.servers %}
tacacs-server host {{ server.address }}
{% endfor %}`}</CodeBlock>
          </Section>

          <Section title="Accessing command output (one command)">
            <p>
              After a <strong>Run Command</strong> step, its output is
              available as <code>command</code>:
            </p>
            <CodeBlock>{`command.name     the exact command string, e.g. "show ip int brief"
command.raw      the raw text output
command.parsed   the TextFSM-parsed rows (only set if "use_textfsm" was
                 checked on the Run Command step — otherwise it is null
                 and you should use command.raw instead)`}</CodeBlock>
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
              <code>success</code>, <code>node_id</code>.
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
