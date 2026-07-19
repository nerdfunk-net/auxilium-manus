"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Workflow Log.
 * Covers every Configuration control with practical examples.
 */
export function WorkflowLogHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Writes a formatted log line for every device in the workflow context. Messages
          appear in worker/run logs — useful for tracing progress, auditing which
          devices reached a point in the graph, or surfacing key attributes without
          dumping full context.
        </p>
        <p>
          Unlike Show Attributes, this step emits one concise line per device rather
          than serializing the entire context.
        </p>
      </HelpSection>

      <HelpSection title="message">
        <p>
          Template string stored as <HelpCode>message</HelpCode>. Logged once per
          device. Use curly-brace placeholders to interpolate resolved attributes from
          the device context.
        </p>
        <p className="font-medium text-foreground">Placeholder syntax</p>
        <p>
          Use <HelpCode>{"{path.to.value}"}</HelpCode> where the path matches context
          keys — e.g. <HelpCode>{"{device.name}"}</HelpCode>,{" "}
          <HelpCode>{"{device.network_driver}"}</HelpCode>,{" "}
          <HelpCode>{"{nautobot.location.name}"}</HelpCode>,{" "}
          <HelpCode>{"{custom.field}"}</HelpCode>. A path that does not resolve
          renders as an empty string (no error).
        </p>
        <HelpExample>
          message: Device {"{device.name}"}: {"{device.network_driver}"}
          <br />
          <span className="text-muted-foreground">
            → Device router1: cisco_ios
          </span>
        </HelpExample>
        <HelpExample>
          message: {"{device.name}"} at {"{nautobot.location.name}"} — backup started
          <br />
          <span className="text-muted-foreground">
            → router1 at Core — backup started
          </span>
        </HelpExample>
        <HelpExample>
          message: Device {"{device.name}"} processed from ISE
        </HelpExample>
        <HelpWarning title="Unresolved placeholders">
          <p>
            Missing or mistyped paths become empty strings in the log line — verify
            attribute names after upstream steps (Nautobot, Run Command, etc.) populate
            context.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — log lines
            written for each device in context. Review in run/worker logs.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — logging
            failed unexpectedly. Rare; check run logs.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Place after steps that populate the attributes you reference in{" "}
            <HelpCode>message</HelpCode>.
          </li>
          <li>
            Use device identity (<HelpCode>device.name</HelpCode>) plus one or two
            business fields for readable audit trails.
          </li>
          <li>
            Add multiple Workflow Log steps at different graph points to mark pipeline
            stages.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
