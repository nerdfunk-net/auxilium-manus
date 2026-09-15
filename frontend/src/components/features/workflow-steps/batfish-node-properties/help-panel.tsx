"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Batfish Node Properties.
 * Covers every Configuration control with practical examples.
 */
export function BatfishNodePropertiesHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Queries per-node configuration properties of the Batfish snapshot an
          upstream <span className="font-medium text-foreground">Init Batfish Snapshot</span> step
          created — one row per node, with a column per requested property
          (e.g. <HelpCode>TACACS_Servers</HelpCode>). Both filters below are
          optional; an empty config returns Batfish&apos;s own default column
          set for every node.
        </p>
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
          hostname). <HelpCode>properties</HelpCode> restricts which columns
          come back, on top of <HelpCode>Node</HelpCode> — a
          comma-separated NodePropertySpec.
        </p>
        <HelpExample>
          nodes: R1
          <br />
          properties: TACACS_Servers
          <br />
          <span className="text-muted-foreground">
            → one row for R1 with its TACACS_Servers value — check the result
            artifact (or chain into Compare Data / a Jinja condition) to see
            whether a specific TACACS key is actually configured
          </span>
        </HelpExample>
        <p>
          Click a suggested property below the field to add it to{" "}
          <HelpCode>properties</HelpCode>. These are the same property names
          <span className="font-medium text-foreground"> Validate Facts</span>{" "}
          and <span className="font-medium text-foreground">Extract Facts</span>{" "}
          recognize.
        </p>
      </HelpSection>

      <HelpSection title="Checking a specific value">
        <p>
          This step returns the <span className="font-medium text-foreground">actual</span>{" "}
          values Batfish parsed — it does not compare against an expected
          value itself. To assert an exact expected value per device (e.g.
          &quot;every device must have TACACS server 10.0.0.5&quot;), use{" "}
          <span className="font-medium text-foreground">Validate Facts</span> with{" "}
          <HelpCode>facts_source: field</HelpCode> instead — it routes each
          device to a <HelpCode>match</HelpCode>/<HelpCode>mismatch</HelpCode> outcome directly.
          Use this step instead when you want to inspect or export the actual
          values themselves — e.g. auditing which TACACS servers are
          configured fleet-wide, not just checking one expected value.
        </p>
      </HelpSection>

      <HelpSection title="Route empty set to Devices">
        <p>
          Batfish always returns one row per matched node, even when a
          property is unset — an unconfigured TACACS server comes back as{" "}
          <HelpCode>TACACS_Servers: []</HelpCode>, not a missing row. Left
          disabled (default), the <HelpCode>devices</HelpCode> outcome
          carries every matched node regardless of value, same as today.
        </p>
        <p>
          Enable <HelpCode>Route empty set to Devices</HelpCode> to filter{" "}
          <HelpCode>devices</HelpCode> down to only the nodes whose requested{" "}
          <HelpCode>properties</HelpCode> are empty — turning a lookup into an
          audit. A value counts as empty if it&apos;s unset, a blank string,
          or an empty list. This requires <HelpCode>properties</HelpCode> to
          be set explicitly — with no filter, Batfish returns dozens of
          unrelated default columns and &quot;empty&quot; has no single
          well-defined meaning across all of them.
        </p>
        <HelpExample>
          nodes: (blank)
          <br />
          properties: TACACS_Servers
          <br />
          Route empty set to Devices: enabled
          <br />
          <span className="text-muted-foreground">
            → devices only contains nodes with no TACACS server configured
          </span>
        </HelpExample>
        <p>
          With more than one <HelpCode>properties</HelpCode> entry, a device
          can have some empty and some not — <HelpCode>empty_match_mode</HelpCode>{" "}
          decides how they combine: <HelpCode>any</HelpCode> (default) routes
          a device if at least one requested property is empty (the stricter
          read — every requested property must be present to be excluded);{" "}
          <HelpCode>all</HelpCode> routes it only if every requested property
          is empty.
        </p>
      </HelpSection>

      <HelpSection title="Output key">
        <p>
          <HelpCode>output_key</HelpCode> names the slot both outcomes use.
          On <HelpCode>success</HelpCode>, it&apos;s workflow-level: a JSON
          artifact reference plus a row count, stored in this run&apos;s
          metadata (covering every queried node in one shared entry). On{" "}
          <HelpCode>devices</HelpCode>, it&apos;s per-device instead — see
          below.
        </p>
      </HelpSection>

      <HelpSection title="Devices outcome">
        <p>
          Alongside <HelpCode>success</HelpCode> (a plain passthrough of
          whatever devices came in, unchanged), this step always emits a
          second outcome, <HelpCode>devices</HelpCode>, carrying one device
          per distinct <HelpCode>Node</HelpCode> value in the answer
          (deduplicated) — a Batfish-sourced identity, not the original
          inventory device.
        </p>
        <p>
          Each device in <HelpCode>devices</HelpCode> is enriched with{" "}
          <span className="font-medium text-foreground">only its own
          row</span> at <HelpCode>parsed.{"{node_id}.{output_key}"}.parsed</HelpCode>{" "}
          — e.g. a downstream{" "}
          <span className="font-medium text-foreground">Log Attributes</span>{" "}
          step or a device-detail view shows each device&apos;s own property
          values, not the combined answer for every queried node. Wire{" "}
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
