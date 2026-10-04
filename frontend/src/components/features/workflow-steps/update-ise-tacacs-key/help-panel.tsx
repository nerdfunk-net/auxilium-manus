"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Update ISE TACACS Key.
 * Covers every Configuration control with practical examples.
 */
export function UpdateIseTacacsKeyHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Sets <HelpCode>tacacsSettings.sharedSecret</HelpCode> on each workflow
          device in Cisco ISE. The new key comes from{" "}
          <HelpCode>new_key</HelpCode> — a per-device expression resolved
          against the device&apos;s attribute bags.
        </p>
        <p>
          Use after Get ISE TACACS Key (to read the current key) or Add to ISE
          (to register a device with an initial key), then chain this step when
          you need to rotate or standardise secrets in ISE.
        </p>
      </HelpSection>

      <HelpSection title="ISE source">
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Configure Source</span>{" "}
          (or Edit Source) and choose a source created under Settings → Sources
          → Cisco ISE. The step stores that source&apos;s ID as{" "}
          <HelpCode>ise_source_id</HelpCode>.
        </p>
        <HelpExample>
          ise_source_id: prod-ise
        </HelpExample>
        <HelpWarning title="Source required">
          <p>
            Without a valid source the step cannot connect to ISE. A pre-flight
            connection failure emits a step-level <HelpCode>failure</HelpCode>{" "}
            outcome.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="New key">
        <p>
          <HelpCode>new_key</HelpCode> is the TACACS+ shared secret to write in
          ISE. It must be a <HelpCode>{"{path.to.value}"}</HelpCode> expression
          resolved per device, filled by Secret Get, Secret Generate or Generate
          Password. Literal values and <HelpCode>| default(&apos;…&apos;)</HelpCode>{" "}
          fallbacks are rejected because step config is stored in the workflow
          definition and mirrored to git.
        </p>

        <HelpExample>
          new_key: {"{tacacs.new_key}"}
        </HelpExample>

        <HelpWarning title="Key required">
          <p>
            An empty <HelpCode>new_key</HelpCode> leaves the step unconfigured.
            Unresolved expressions mark individual devices failed but the step
            still emits <HelpCode>success</HelpCode> for survivors.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            step finished. Devices where the key was resolved and ISE accepted
            the update are updated. Per-device failures (unresolved expression,
            device not found, ISE rejected the update) mark that device failed
            but do not fail the step.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — ISE
            could not be reached or authentication failed — a condition affecting
            every device equally.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Configure a Cisco ISE source.</li>
          <li>
            Set <HelpCode>new_key</HelpCode> to an expression referencing an
            attribute filled by an upstream Secret Get, Secret Generate or
            Generate Password step.
          </li>
          <li>
            Place after inventory and optional Get ISE TACACS Key; verify ISE
            updates in run logs.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
