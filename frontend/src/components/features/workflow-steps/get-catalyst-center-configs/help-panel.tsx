"use client";

import { HelpCode, HelpSection, HelpWarning } from "../shared/step-help";

/** Built-in Help tab content for Get Config from Catalyst Center. */
export function GetCatalystCenterConfigsHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Fetches each device&apos;s running configuration from the Cisco
          Catalyst Center, without SSH access to the device. The text is stored
          as an artifact and referenced on the device, exactly like Get Configs
          does, so Compare Data, Store Artifact and Render Jinja Template work
          unchanged.
        </p>
        <p>
          Place it after <HelpCode>Get from Catalyst Center</HelpCode>. Devices
          from any other source fail with{" "}
          <HelpCode>not_catalyst_center_device</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Startup configuration">
        <p>
          Only the running configuration is available from the controller. Use
          Run Command via Catalyst Center with{" "}
          <HelpCode>show startup-config</HelpCode> if you need the startup
          configuration.
        </p>
      </HelpSection>

      <HelpSection title="Failures">
        <HelpWarning title="Per-device failures">
          <p>
            A device the controller cannot return a configuration for leaves
            through the failure outcome; the other devices continue through
            success.
          </p>
        </HelpWarning>
      </HelpSection>
    </div>
  );
}
