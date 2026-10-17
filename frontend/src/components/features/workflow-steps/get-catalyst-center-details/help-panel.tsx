"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/** Built-in Help tab content for Get Details from Catalyst Center. */
export function GetCatalystCenterDetailsHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads structured facts about each device from the Cisco Catalyst
          Center Intent API — no SSH access needed. Place it after{" "}
          <HelpCode>Get from Catalyst Center</HelpCode>; devices from any other
          source fail with <HelpCode>not_catalyst_center_device</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Facts">
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>device</HelpCode> — the inventory record (serial, role,
            reachability, collection status, uptime, boot time).
          </li>
          <li>
            <HelpCode>software</HelpCode> — software type and version,
            platform and series. Read from the same controller call as{" "}
            <HelpCode>device</HelpCode>; ticking both costs one request.
          </li>
          <li>
            <HelpCode>interfaces</HelpCode> — one entry per interface.
          </li>
          <li>
            <HelpCode>vlans</HelpCode> — VLAN interfaces with number, IP and
            prefix.
          </li>
          <li>
            <HelpCode>compliance</HelpCode> — overall status and one entry per
            compliance type (running config, image, EoX, PSIRT, …).
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Where the data lands">
        <HelpExample>
          parsed.&lt;parsed_output_key&gt;.&lt;fact&gt; = {"{"}parsed, error{"}"}
        </HelpExample>
        <p>
          The same shape Run Command and Run Command via Catalyst Center use for
          parsed output, so Route on Attribute, Jinja templates and Log
          Attributes read it the same way.
        </p>
        <HelpWarning title="Partial failures">
          <p>
            A fact the controller cannot return is recorded as{" "}
            <HelpCode>parsed: null</HelpCode> plus an error text and the device
            still succeeds. The device only fails (failure outcome) when every
            selected fact failed.
          </p>
        </HelpWarning>
      </HelpSection>
    </div>
  );
}
