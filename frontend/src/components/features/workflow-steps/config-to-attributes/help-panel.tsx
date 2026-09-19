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
          Reads a device&apos;s parsed config and populates its Nautobot attribute
          bag — purely in-memory, no Nautobot connection is made here. A later{" "}
          <span className="font-medium text-foreground">Add to Nautobot</span> or{" "}
          <span className="font-medium text-foreground">Update Device</span> step
          (with <HelpCode>interfaces_source: nautobot_origin</HelpCode>) can then
          create or update those interfaces for real.
        </p>
        <p>
          Currently supports one attribute group:{" "}
          <span className="font-medium text-foreground">Layer3 Interfaces</span> —
          name, status, type, description, IP addresses (including secondaries,
          with an explicit Nautobot IP role), and enabled state. More groups will
          be added later.
        </p>
      </HelpSection>

      <HelpSection title="Source format">
        <p>
          Which parser produced the config at <HelpCode>parsed.{"{parsed_key}"}</HelpCode>:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">Cisco Config Parser</span> —
            output from an upstream <span className="font-medium text-foreground">
            Parse Cisco Config</span> step (a flat, typed interface list).
          </li>
          <li>
            <span className="font-medium text-foreground">Genie (pyATS)</span> —
            output from an upstream <span className="font-medium text-foreground">
            Get &amp; Parse Config</span> step (Genie&apos;s raw parsed{" "}
            <HelpCode>show running-config</HelpCode> tree, keyed by literal config
            lines). Only <HelpCode>config_source: running</HelpCode> is supported
            for this format — Get &amp; Parse Config never captures startup-config.
          </li>
        </ul>
        <p className="text-muted-foreground">
          A Batfish source format is planned as a future addition to this same
          contract.
        </p>
      </HelpSection>

      <HelpSection title="Config source">
        <p>
          Choose which parsed config to read attribute values from —{" "}
          <HelpCode>running</HelpCode> or <HelpCode>startup</HelpCode> (exactly
          one). Genie only ever populates <HelpCode>running</HelpCode>.
        </p>
        <HelpExample>
          config_source: running
          <br />
          <span className="text-muted-foreground">
            → reads parsed.{"{parsed_key}"}.running (both Parse Cisco Config and
            Get &amp; Parse Config nest their output under running / startup).
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Parsed key">
        <p>
          <HelpCode>parsed_key</HelpCode> must match the matching upstream step&apos;s
          own <HelpCode>output_key</HelpCode> — Parse Cisco Config for
          cisco_config_parser, Get &amp; Parse Config for genie — that is where its
          parsed model was written on each device.
        </p>
        <p>
          Click the search icon next to the field to browse real attribute paths
          from the workflow&apos;s most recent run (requires a saved, previously run
          workflow) and pick the upstream step&apos;s key directly instead of typing
          it — selecting any node under <HelpCode>parsed.*</HelpCode> fills in just
          that key segment.
        </p>
        <HelpWarning title="Add the matching upstream step first">
          <p>
            If no device has parsed data at{" "}
            <HelpCode>parsed.{"{parsed_key}"}</HelpCode>, the step fails with a
            clear error naming the missing key and the expected upstream step — add
            it before this one and make sure <HelpCode>parsed_key</HelpCode> matches
            its <HelpCode>output_key</HelpCode>.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Attributes">
        <p>
          Check <HelpCode>Layer3 Interfaces</HelpCode> to build the interfaces
          list. Per interface, regardless of source format:
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
            every IP the interface has. The primary address is marked{" "}
            <HelpCode>is_primary</HelpCode>; an IOS{" "}
            <HelpCode>ip address ... secondary</HelpCode> line (or, for Cisco
            Config Parser, a parsed secondary IP) is marked with Nautobot IP role{" "}
            <HelpCode>secondary</HelpCode> instead.
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
          <li>
            Upstream, add either Get Configs → Parse Cisco Config, or Add Testbed
            → Get &amp; Parse Config (pyATS/Genie).
          </li>
          <li>
            Add this step after it; set <HelpCode>source_format</HelpCode> to
            match, set <HelpCode>parsed_key</HelpCode> and{" "}
            <HelpCode>config_source</HelpCode> to match the upstream step&apos;s{" "}
            <HelpCode>output_key</HelpCode>, and check{" "}
            <HelpCode>Layer3 Interfaces</HelpCode>.
          </li>
          <li>
            Add Add to Nautobot or Update Device after it with{" "}
            <HelpCode>interfaces_source: nautobot_origin</HelpCode>.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
