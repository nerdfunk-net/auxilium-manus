"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Batfish Path Check.
 * Covers every Configuration control with practical examples.
 */
export function BatfishPathCheckHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Checks whether a path exists between <HelpCode>start_node</HelpCode>{" "}
          and (optionally) <HelpCode>end_node</HelpCode> via Batfish&apos;s
          reachability question, optionally narrowed by header fields
          (destination/source IP, applications, IP protocols).
        </p>
        <HelpWarning title="Both outcomes are normal answers">
          <p>
            <HelpCode>reachable</HelpCode> /{" "}
            <HelpCode>not_reachable</HelpCode> are both valid results, not
            success/failure — no matching flow found simply means there is no
            path, which is a real answer, not an error.
          </p>
        </HelpWarning>
        <p>
          This step evaluates <strong>one flow definition from its own
          config</strong>, not one check per device — the full device set
          from upstream passes through unchanged regardless of which outcome
          fires.
        </p>
      </HelpSection>

      <HelpSection title="Path constraints">
        <HelpExample>
          start_node: R1
          <br />
          end_node: R2
          <br />
          <span className="text-muted-foreground">
            → is there a path from R1 to R2?
          </span>
        </HelpExample>
        <p>
          Leave <HelpCode>end_node</HelpCode> empty to search for a path to
          any destination matching the header fields instead of one specific
          node.
        </p>
      </HelpSection>

      <HelpSection title="Header fields and flags">
        <p>
          <HelpCode>dst_ips</HelpCode> / <HelpCode>src_ips</HelpCode> /{" "}
          <HelpCode>applications</HelpCode> / <HelpCode>ip_protocols</HelpCode>{" "}
          narrow which flows count as a match. <HelpCode>max_traces</HelpCode>{" "}
          caps how many example traces are returned.{" "}
          <HelpCode>invert_search</HelpCode> searches for packets{" "}
          <em>outside</em> the given header space instead of inside it.{" "}
          <HelpCode>ignore_filters</HelpCode> skips ACLs/filters during the
          analysis, checking pure routing reachability.
        </p>
      </HelpSection>
    </div>
  );
}
