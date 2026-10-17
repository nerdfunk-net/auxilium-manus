"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Send Mail.
 * Covers every Configuration control with practical examples.
 */
export function SendMailHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Sends one email through an SMTP server — one message per step
          execution, not one per device. Use it to report that a workflow
          finished or that something needs attention.
        </p>
      </HelpSection>

      <HelpSection title="Mail server">
        <p>
          The step sends through the SMTP server an administrator configured
          under Settings → Mail: server, port, transport security, login and
          sender address are not step settings. The administrator&apos;s allowed
          recipient domains apply; a recipient outside them fails the step.
        </p>
        <HelpWarning title="Mail must be configured first">
          <p>
            If no server or sender is configured in Settings → Mail the step
            fails with a configuration error.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="to">
        <p>
          Recipient addresses: several may be separated by commas or
          semicolons. It supports{" "}
          <HelpCode>{"{path.to.value}"}</HelpCode> placeholders resolved
          against the first device, so the recipient can come from device data.
        </p>
        <HelpExample>
          to: ops@example.com; {"{custom.owner_email}"}
        </HelpExample>
      </HelpSection>

      <HelpSection title="subject / body">
        <p>
          Both support placeholders. In the{" "}
          <span className="font-medium text-foreground">subject</span>,{" "}
          <HelpCode>{"{path.to.value}"}</HelpCode> resolves against the first
          device (it must stay a single line). In the{" "}
          <span className="font-medium text-foreground">body</span> it is
          rendered once per device and the results are joined with newlines.
        </p>
        <p>
          <HelpCode>{"{devices}"}</HelpCode> renders every device name,
          comma-joined; <HelpCode>{"{device_count}"}</HelpCode> renders the
          count. A path that doesn&apos;t resolve renders as an empty string.
        </p>
        <HelpExample>
          subject: Config backup failed on {"{device.name}"}
          <br />
          <span className="text-muted-foreground">
            → Config backup failed on router1
          </span>
        </HelpExample>
        <HelpExample>
          body: {"{device.name}"} ({"{nautobot.location.name}"})
          <br />
          <span className="text-muted-foreground">
            → router1 (core)
            <br />→ router2 (edge)
          </span>
        </HelpExample>
        <HelpWarning title="Nothing to report">
          <p>
            If the subject, body or an address needs a device attribute but no
            device reaches this step (for example it is wired to an outcome
            that matched nothing), the step sends no mail and reports success.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            server accepted the message (or there was nothing to report).
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — the
            mail could not be sent: server unreachable, TLS or login failed,
            or a recipient was rejected. The step summary shows the error
            type and SMTP status code only.
          </li>
        </ul>
        <p>
          Invalid configuration (missing field, bad port, invalid address)
          fails the step itself.
        </p>
      </HelpSection>

      <HelpSection title="Fan-out">
        <p>
          Place this step after a <HelpCode>Fan In</HelpCode> node for one mail
          covering every device in the run. Placed inside fan-out children it
          sends once per child branch.
        </p>
      </HelpSection>
    </div>
  );
}
