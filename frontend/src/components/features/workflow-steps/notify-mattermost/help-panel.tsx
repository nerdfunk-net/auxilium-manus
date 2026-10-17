"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Notify Mattermost.
 * Covers every Configuration control with practical examples.
 */
export function NotifyMattermostHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Posts one message to a Mattermost channel via a configured
          Mattermost source, team, and channel — one HTTP call per step
          execution, not one per device. Use it to report that a workflow
          finished successfully or that something went wrong.
        </p>
      </HelpSection>

      <HelpSection title="mattermost_source_id">
        <p>
          The Mattermost source (URL + bot token) configured under Settings →
          Sources. Only the source ID is stored on the step; credentials are
          resolved from settings at run time.
        </p>
      </HelpSection>

      <HelpSection title="team_name / channel_name">
        <p>
          The Mattermost team and channel name to post to (not a channel ID
          — the step resolves the name to an ID at run time). The bot
          account behind the source&apos;s token must be a member of both.
        </p>
      </HelpSection>

      <HelpSection title="message">
        <p>
          Message text posted to the channel. Supports curly-brace
          placeholders.
        </p>
        <p className="font-medium text-foreground">Per-device placeholders</p>
        <p>
          <HelpCode>{"{path.to.value}"}</HelpCode> resolves against the{" "}
          <span className="font-medium text-foreground">first device</span>{" "}
          in the workflow context — e.g. <HelpCode>{"{device.name}"}</HelpCode>,{" "}
          <HelpCode>{"{nautobot.location.name}"}</HelpCode>. A path that
          doesn&apos;t resolve renders as an empty string.
        </p>
        <p className="font-medium text-foreground">Run-level placeholders</p>
        <p>
          <HelpCode>{"{devices}"}</HelpCode> renders every device name in
          context, comma-joined. <HelpCode>{"{device_count}"}</HelpCode>{" "}
          renders the device count. Use these for a multi-device summary
          instead of a single device&apos;s name.
        </p>
        <HelpExample>
          message: {"{device.name}"} config backup failed
          <br />
          <span className="text-muted-foreground">
            → router1 config backup failed
          </span>
        </HelpExample>
        <HelpExample>
          message: Workflow finished: {"{device_count}"} device(s) (
          {"{devices}"})
          <br />
          <span className="text-muted-foreground">
            → Workflow finished: 3 device(s) (router1, router2, router3)
          </span>
        </HelpExample>
        <HelpWarning title="Unresolved placeholders">
          <p>
            Missing or mistyped paths become empty strings — verify
            attribute names after upstream steps (Nautobot, Run Command,
            etc.) populate context.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            message posted to the channel.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — the
            channel couldn&apos;t be resolved or the post failed (bad
            source/team/channel, auth error, Mattermost unreachable).
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Wire Notify Mattermost to the <HelpCode>success</HelpCode> and/or{" "}
            <HelpCode>failure</HelpCode> handle of an upstream step to report
            that step&apos;s outcome — a node wired to a{" "}
            <HelpCode>failure</HelpCode> handle only sees the devices that
            failed.
          </li>
          <li>
            <span className="font-medium text-foreground">Fan-out:</span>{" "}
            place this step after a{" "}
            <HelpCode>Fan In</HelpCode> node for one summary message covering
            every device in the run. Placed inside fan-out children instead,
            it posts once per child branch.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
