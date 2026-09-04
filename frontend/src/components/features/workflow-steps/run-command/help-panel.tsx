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
          steps such as Filter Output, Merge Content, Compare Data, or Update
          Attribute — and, when a <HelpCode>parser</HelpCode> is enabled, structured
          per-command data for Route on Attribute and Jinja templates (see
          &quot;Using parsed output in another step&quot; below).
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

      <HelpSection title="Parser">
        <p>
          <HelpCode>parser</HelpCode> chooses whether — and how — command output is
          turned into structured data: <HelpCode>none</HelpCode> (default, raw text
          only), <HelpCode>textfsm</HelpCode> (netmiko/ntc-templates, no extra setup),
          or <HelpCode>genie</HelpCode> (Cisco&apos;s pyATS parsing library, via a
          configured pyATS source — that option is hidden until one exists under
          Settings → Sources).
        </p>
        <p>
          Whichever you pick, the parsed result lands in the <strong>same place</strong>{" "}
          on each device — <HelpCode>parsed.&lt;parsed_output_key&gt;.&quot;&lt;command&gt;&quot;</HelpCode>
          , nested as <HelpCode>{"{parsed, error}"}</HelpCode> — so downstream steps
          (Route on Attribute, Jinja templates, Log Attributes) read it the same way
          no matter which parser produced it.
        </p>
        <HelpExample>
          parser: textfsm
          <br />
          commands:
          <br />
          {"  "}- show ip interface brief
          <br />
          <span className="text-muted-foreground">
            → parsed.parsed.&quot;show ip interface brief&quot;.parsed holds the
            structured rows
          </span>
        </HelpExample>
        <HelpExample>
          parser: genie
          <br />
          pyats_source_id: lab-pyats
          <br />
          parsed_output_key: genie
          <br />
          <span className="text-muted-foreground">
            → parsed.genie.&quot;show version&quot;.parsed holds the structured result
          </span>
        </HelpExample>
        <p>
          <HelpCode>parsed_output_key</HelpCode> (default <HelpCode>parsed</HelpCode>)
          names where output lands on each device. Give each Run Command instance a
          distinct key if a workflow uses more than one with parsing enabled.
        </p>
        <HelpWarning title="Per-command failures don't fail the device">
          <p>
            Neither parser has a template/parser for every command. A command that
            can&apos;t be parsed comes back with <HelpCode>error</HelpCode> set and{" "}
            <HelpCode>parsed: null</HelpCode> for that command only — the device still
            reports success as long as the raw command execution itself succeeded.
            The same applies if the pyATS shim itself is unreachable: Genie parsing is
            skipped entirely for that run rather than failing already-successful
            devices.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Using parsed output in another step">
        <p>
          Once <HelpCode>parser</HelpCode> is set to <HelpCode>textfsm</HelpCode> or{" "}
          <HelpCode>genie</HelpCode>, any downstream step that reads attribute paths —
          Route on Attribute, Jinja templates, Log Attributes — can reach into the
          parsed rows with a dot path:
        </p>
        <HelpExample>
          parsed.&lt;parsed_output_key&gt;.&lt;command&gt;.parsed
        </HelpExample>
        <p>
          A path segment can also filter into a list of parsed rows by matching one of
          their fields — <HelpCode>list_field[field=value]</HelpCode> — since there is
          no numeric <HelpCode>[0]</HelpCode> index.
        </p>
        <p className="font-medium text-foreground">
          Example — flag devices where a TACACS+ server has no name assigned
        </p>
        <p>
          Run Command executes <HelpCode>show tacacs</HelpCode> with{" "}
          <HelpCode>parser: textfsm</HelpCode> (default{" "}
          <HelpCode>parsed_output_key: parsed</HelpCode>), producing one row per
          configured server:
        </p>
        <HelpExample>
          [{"{"}
          <br />
          {"  "}&quot;tacacs_server_name&quot;: &quot;ISE_SERVER_1&quot;,
          <br />
          {"  "}&quot;tacacs_server&quot;: &quot;10.10.20.77&quot;,
          <br />
          {"  "}...
          <br />
          {"}"}]
        </HelpExample>
        <p>
          A <span className="font-medium text-foreground">Route on Attribute</span>{" "}
          step placed after it picks that row by its (known) server IP, then checks
          whether the name is empty:
        </p>
        <HelpExample>
          attribute_path:
          <br />
          {"  "}parsed.parsed.show tacacs.parsed[tacacs_server=10.10.20.77]
          <br />
          {"    "}.tacacs_server_name
          <br />
          routes:
          <br />
          {"  "}- outcome: missing_name
          <br />
          {"    "}values: [&quot;{"{"}empty{"}"}&quot;, &quot;{"{"}absent{"}"}&quot;]
          <br />
          default_outcome: ok
        </HelpExample>
        <p>
          Devices route to <HelpCode>missing_name</HelpCode> when that server has no
          name (or the command didn&apos;t match/run), and to{" "}
          <HelpCode>ok</HelpCode> otherwise.
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
            Set driver override only when auto-detection fails; set{" "}
            <HelpCode>parser</HelpCode> to <HelpCode>textfsm</HelpCode> or{" "}
            <HelpCode>genie</HelpCode> when you rely on parsed output downstream.
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
