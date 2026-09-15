"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Batfish Interface Properties.
 * Covers every Configuration control with practical examples.
 */
export function BatfishInterfacePropertiesHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Queries per-interface configuration properties of the Batfish
          snapshot an upstream{" "}
          <span className="font-medium text-foreground">Init Batfish Snapshot</span> step
          created — one row per (node, interface) pair, with a column per
          requested property (e.g. <HelpCode>Description</HelpCode>,{" "}
          <HelpCode>MTU</HelpCode>, <HelpCode>Primary_Address</HelpCode>).
          Every filter below is optional; an empty config returns
          Batfish&apos;s own default column set for every interface on every
          node.
        </p>
        <HelpWarning title="Not the same question as Batfish Node Properties">
          <p>
            <span className="font-medium text-foreground">Batfish Node Properties</span> returns
            one row per node (e.g. hostname, TACACS/NTP/DNS servers). This
            step returns one row per interface on a node (e.g. description,
            MTU, IP address, VRF membership, applied ACLs) — a different
            Batfish question with a different result shape. Use this step
            when the fact you need lives on an interface, not the device as
            a whole.
          </p>
        </HelpWarning>
        <HelpWarning title="Snapshot source: upstream Init step, or a network set directly">
          <p>
            By default this step reads the snapshot location from an upstream{" "}
            <HelpCode>Init Batfish Snapshot</HelpCode> step&apos;s run metadata. See
            &quot;Querying a network directly&quot; below to target any network
            instead, with no Init step required in this workflow.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Filters">
        <p>
          <HelpCode>nodes</HelpCode> restricts to matching node names (e.g. a
          hostname). <HelpCode>interfaces</HelpCode> further restricts to
          matching interface names (e.g. a name or regex) on those nodes.{" "}
          <HelpCode>properties</HelpCode> restricts which columns come back,
          on top of <HelpCode>Interface</HelpCode> — a comma-separated
          property list.
        </p>
        <HelpExample>
          nodes: R1
          <br />
          properties: Description
          <br />
          <span className="text-muted-foreground">
            → one row per interface on R1 with its Description value
          </span>
        </HelpExample>
        <p>
          Click a suggested property below the field to add it to{" "}
          <HelpCode>properties</HelpCode>. This is a curated starting-point
          list, not exhaustive — Batfish&apos;s real column set is fetched
          from the coordinator at runtime, so any real property name works
          whether or not it&apos;s listed.
        </p>
      </HelpSection>

      <HelpSection title="Route empty set to Devices">
        <p>
          Left disabled (default), the <HelpCode>devices</HelpCode> outcome
          carries every node with at least one matching interface, regardless
          of value.
        </p>
        <p>
          Enable <HelpCode>Route empty set to Devices</HelpCode> to filter{" "}
          <HelpCode>devices</HelpCode> down to only the nodes with at least
          one matching interface whose requested <HelpCode>properties</HelpCode>{" "}
          are empty — turning a lookup into an audit (e.g. &quot;which
          devices have an interface with no description set&quot;). A value
          counts as empty if it&apos;s unset, a blank string, or an empty
          list. This requires <HelpCode>properties</HelpCode> to be set
          explicitly.
        </p>
        <HelpExample>
          properties: Description
          <br />
          Route empty set to Devices: enabled
          <br />
          <span className="text-muted-foreground">
            → devices only contains nodes with at least one undescribed
            interface
          </span>
        </HelpExample>
        <p>
          With more than one <HelpCode>properties</HelpCode> entry,{" "}
          <HelpCode>empty_match_mode</HelpCode> decides how they combine per
          interface: <HelpCode>any</HelpCode> (default) flags an interface if
          at least one requested property is empty; <HelpCode>all</HelpCode>{" "}
          flags it only if every requested property is empty. A node is
          routed to <HelpCode>devices</HelpCode> if any of its interfaces is
          flagged.
        </p>
      </HelpSection>

      <HelpSection title="Output key">
        <p>
          <HelpCode>output_key</HelpCode> names the slot both outcomes use.
          On <HelpCode>success</HelpCode>, it&apos;s workflow-level: a JSON
          artifact reference plus a row count, stored in this run&apos;s
          metadata (covering every matched interface on every node in one
          shared entry). On <HelpCode>devices</HelpCode>, it&apos;s
          per-device instead — see below.
        </p>
      </HelpSection>

      <HelpSection title="Devices outcome">
        <p>
          Alongside <HelpCode>success</HelpCode> (a plain passthrough of
          whatever devices came in, unchanged), this step always emits a
          second outcome, <HelpCode>devices</HelpCode>, carrying one device
          per distinct node with a matching interface (deduplicated) — a
          Batfish-sourced identity, not the original inventory device.
        </p>
        <p>
          Each device in <HelpCode>devices</HelpCode> is enriched with{" "}
          <span className="font-medium text-foreground">only its own
          matching interfaces</span> at{" "}
          <HelpCode>parsed.{"{node_id}.{output_key}"}.parsed.Interfaces</HelpCode>{" "}
          — e.g. a downstream{" "}
          <span className="font-medium text-foreground">Log Attributes</span>{" "}
          step or a device-detail view shows each device&apos;s own
          interfaces, not the combined answer for every queried node. Wire{" "}
          <HelpCode>devices</HelpCode> to a{" "}
          <span className="font-medium text-foreground">
            Get Nautobot Attributes
          </span>{" "}
          step to also resolve each node against Nautobot.
        </p>
        <HelpWarning title="Enable case-insensitive lookup on Get Nautobot Attributes">
          <p>
            Batfish always lowercases parsed node hostnames. A Nautobot
            device named with any uppercase letters (e.g. <HelpCode>R1</HelpCode>)
            won&apos;t match by name purely due to casing unless{" "}
            <span className="font-medium text-foreground">
              Get Nautobot Attributes
            </span>
            &apos;s <HelpCode>case_insensitive_lookup</HelpCode> option is turned
            on.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Querying a network directly">
        <p>
          Leave <HelpCode>batfish_source_id</HelpCode>/<HelpCode>network</HelpCode> blank
          to use the snapshot from an upstream Init Batfish Snapshot step in this run
          (default). Set both to query any network directly — e.g. a production network
          refreshed nightly by a Schedule — with no Init step needed in this workflow.
          This always overrides the run&apos;s own snapshot when set.
        </p>
        <p>
          Leave <HelpCode>snapshot</HelpCode> blank to use the most recently created
          snapshot in that network.
        </p>
      </HelpSection>
    </div>
  );
}
