"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Batfish Routing Table.
 * Covers every Configuration control with practical examples.
 */
export function BatfishRoutingTableHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Queries the routing table of the Batfish snapshot an upstream{" "}
          <span className="font-medium text-foreground">Init Batfish Snapshot</span> step
          created — one row per node/VRF/network route. Every filter below is
          optional; an empty config returns every route on every node.
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
          hostname). <HelpCode>network_prefix</HelpCode> restricts to routes
          matching a prefix, interpreted per{" "}
          <HelpCode>prefix_match_type</HelpCode>.
        </p>
        <HelpExample>
          network_prefix: 192.168.1.0/24
          <br />
          prefix_match_type: LONGEST_PREFIX_MATCH
          <br />
          <span className="text-muted-foreground">
            → the most specific matching route(s) for that prefix
          </span>
        </HelpExample>
        <p>
          <HelpCode>protocols</HelpCode> and <HelpCode>vrfs</HelpCode> further
          narrow by routing protocol (e.g. static, bgp) or VRF name/regex.{" "}
          <HelpCode>rib</HelpCode> selects which protocol RIB to read from —{" "}
          <HelpCode>main</HelpCode> (default), <HelpCode>bgp</HelpCode>, or{" "}
          <HelpCode>evpn</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Output key">
        <p>
          <HelpCode>output_key</HelpCode> names the slot in this run&apos;s
          metadata where the result is stored — a JSON artifact reference
          plus a row count. Unlike per-device steps, this is workflow-level
          data, not <HelpCode>parsed.{"{output_key}"}</HelpCode> on each
          device.
        </p>
      </HelpSection>

      <HelpSection title="Devices outcome">
        <p>
          Alongside <HelpCode>success</HelpCode>, this step always emits a
          second outcome, <HelpCode>devices</HelpCode>, carrying one device
          per distinct <HelpCode>Node</HelpCode> value in the routes answer
          (deduplicated) — a Batfish-sourced identity, not the original
          inventory device. Wire it to a{" "}
          <span className="font-medium text-foreground">
            Get Nautobot Attributes
          </span>{" "}
          step to resolve each node against Nautobot: matched devices come
          back enriched with real attributes on its{" "}
          <HelpCode>success</HelpCode> outcome, and any node Nautobot doesn&apos;t
          recognize is dropped there instead — it lands on{" "}
          <span className="font-medium text-foreground">
            Get Nautobot Attributes
          </span>
          &apos;s <HelpCode>failure</HelpCode> outcome rather than continuing
          downstream.
        </p>
        <HelpWarning title="Name matching is case-sensitive">
          <p>
            Batfish always lowercases parsed node hostnames. A Nautobot
            device named with any uppercase letters (e.g. <HelpCode>R1</HelpCode>)
            won&apos;t resolve by name purely due to casing, even though it
            exists — it will show up as unmatched on{" "}
            <span className="font-medium text-foreground">
              Get Nautobot Attributes
            </span>
            &apos;s <HelpCode>failure</HelpCode> outcome.
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
