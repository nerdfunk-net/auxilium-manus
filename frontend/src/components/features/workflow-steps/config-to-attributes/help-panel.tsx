"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Config to Attributes.
 * Covers every Configuration control with practical examples.
 */
export function ConfigToAttributesHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads a device&apos;s parsed Cisco config (written by an upstream{" "}
          <span className="font-medium text-foreground">Parse Cisco Config</span>{" "}
          step) and populates its Nautobot attribute bag — purely in-memory, no
          Nautobot connection is made here. A later{" "}
          <span className="font-medium text-foreground">Add to Nautobot</span> step
          (with <HelpCode>interfaces_source: nautobot_origin</HelpCode>) can then
          create those interfaces for real.
        </p>
        <p>
          Currently supports one attribute group:{" "}
          <span className="font-medium text-foreground">Layer3 Interfaces</span> —
          name, status, type, description, IP address (with secondary), and
          enabled state. More groups will be added later.
        </p>
      </HelpSection>

      <HelpSection title="Config source">
        <p>
          Choose which parsed config to read attribute values from —{" "}
          <HelpCode>running</HelpCode> or <HelpCode>startup</HelpCode> (exactly
          one).
        </p>
        <HelpExample>
          config_source: running
          <br />
          <span className="text-muted-foreground">
            → reads parsed.{"{parsed_key}"}.running.l3_interfaces if the upstream
            step parsed both, or parsed.{"{parsed_key}"}.l3_interfaces directly if
            it only parsed running.
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Parsed key">
        <p>
          <HelpCode>parsed_key</HelpCode> must match the upstream{" "}
          <span className="font-medium text-foreground">Parse Cisco Config</span>{" "}
          step&apos;s own <HelpCode>output_key</HelpCode> — that is where its parsed
          model was written on each device.
        </p>
        <HelpWarning title="Add Parse Cisco Config upstream first">
          <p>
            If no device has parsed data at{" "}
            <HelpCode>parsed.{"{parsed_key}"}</HelpCode>, the step fails with a
            clear error naming the missing key — add a Parse Cisco Config step
            before this one and make sure <HelpCode>parsed_key</HelpCode> matches
            its <HelpCode>output_key</HelpCode>.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Attributes">
        <p>
          Check <HelpCode>Layer3 Interfaces</HelpCode> to build the interfaces
          list. Per interface:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">type</span> —{" "}
            <HelpCode>1000base-t</HelpCode> for names starting with{" "}
            <HelpCode>Gigabit</HelpCode>, <HelpCode>100base-tx</HelpCode> for names
            starting with <HelpCode>Ethernet</HelpCode>, else{" "}
            <HelpCode>virtual</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">status</span> — always{" "}
            <HelpCode>Active</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">enabled</span> —{" "}
            <HelpCode>true</HelpCode> unless the interface has a{" "}
            <HelpCode>shutdown</HelpCode> line in its config.
          </li>
          <li>
            <span className="font-medium text-foreground">ip_addresses</span> —
            the primary IP first, then a secondary IP only when the parsed
            interface has all three of <HelpCode>sec_ip_address</HelpCode>,{" "}
            <HelpCode>sec_mask</HelpCode>, and <HelpCode>sec_subnet</HelpCode> set.
          </li>
        </ul>
        <HelpExample>
          attributes: [layer3_interfaces]
        </HelpExample>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            nautobot attribute bag was updated on every device that had usable
            parsed data; devices without data are left unchanged.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Add Get Configs → Parse Cisco Config upstream.</li>
          <li>
            Add this step after it; set <HelpCode>parsed_key</HelpCode> and{" "}
            <HelpCode>config_source</HelpCode> to match, and check{" "}
            <HelpCode>Layer3 Interfaces</HelpCode>.
          </li>
          <li>
            Add Add to Nautobot after it with{" "}
            <HelpCode>interfaces_source: nautobot_origin</HelpCode>.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
