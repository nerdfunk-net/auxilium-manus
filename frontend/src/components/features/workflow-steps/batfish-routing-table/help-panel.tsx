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
        <HelpWarning title="Requires an upstream Init Batfish Snapshot step">
          <p>
            This step reads the snapshot location from this run&apos;s metadata — it
            has no source configuration of its own.
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
    </div>
  );
}
