"use client";

import {
  FanOutHelpSection,
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Get from List.
 * Covers every Configuration control with practical examples.
 */
export function GetFromListHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Adds a fixed list of devices to the workflow context as targets for
          downstream steps. Use when you already know the exact hostnames
          and/or IP addresses and do not need Nautobot, ISE, or Git to resolve
          the inventory — including devices with no DNS entry or no existing
          Nautobot record yet (e.g. get IP → log in → pull config → add to
          Nautobot).
        </p>
        <p>
          Each row becomes a workflow device with identity only — no
          platform or credentials until a later step enriches the context.
        </p>
      </HelpSection>

      <HelpSection title="Devices">
        <p>
          <HelpCode>devices</HelpCode> is a list of rows, each with a{" "}
          <HelpCode>name</HelpCode> field and an <HelpCode>ip_address</HelpCode>{" "}
          field. At least one of the two must be filled in per row — you can
          set just a name, just an IP address, or both. Click the plus button
          to add rows; use the minus button to remove a row (at least one row
          always remains).
        </p>
        <p>
          When a row has an IP address, it becomes the device&apos;s
          <HelpCode>primary_ip4</HelpCode> and is what downstream steps
          (Reachable, Get Device Configs, Run Command, ...) connect to.
          Otherwise the name is used as the hostname. A row with only an IP
          address (no name) is shown downstream using that IP as its display
          name.
        </p>
        <HelpExample>
          devices:
          <br />
          {"  "}- name: router1.example.com
          <br />
          {"  "}- name: router2.example.com
          <br />
          {"    "}ip_address: 10.0.0.6
          <br />
          {"  "}- ip_address: 10.0.0.5
        </HelpExample>
        <HelpWarning title="At least one field required per row">
          <p>
            Blank rows (both name and IP address empty) are ignored at run
            time, but you must configure at least one non-empty row. The
            Configuration panel shows &quot;Enter a name and/or IP address for
            at least one device&quot; until you do. An invalid IP address
            format fails the step with a clear error naming the row.
          </p>
        </HelpWarning>
      </HelpSection>

      <FanOutHelpSection />

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — all
            configured devices were added to context.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — no
            valid devices (empty list after trimming).
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Enter one or more device names and/or IP addresses.</li>
          <li>
            Enable fan-out when the next steps are expensive per device (Get
            Device Configs, Run Command).
          </li>
          <li>
            Chain Get Nautobot Attributes or Get Device Configs to enrich devices
            if you need IP or platform data.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
