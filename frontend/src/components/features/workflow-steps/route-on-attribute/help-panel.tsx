"use client";

import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Route on Attribute.
 * Covers every Configuration control with practical examples.
 */
export function RouteOnAttributeHelpPanel(_props: PluginConfigPanelProps) {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Branches the workflow per device based on an attribute value. Each route
          rule maps matching values to a named outcome handle on the canvas. Use it
          to send IOS devices down one path and NX-OS down another, or to split
          devices that have a TACACS key from those that do not.
        </p>
        <p>
          Routes are evaluated top to bottom — the{" "}
          <span className="font-medium text-foreground">first match wins</span>.
        </p>
      </HelpSection>

      <HelpSection title="Attribute path">
        <p>
          <HelpCode>attribute_path</HelpCode> is the dot-path read from each
          device&apos;s context. Examples:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>device.network_driver</HelpCode> — Netmiko driver from inventory
          </li>
          <li>
            <HelpCode>nautobot.role.name</HelpCode> — Nautobot role
          </li>
          <li>
            <HelpCode>custom.tacacs_key</HelpCode> — user-defined attribute from
            Update Attribute or upstream steps
          </li>
        </ul>
        <HelpExample>
          attribute_path: device.network_driver
        </HelpExample>
      </HelpSection>

      <HelpSection title="Routes">
        <p>
          <HelpCode>routes</HelpCode> is an ordered list of rules. Each rule has:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>outcome</HelpCode> — canvas handle name (e.g.{" "}
            <HelpCode>ios</HelpCode>, <HelpCode>nxos</HelpCode>). Connect edges from
            this handle to downstream steps.
          </li>
          <li>
            <HelpCode>values</HelpCode> — comma-separated literals or special tokens
            that must match the resolved attribute.
          </li>
        </ul>
        <HelpExample>
          routes:
          <br />
          {"  "}- outcome: ios
          <br />
          {"    "}values: [cisco_ios, ios]
          <br />
          {"  "}- outcome: nxos
          <br />
          {"    "}values: [cisco_nxos, nxos]
        </HelpExample>
        <p>
          Use <span className="font-medium text-foreground">Add route</span> for more
          rules. At least one route is required. Put more specific rules above broader
          ones — first match wins.
        </p>
      </HelpSection>

      <HelpSection title="Special match tokens">
        <p>
          Besides literal strings, route values can use existence tokens (click the
          chip buttons in Configuration to insert):
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>{"{absent}"}</HelpCode> — attribute_path does not exist on the
            context.
          </li>
          <li>
            <HelpCode>{"{null}"}</HelpCode> — value is null.
          </li>
          <li>
            <HelpCode>{"{empty}"}</HelpCode> — value is an empty string, list, or
            object.
          </li>
          <li>
            <HelpCode>{"{exists}"}</HelpCode> — value is present and non-empty (e.g.
            check whether a TACACS+ key was found).
          </li>
        </ul>
        <HelpExample>
          routes:
          <br />
          {"  "}- outcome: has_key
          <br />
          {`    values: ["{exists}"]`}
          <br />
          {"  "}- outcome: missing_key
          <br />
          {`    values: ["{absent}", "{empty}"]`}
        </HelpExample>
      </HelpSection>

      <HelpSection title="Default outcome">
        <p>
          <HelpCode>default_outcome</HelpCode> is the handle used when no route
          matches. Example: <HelpCode>unmatched</HelpCode> for devices whose driver
          is not ios or nxos.
        </p>
        <HelpExample>
          default_outcome: unmatched
        </HelpExample>
        <HelpWarning title="Empty default fails the step">
          <p>
            Leave default_outcome empty to fail the step when nothing matches. Set a
            named default to send unmatched devices to a catch-all path instead.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Case sensitive">
        <p>
          <HelpCode>case_sensitive</HelpCode> controls literal matching (special
          tokens are unaffected). When off (default),{" "}
          <HelpCode>cisco_ios</HelpCode> matches <HelpCode>CISCO_IOS</HelpCode>. Enable
          when exact casing matters.
        </p>
        <HelpExample>
          case_sensitive: false
          <br />
          routes:
          <br />
          {"  "}- outcome: ios
          <br />
          {"    "}values: [cisco_ios]
        </HelpExample>
      </HelpSection>

      <HelpSection title="Outcomes">
        <p>
          Each configured route outcome plus <HelpCode>default_outcome</HelpCode>{" "}
          appears as a green output handle on the canvas node. Devices traverse
          exactly one handle per run.
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            Named route outcomes — device matched that rule&apos;s values.
          </li>
          <li>
            Default outcome — no rule matched; only when default_outcome is set.
          </li>
          <li>
            Step failure — no match and default_outcome is empty.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Ensure the attribute exists (inventory, Run Command, Update Attribute).
          </li>
          <li>Set attribute_path to the field you want to branch on.</li>
          <li>
            Add routes in priority order; use special tokens for presence checks.
          </li>
          <li>Set default_outcome for a catch-all path.</li>
          <li>Connect each outcome handle to the appropriate downstream branch.</li>
        </ol>
      </HelpSection>
    </div>
  );
}
