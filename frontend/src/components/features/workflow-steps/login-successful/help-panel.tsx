"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Login Successful.
 * Covers every Configuration control with practical examples.
 */
export function LoginSuccessfulHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Attempts an SSH login to every device with a configured credential and
          routes each device to{" "}
          <span className="font-medium text-foreground">success</span> or{" "}
          <span className="font-medium text-foreground">failure</span> based on
          whether authentication succeeds — a credential gate before running
          commands or pulling configuration.
        </p>
        <p>
          A successful login leaves the SSH session in the run&apos;s session
          pool, so later network steps that use the same credential can reuse
          the connection.
        </p>
      </HelpSection>

      <HelpSection title="Credential reference">
        <p>
          <HelpCode>credential_reference</HelpCode> selects an SSH credential
          from Settings → Credentials. Only active, non-expired SSH credentials
          appear in the dropdown. The value stored is the credential{" "}
          <span className="font-medium text-foreground">name</span>, not its
          internal ID.
        </p>
        <HelpExample>
          credential_reference: network-admin-ssh
          <br />
          <span className="text-muted-foreground">
            → username/password from that credential record
          </span>
        </HelpExample>
        <HelpWarning title="SSH credential required">
          <p>
            Without a credential the step cannot connect. If no SSH credentials
            exist, the Configuration panel shows &quot;No SSH credentials in
            Settings → Credentials&quot;.
          </p>
        </HelpWarning>
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

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — SSH
            authentication succeeded and the session is alive.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> —
            authentication failed, the host was unreachable, the device has no
            hostname/IP, or the connection attempt errored.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Place Login Successful after an inventory step (and optionally after Reachable).</li>
          <li>Select the SSH credential that should be validated.</li>
          <li>
            Connect <span className="font-medium text-foreground">success</span>{" "}
            to steps that need a working login, and{" "}
            <span className="font-medium text-foreground">failure</span> to a
            branch that logs or skips devices that could not authenticate.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
