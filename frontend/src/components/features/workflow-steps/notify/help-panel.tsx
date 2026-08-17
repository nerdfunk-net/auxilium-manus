"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Notify.
 * Covers every Configuration control with practical examples.
 */
export function NotifyHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Writes one notification row per device in the workflow context to the
          notifications table — workflow name, workflow owner, timestamp, severity, and
          the rendered message. Notifications show up on the dashboard&apos;s
          Notifications card, so operators can see alerts without opening the run.
        </p>
      </HelpSection>

      <HelpSection title="message">
        <p>
          Template string stored as <HelpCode>message</HelpCode>. Recorded once per
          device. Use curly-brace placeholders to interpolate resolved attributes from
          the device context.
        </p>
        <p className="font-medium text-foreground">Placeholder syntax</p>
        <p>
          Use <HelpCode>{"{path.to.value}"}</HelpCode> where the path matches context
          keys — e.g. <HelpCode>{"{device.name}"}</HelpCode>,{" "}
          <HelpCode>{"{nautobot.location.name}"}</HelpCode>,{" "}
          <HelpCode>{"{custom.field}"}</HelpCode>. A path that does not resolve renders
          as an empty string (no error).
        </p>
        <HelpExample>
          message: Could not get config from device {"{device.name}"}
          <br />
          <span className="text-muted-foreground">
            → Could not get config from device router1
          </span>
        </HelpExample>
        <HelpExample>
          message: {"{device.name}"} at {"{nautobot.location.name}"} is unreachable
          <br />
          <span className="text-muted-foreground">→ router1 at Core is unreachable</span>
        </HelpExample>
        <HelpWarning title="Unresolved placeholders">
          <p>
            Missing or mistyped paths become empty strings in the message — verify
            attribute names after upstream steps (Nautobot, Run Command, etc.) populate
            context.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="severity">
        <p>
          One of <HelpCode>info</HelpCode>, <HelpCode>warning</HelpCode>, or{" "}
          <HelpCode>error</HelpCode>. Stored on every notification row written by this
          step and shown as a colored badge on the dashboard card.
        </p>
        <HelpExample>severity: info — routine status update</HelpExample>
        <HelpExample>severity: warning — a device was unreachable or skipped</HelpExample>
        <HelpExample>severity: error — a required operation failed</HelpExample>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — a
            notification was written for each device in context (zero devices writes
            zero rows and is not an error).
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Wire Notify to the <HelpCode>failure</HelpCode> handle of an upstream step
            (e.g. Get Device Configs) to alert on per-device failures.
          </li>
          <li>
            Use device identity (<HelpCode>device.name</HelpCode>) in the message so the
            dashboard card and Step Result viewer clearly identify which device the
            notification refers to.
          </li>
          <li>
            Safe under fan-out — each notification row is written independently per
            device, no shared external resource.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
