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
          adding a dedicated notify node after every step. Writes one notification
          row per accumulated error on each device in context — root-cause step,
          node, and message — instead of just the most recent one.
        </p>
      </HelpSection>

      <HelpSection title="message">
        <p>
          Template string stored as <HelpCode>message</HelpCode>. Rendered once
          per error accumulated on a device — a device that failed at two
          different points before reaching this node produces two rows.
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
