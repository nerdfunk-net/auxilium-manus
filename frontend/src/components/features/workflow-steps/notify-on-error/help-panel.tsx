"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Notify On Error.
 * Covers every Configuration control with practical examples.
 */
export function NotifyOnErrorHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Shared error sink for a workflow: wire many upstream steps&apos;{" "}
          <HelpCode>failure</HelpCode> outcome handles to this one node instead of
          adding a dedicated notify node after every step. Renders one message
          per accumulated error on each device in context — root-cause step,
          node, and message — instead of just the most recent one, and delivers
          it to one or both of two independently toggleable channels: a local
          Notification row, and/or a Mattermost post.
        </p>
      </HelpSection>

      <HelpSection title="message">
        <p>
          Template string stored as <HelpCode>message</HelpCode>. Rendered once
          per error accumulated on a device — a device that failed at two
          different points before reaching this node produces two rows — and
          reused verbatim as the Mattermost post text for that row when the
          Mattermost channel is enabled below.
        </p>
        <p className="font-medium text-foreground">Placeholder syntax</p>
        <p>
          Device attributes resolve the same way as Notify:{" "}
          <HelpCode>{"{device.name}"}</HelpCode>,{" "}
          <HelpCode>{"{nautobot.location.name}"}</HelpCode>. In addition, this step
          exposes the specific error being reported:{" "}
          <HelpCode>{"{error.step_id}"}</HelpCode> (the step type that failed),{" "}
          <HelpCode>{"{error.node_id}"}</HelpCode> (the specific canvas node),{" "}
          <HelpCode>{"{error.code}"}</HelpCode>, and{" "}
          <HelpCode>{"{error.message}"}</HelpCode>. A path that does not resolve
          renders as an empty string (no error).
        </p>
        <HelpExample>
          message: Device {"{device.name}"} failed at {"{error.step_id}"}:{" "}
          {"{error.message}"}
          <br />
          <span className="text-muted-foreground">
            → Device router1 failed at run-command: timeout after 30s
          </span>
        </HelpExample>
        <HelpWarning title="Devices with no accumulated errors are skipped">
          <p>
            If this node is accidentally wired to a <HelpCode>success</HelpCode>{" "}
            handle, devices with an empty error list produce no notification row
            — no blank or misleading messages get written.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="severity">
        <p>
          Always <HelpCode>error</HelpCode> — not configurable. Use the plain{" "}
          <HelpCode>Notify Local</HelpCode> step if you need
          <HelpCode>info</HelpCode>/<HelpCode>warning</HelpCode> severities.
        </p>
      </HelpSection>

      <HelpSection title="notify_local / notify_mattermost">
        <p>
          Two independent checkboxes controlling where the rendered message
          goes. <HelpCode>notify_local</HelpCode> (default on) writes a local
          Notification row per accumulated error, same as before this step
          could reach Mattermost. <HelpCode>notify_mattermost</HelpCode>{" "}
          (default off) additionally posts each row&apos;s rendered message to
          a Mattermost channel. Either, both, or — if you explicitly disable
          both — configuration is rejected with an error, since the step
          would otherwise do nothing.
        </p>
      </HelpSection>

      <HelpSection title="mattermost_source_id / team_name / channel_name">
        <p>
          Only used when <HelpCode>notify_mattermost</HelpCode> is enabled.
          The Mattermost source (URL + bot token) configured under Settings →
          Sources, plus the target team and channel name (not a channel ID —
          resolved to one at run time). The bot account behind the
          source&apos;s token must be a member of both. Same fields and same
          resolution mechanism as the <HelpCode>Notify Mattermost</HelpCode>{" "}
          step.
        </p>
        <HelpWarning title="Mattermost failures are best-effort">
          <p>
            A Mattermost post is attempted once per accumulated error. If the
            source, channel, or the post itself fails, it is logged as a
            warning and skipped — it does not fail this step, does not
            produce a <HelpCode>failure</HelpCode> outcome, and does not
            block local notifications or other rows from being posted.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — a
            notification was written for every accumulated error on every device
            with at least one (zero errors across all devices writes zero rows and
            is not an error).
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Add one Notify On Error node per workflow and wire every step&apos;s{" "}
            <HelpCode>failure</HelpCode> handle to it, instead of a notify node
            after each step.
          </li>
          <li>
            Place it after the last step whose failures it should catch — branches
            from earlier and later steps converge into it before it runs, once,
            over the union of every device that failed anywhere upstream.
          </li>
          <li>
            Safe under fan-out — each notification row is written independently
            per device/error, no shared external resource.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
