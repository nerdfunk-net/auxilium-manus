"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Configure Replace Config.
 * Covers every Configuration control with practical examples.
 */
export function ConfigureReplaceConfigHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Replaces a device&apos;s running configuration with a file already
          on its filesystem using Cisco&apos;s{" "}
          <HelpCode>configure replace ... force time N</HelpCode>, which
          schedules an automatic on-device rollback after N minutes. For
          each device, in order:
        </p>
        <ol className="list-decimal space-y-1 pl-5">
          <li>
            Runs <HelpCode>configure replace</HelpCode> with the configured
            filename, filesystem, and timeout.
          </li>
          <li>
            Reconnects and sends <HelpCode>configure confirm</HelpCode> to
            cancel the rollback timer.
          </li>
          <li>
            Reads the output of <HelpCode>configure confirm</HelpCode> to
            confirm the device actually had a pending timed change to
            confirm.
          </li>
        </ol>
        <HelpWarning title="A lost connection or an unconfirmable state means the device reverts itself">
          <p>
            Reconnecting to send <HelpCode>configure confirm</HelpCode>{" "}
            doubles as the connectivity check — if the replace broke
            reachability, that step fails outright and the device reverts on
            its own once <HelpCode>timeout_minutes</HelpCode> elapses. If the
            device instead responds with{" "}
            <HelpCode>%No Rollback Confirmed Change pending</HelpCode> (the
            timer already expired, or another session already confirmed it),
            the step also reports failure rather than assuming success.
          </p>
        </HelpWarning>
        <HelpWarning title="Requires an upstream Add Testbed step">
          <p>
            Credentials and device connection info come from the{" "}
            <HelpCode>pyats_testbed</HelpCode> bag written by an upstream Add
            Testbed step — this step has no credential field of its own. A
            typical flow is Get Configs → Update Content → Upload Config →
            Add Testbed → this step.
          </p>
        </HelpWarning>
        <HelpWarning title="Requires config archiving enabled on the device">
          <p>
            The <HelpCode>time N</HelpCode> / Rollback Confirmed Change
            behaviour this step relies on only works once config archiving is
            set up on the device. Without it, <HelpCode>configure replace</HelpCode>{" "}
            is rejected with{" "}
            <HelpCode>%Turn config archive on before using Rollback Confirmed Change</HelpCode>{" "}
            and the step fails with code{" "}
            <HelpCode>archive_not_configured</HelpCode>. Enable it once per
            device, e.g.:
          </p>
          <HelpExample>
            archive
            <br />
            &nbsp;path flash:archive
          </HelpExample>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="destination_filename">
        <p>
          Filename of the config file already present on the device — e.g.
          the same <HelpCode>destination_filename</HelpCode> an upstream
          Upload Config step wrote.
        </p>
        <HelpExample>
          destination_filename: startup-config-new.cfg
        </HelpExample>
      </HelpSection>

      <HelpSection title="file_system">
        <p>Filesystem on the device where the file lives.</p>
        <HelpExample>
          file_system: bootflash:
          <br />
          <span className="text-muted-foreground">
            → configure replace bootflash:startup-config-new.cfg force time 2
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="timeout_minutes">
        <p>
          Minutes passed as the <HelpCode>time N</HelpCode> argument — how
          long the device waits for <HelpCode>configure confirm</HelpCode>{" "}
          before auto-reverting. Whole number from 1 to 120 (the device&apos;s
          own accepted range).
        </p>
      </HelpSection>
    </div>
  );
}
