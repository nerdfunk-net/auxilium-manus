"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/** Built-in Help tab content for Exists in Nautobot. */
export function ExistsInNautobotHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Checks whether each device already exists in Nautobot and routes it to{" "}
          <span className="font-medium text-foreground">exists</span> or{" "}
          <span className="font-medium text-foreground">non_existing</span>. A
          device whose lookup could not be performed (Nautobot error, IP
          expression resolved to nothing) goes to{" "}
          <span className="font-medium text-foreground">failure</span>.
        </p>
        <p>
          For devices routed to <HelpCode>exists</HelpCode> the Nautobot UUID is
          stored as <HelpCode>nautobot.id</HelpCode> (other keys of the{" "}
          <HelpCode>nautobot</HelpCode> bag are kept).
        </p>
      </HelpSection>

      <HelpSection title="nautobot_source_id">
        <p>The Nautobot source (Settings → Sources) to query.</p>
      </HelpSection>

      <HelpSection title="strategy">
        <p>
          <HelpCode>name</HelpCode> — a Nautobot device with the same name as the
          workflow device.
        </p>
        <p>
          <HelpCode>primary_ip</HelpCode> — a Nautobot device whose primary IPv4
          is the IP address.
        </p>
        <p>
          <HelpCode>interface_ip</HelpCode> — a Nautobot device that has the IP
          address assigned to any of its interfaces (not necessarily primary).
        </p>
      </HelpSection>

      <HelpSection title="ip_address (IP strategies only)">
        <p>
          A fixed address or a per-device <HelpCode>{"{path}"}</HelpCode>
          expression. Any <HelpCode>/prefix</HelpCode> is ignored.
        </p>
        <HelpExample>
          {"{device.primary_ip4}"}
          <br />
          {"{custom.mgmt_ip}"}
          <br />
          192.168.178.120
        </HelpExample>
      </HelpSection>

      <HelpSection title="case_insensitive_lookup (name strategy only)">
        <p>
          Match the name ignoring case — useful for sources such as Batfish that
          lowercase device names.
        </p>
      </HelpSection>

      <HelpSection title="Typical use">
        <p>
          Put this step before Add to Nautobot: wire{" "}
          <HelpCode>non_existing</HelpCode> to Add to Nautobot and{" "}
          <HelpCode>exists</HelpCode> to Update Device, which can read the UUID
          from <HelpCode>nautobot.id</HelpCode>.
        </p>
      </HelpSection>

      <HelpWarning title="Several matches">
        <p>
          If more than one Nautobot device matches, the first one returned is
          used.
        </p>
      </HelpWarning>
    </div>
  );
}
