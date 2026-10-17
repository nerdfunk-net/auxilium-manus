"use client";

import { HelpCode, HelpExample, HelpSection } from "../shared/step-help";

/** Built-in Help tab content for Get Health Status from Catalyst Center. */
export function GetCatalystCenterHealthHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads each device&apos;s health from the Cisco Catalyst Center:
          overall health, CPU and memory with their scores, communication and
          collection state, HA and stack status, maintenance mode and last boot
          time. Place it after <HelpCode>Get from Catalyst Center</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Where the data lands">
        <HelpExample>
          parsed.&lt;parsed_output_key&gt;.health = {"{"}parsed, error{"}"}
        </HelpExample>
        <p>
          Use Route on Attribute on, for example{" "}
          <HelpCode>parsed.catalyst_health.health.parsed.overall_health</HelpCode>{" "}
          to branch on a poor score. A device the controller returns no health
          for leaves through the failure outcome.
        </p>
      </HelpSection>
    </div>
  );
}
