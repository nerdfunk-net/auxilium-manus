"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/** Built-in Help tab content for Get Client Data from CC. */
export function GetCatalystCenterClientDataHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads the <strong>wired clients</strong> of each switch from the Cisco
          Catalyst Center (Clients API, release 3.1 or newer) without logging
          into the device, and stores them for the question &ldquo;where is this
          MAC or IP?&rdquo; in the same tables as{" "}
          <HelpCode>Collect Client Data</HelpCode>. Place it after{" "}
          <HelpCode>Get from Catalyst Center</HelpCode>; devices from any other
          source leave through the failure outcome.
        </p>
      </HelpSection>

      <HelpSection title="lookback_hours">
        <p>
          How many hours back the controller looks (1&ndash;168, default 24).
          A client that was not seen within the window is not reported.
        </p>
        <HelpExample>lookback_hours = 48</HelpExample>
      </HelpSection>

      <HelpSection title="dry_run">
        <p>
          Records what would be queried and stores nothing.
        </p>
      </HelpSection>

      <HelpSection title="Where the data lands">
        <HelpExample>
          parsed.&lt;node id&gt;.client_data = {"{"}arp_entries, mac_entries,
          lookback_hours{"}"}
        </HelpExample>
        <p>
          The rows themselves are in the client data tables: MAC, VLAN and port
          for each client, plus its IP addresses. Ask the Net and the
          client-data page read them from there.
        </p>
      </HelpSection>

      <HelpWarning title="Not a live MAC table">
        <p>
          Catalyst Center reports the clients it saw in the window, and no VRF.
          A switch without clients is a success with no rows and replaces the
          older rows of that device. For one device name, the newest collection
          of this step and of Collect Client Data wins, whichever it came from.
        </p>
      </HelpWarning>
    </div>
  );
}
