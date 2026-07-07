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
            Reference for the variables available when a template is rendered
            by the &quot;Render Jinja Template&quot; workflow step.
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
            <CodeBlock>{`nautobot.*   — from "Get Nautobot Attributes"
git.*        — from "Get Git Devices"`}</CodeBlock>
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
              The &quot;Execute command&quot; button in the template editor
              only runs a single ad-hoc command for testing, and populates
              just <code>command.raw</code>/<code>command.parsed</code> in
              that preview. It does not simulate <code>commands</code> or{" "}
              <code>commands_by_name</code> — those only appear once this
              template actually runs inside a workflow, after one or more
              real Run Command steps.
            </p>
          </Section>

          <Section title="Undefined variables">
            <p>
              Referencing a variable that doesn&apos;t exist (for example,{" "}
              <code>command.parsed</code> when no Run Command step ran
              upstream) fails that device with{" "}
              <code>Undefined template variable: '…' is undefined</code>. That
              device is routed to the step&apos;s &quot;failure&quot; outcome
              instead of &quot;success&quot;.
            </p>
          </Section>

          <Section title="Full example">
            <CodeBlock>{`Hostname: {{ device.name }} ({{ device.primary_ip4 }})
Platform: {{ device.platform }}

{% set interfaces = commands_by_name['show ip int brief'] %}
{% if interfaces and interfaces.parsed %}
Interfaces:
{% for row in interfaces.parsed %}
  {{ row.interface }}: {{ row.status }}/{{ row.proto }}
{% endfor %}
{% else %}
No interface data available.
{% endif %}`}</CodeBlock>
          </Section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
