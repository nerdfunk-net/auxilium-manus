"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Reachable.
 * Covers every Configuration control with practical examples.
 */
export function ReachableHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Pings every device with ICMP echo requests and routes each device to{" "}
          <span className="font-medium text-foreground">success</span> or{" "}
          <span className="font-medium text-foreground">failure</span> based on
          how many replies came back within the timeout — a quick reachability
          gate before running commands or pulling configuration.
        </p>
      </HelpSection>

      <HelpSection title="Ping count">
        <p>
          <HelpCode>ping_count</HelpCode> is how many ICMP echo requests to send
          to each device.
        </p>
        <HelpExample>
          ping_count: 4
          <br />
          <span className="text-muted-foreground">
            → sends 4 pings to each device
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Required replies">
        <p>
          <HelpCode>required_replies</HelpCode> is the minimum number of
          replies that must come back for a device to be considered reachable.
          It cannot exceed <HelpCode>ping_count</HelpCode>.
        </p>
        <HelpExample>
          ping_count: 4
          <br />
          required_replies: 2
          <br />
          <span className="text-muted-foreground">
            → reachable once at least 2 of the 4 pings get a reply
          </span>
        </HelpExample>
        <HelpWarning title="required_replies cannot exceed ping_count">
          <p>
            The step fails validation up front if{" "}
            <HelpCode>required_replies</HelpCode> is greater than{" "}
            <HelpCode>ping_count</HelpCode> — no device can ever satisfy that.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Timeout">
        <p>
          <HelpCode>timeout_seconds</HelpCode> is how long to wait for each
          individual ping reply, in seconds.
        </p>
        <HelpExample>
          timeout_seconds: 2
          <br />
          <span className="text-muted-foreground">
            → each ping waits up to 2 seconds for a reply
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            device replied to at least <HelpCode>required_replies</HelpCode>{" "}
            pings.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — the
            device didn&apos;t reply enough times, has no hostname/IP to ping,
            or the ping attempt itself errored.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Place Reachable right after an inventory step.</li>
          <li>
            Set <HelpCode>ping_count</HelpCode>,{" "}
            <HelpCode>required_replies</HelpCode>, and{" "}
            <HelpCode>timeout_seconds</HelpCode> for how strict the check
            should be.
          </li>
          <li>
            Connect <span className="font-medium text-foreground">success</span>{" "}
            to the steps that should only run against reachable devices, and{" "}
            <span className="font-medium text-foreground">failure</span> to a
            branch that logs or skips unreachable ones.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
