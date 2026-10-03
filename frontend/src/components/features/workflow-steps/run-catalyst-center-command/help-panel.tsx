"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/** Built-in Help tab content for Run Command via Catalyst Center. */
export function RunCatalystCenterCommandHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Runs read-only CLI commands on devices through the Cisco Catalyst
          Center command runner. The controller talks to the devices, so no SSH
          credential is needed in the workflow.
        </p>
        <p>
          Place it after <HelpCode>Get from Catalyst Center</HelpCode>. Devices
          from any other source fail with{" "}
          <HelpCode>not_catalyst_center_device</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Commands">
        <p>
          <HelpCode>commands</HelpCode> run in order on every device (1–20,
          each unique). Catalyst Center accepts only read-only{" "}
          <HelpCode>show</HelpCode>-class commands; anything else is reported as
          blocklisted and fails that device.
        </p>
        <HelpExample>
          show version
          <br />
          show ip interface brief
        </HelpExample>
      </HelpSection>

      <HelpSection title="Output">
        <p>
          The echoed command and the trailing device prompt are removed. The
          cleaned text of each command is stored as an artifact and listed under
          the device&apos;s command results for downstream steps such as Store
          Artifact or Filter Output.
        </p>
      </HelpSection>

      <HelpSection title="Parsing with TextFSM">
        <p>
          Set <HelpCode>parser</HelpCode> to <HelpCode>textfsm</HelpCode> to
          turn each command&apos;s output into rows using the ntc-templates
          library. The result is stored exactly like Run Command does:
        </p>
        <HelpExample>
          parsed.&lt;parsed_output_key&gt;.&lt;command&gt; = {"{"}parsed, error{"}"}
        </HelpExample>
        <p>
          Route on Attribute, Jinja templates and Log Attributes read it the
          same way for either step. The template family comes from the
          device&apos;s network driver (set by Get from Catalyst Center from the
          software type); use <HelpCode>network_driver_override</HelpCode> when
          a device has none.
        </p>
        <HelpWarning title="Non-fatal per command">
          <p>
            A command without a matching template gets{" "}
            <HelpCode>parsed: null</HelpCode> and an error text; the device
            still succeeds and the raw output is still stored. Not every{" "}
            <HelpCode>show</HelpCode> command has a template.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Timeout and batching">
        <p>
          <HelpCode>timeout</HelpCode> (1–300 seconds) is how long the
          controller may spend on one request. Devices are sent in batches of
          20, with at most three requests in flight at a time.
        </p>
        <HelpWarning title="Partial failures">
          <p>
            A failed batch, a missing output or a blocklisted command fails only
            the affected devices; they leave through the failure outcome while
            the rest continue through success.
          </p>
        </HelpWarning>
      </HelpSection>
    </div>
  );
}
