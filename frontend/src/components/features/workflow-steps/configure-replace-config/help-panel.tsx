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
            If <HelpCode>skip_if_no_pending_changes</HelpCode> is on, diffs
            the target file against the running config first (
            <HelpCode>show archive config differences</HelpCode>). If
            there&apos;s no difference, the step skips straight to success
            without touching the device.
          </li>
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
          <li>
            If <HelpCode>verify_diff_after_replace</HelpCode> is on, diffs
            the target file against the running config again to confirm
            they actually match — <HelpCode>configure confirm</HelpCode>{" "}
            succeeding only proves the rollback timer was cancelled, not
            that every line applied.
          </li>
        </ol>
        <HelpWarning title="A diff mismatch after replace fails the step, even though the timer was confirmed">
          <p>
            <HelpCode>configure confirm</HelpCode> only proves the device
            cancelled its rollback timer — it doesn&apos;t prove the running
            config matches the target file. If{" "}
            <HelpCode>verify_diff_after_replace</HelpCode> finds a
            difference, the device fails with code{" "}
            <HelpCode>diff_mismatch</HelpCode> and the diff is stored as an
            artifact for review. If the verification diff command itself
            fails to run, the device fails with{" "}
            <HelpCode>post_verify_failed</HelpCode> rather than assuming
            success.
          </p>
        </HelpWarning>
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

      <HelpSection title="skip_if_no_pending_changes">
        <p>
          Default on. Before replacing, diffs the target file against the
          running config. If there are no differences, the step skips{" "}
          <HelpCode>configure replace</HelpCode>/
          <HelpCode>configure confirm</HelpCode> entirely and reports
          success — avoids cycling the device through a rollback timer for a
          no-op change. A non-empty pre-diff is stored as an artifact for
          review but does not block the replace. If the diff command itself
          fails to run (e.g. unsupported on this platform), the step
          proceeds with the replace unverified rather than blocking on a
          diagnostic command.
        </p>
      </HelpSection>

      <HelpSection title="verify_diff_after_replace">
        <p>
          Default on. After <HelpCode>configure confirm</HelpCode> succeeds,
          diffs the target file against the running config again. A
          non-empty diff means the running config still doesn&apos;t match
          the target despite the rollback timer being cancelled — the
          device fails with code <HelpCode>diff_mismatch</HelpCode> and the
          diff is stored as an artifact. Unlike the pre-check, a failure to
          run this diff also fails the device (code{" "}
          <HelpCode>post_verify_failed</HelpCode>), since the outcome can no
          longer be vouched for once <HelpCode>configure confirm</HelpCode>{" "}
          has already run.
        </p>
      </HelpSection>
    </div>
  );
}
