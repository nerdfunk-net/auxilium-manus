"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Get & Parse Config.
 * Covers every Configuration control with practical examples.
 */
export function GetPyatsConfigHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Fetches each device&apos;s running configuration via the pyATS shim
          and parses it with Genie into structured data — the Genie-powered
          alternative to Parse Cisco Config, which uses a lighter-weight
          parser instead. Startup config is intentionally out of scope:
          Genie has no parser for <HelpCode>show startup-config</HelpCode> on
          any platform, so raw config capture (running or startup) stays the
          job of Get Device Configs instead.
        </p>
        <p>
          The parsed result is written to{" "}
          <HelpCode>device.parsed.{"{output_key}"}</HelpCode> as{" "}
          <HelpCode>{"{ running: ... }"}</HelpCode> for downstream Render
          Jinja Template or Log Attributes steps.
        </p>
        <HelpWarning title="Requires an upstream Add Testbed step">
          <p>
            This step reads its device connection details and credential from
            the <HelpCode>pyats_testbed</HelpCode> bag written by an Add
            Testbed step earlier in the workflow — it has no credential or
            source configuration of its own.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Output key">
        <p>
          <HelpCode>output_key</HelpCode> names the slot where the parsed
          result is stored on each device. Downstream steps and templates
          reference <HelpCode>device.parsed.{"{output_key}"}</HelpCode>.
        </p>
        <HelpExample>
          output_key: pyats_config
          <br />
          <span className="text-muted-foreground">→ device.parsed.pyats_config.running</span>
        </HelpExample>
      </HelpSection>
    </div>
  );
}
