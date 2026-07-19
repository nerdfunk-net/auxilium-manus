"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Run Command.
 * Covers every Configuration control with practical examples.
 */
export function RunCommandHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Connects to each device in the workflow context over SSH and runs one or
          more CLI commands. Output is stored on the device context for downstream
          steps such as Filter Output, Merge Content, Compare Data, or Update Attribute.
        </p>
        <p>
          Requires devices from an upstream inventory step and a valid SSH credential
          from Settings → Credentials.
        </p>
      </HelpSection>

      <HelpSection title="Credential reference">
        <p>
          Select an SSH credential from the dropdown. The step stores{" "}
          <HelpCode>credential_reference</HelpCode> as the credential&apos;s name
          (not its internal ID). Username and password/key are resolved at run time.
        </p>
        <HelpExample>
          credential_reference: prod-ssh-admin
          <br />
          <span className="text-muted-foreground">
            → uses username/password from Settings → Credentials
          </span>
        </HelpExample>
        <HelpWarning title="SSH credential required">
          <p>
            The step cannot connect without a non-expired SSH credential. Create one
            under Settings → Credentials if the dropdown is empty.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Commands">
        <p>
          <HelpCode>commands</HelpCode> is an ordered list of CLI strings executed
          sequentially on each device. Use{" "}
          <span className="font-medium text-foreground">Add command</span> for more
          entries; at least one command is required.
        </p>
        <p>
          Each command&apos;s raw output is stored separately. Downstream steps can
          target a specific command via <HelpCode>source_command</HelpCode> (Filter
          Output, Compare Data) or use the first command when left unspecified.
        </p>
        <HelpExample>
          commands:
          <br />
          {"  "}- show version
          <br />
          {"  "}- show ip route
          <br />
          {"  "}- show running-config | include hostname
        </HelpExample>
        <p>
          Common patterns: <HelpCode>show version</HelpCode> for OS info,{" "}
          <HelpCode>show ip interface brief</HelpCode> for interfaces,{" "}
          <HelpCode>show running-config</HelpCode> for config snippets (prefer Get
          Device Configs for full configs).
        </p>
      </HelpSection>

      <HelpSection title="Network driver override">
        <p>
          <HelpCode>network_driver_override</HelpCode> replaces each device&apos;s
          inferred Netmiko driver for this step only. Leave empty to use the driver
          from device context (usually set by inventory or platform metadata).
        </p>
        <HelpExample>
          network_driver_override: cisco_ios
          <br />
          <span className="text-muted-foreground">
            → forces Netmiko cisco_ios even if context says otherwise
          </span>
        </HelpExample>
        <p>
          Use when platform detection is wrong or missing — e.g.{" "}
          <HelpCode>cisco_nxos</HelpCode>, <HelpCode>juniper_junos</HelpCode>,{" "}
          <HelpCode>arista_eos</HelpCode>. Match Netmiko driver names exactly.
        </p>
      </HelpSection>

      <HelpSection title="Use TextFSM">
        <p>
          When <HelpCode>use_textfsm</HelpCode> is enabled, command output is parsed
          with TextFSM when a matching template exists. Parsed rows are available on
          the device context for Jinja templates and attribute steps.
        </p>
        <HelpExample>
          use_textfsm: true
          <br />
          commands:
          <br />
          {"  "}- show ip interface brief
          <br />
          <span className="text-muted-foreground">
            → structured interface list when a TextFSM template is installed
          </span>
        </HelpExample>
        <p>
          Leave off for raw text output (default). Enable when you need structured
          data and have TextFSM templates for your platform/commands.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — all
            commands completed for the device (individual command errors may still
            appear in output).
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — SSH
            connection failed, authentication error, missing credential, or timeout.
            Check credential, reachability, and driver override.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Ensure devices are in context from an inventory step.</li>
          <li>Select an SSH credential.</li>
          <li>Add the commands you need; start with one command to validate connectivity.</li>
          <li>
            Set driver override only when auto-detection fails; enable TextFSM when
            you rely on parsed output downstream.
          </li>
          <li>
            Chain Filter Output before Compare Data if output contains volatile
            fields (uptime, timestamps).
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
