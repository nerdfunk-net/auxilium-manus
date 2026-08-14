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
          <HelpCode>configure replace ... time N force</HelpCode>, which
          schedules an automatic on-device rollback after N minutes. For
          each device, in order:
        </p>
        <ol className="list-decimal space-y-1 pl-5">
          <li>Captures a Genie &quot;interface&quot; snapshot (baseline).</li>
          <li>
            Runs <HelpCode>configure replace</HelpCode> with the configured
            filename, filesystem, and timeout.
          </li>
          <li>Captures a second &quot;interface&quot; snapshot.</li>
          <li>Diffs the two snapshots via Genie.</li>
          <li>
            Only if the diff is identical, sends{" "}
            <HelpCode>configure confirm</HelpCode> to cancel the rollback
            timer.
          </li>
        </ol>
        <HelpWarning title="A detected difference or lost connection means the device reverts itself">
          <p>
            If the post-change snapshot can&apos;t be captured at all, or the
            diff shows any change, <HelpCode>configure confirm</HelpCode> is
            deliberately <span className="font-medium">not</span> sent — the
            step reports failure and the device automatically reverts to its
            pre-change configuration once <HelpCode>timeout_minutes</HelpCode>{" "}
            elapses.
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
            → configure replace bootflash:startup-config-new.cfg time 2 force
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
