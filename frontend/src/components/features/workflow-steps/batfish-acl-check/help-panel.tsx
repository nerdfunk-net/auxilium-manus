"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Batfish ACL Check.
 * Covers every Configuration control with practical examples.
 */
export function BatfishAclCheckHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Tests one concrete flow — the fields below — against a named
          filter/ACL on the snapshot via Batfish&apos;s{" "}
          <HelpCode>testFilters</HelpCode> question, and reads the filter&apos;s
          matched action.
        </p>
        <HelpWarning title="dst_ips is required">
          <p>
            Batfish itself treats header fields as required for this
            question — <HelpCode>node</HelpCode>, <HelpCode>filter_name</HelpCode>,
            and <HelpCode>dst_ips</HelpCode> must all be set.
          </p>
        </HelpWarning>
        <p>
          Outcomes are <HelpCode>permit</HelpCode> / <HelpCode>deny</HelpCode>{" "}
          read from the matched line&apos;s action — one concrete flow in, one
          concrete verdict out, not a search across a whole space of traffic.
          Like Path Check, the full device set from upstream passes through
          unchanged regardless of which outcome fires.
        </p>
      </HelpSection>

      <HelpSection title="Example">
        <HelpExample>
          node: R1
          <br />
          filter_name: TEST-ACL
          <br />
          dst_ips: 192.168.1.1
          <br />
          applications: SSH
          <br />
          <span className="text-muted-foreground">
            → does TEST-ACL on R1 permit SSH to 192.168.1.1?
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Optional fields">
        <p>
          <HelpCode>src_ips</HelpCode> / <HelpCode>ip_protocols</HelpCode>{" "}
          further narrow the tested flow. <HelpCode>start_location</HelpCode>{" "}
          pins where the flow originates when that matters for the filter
          being tested.
        </p>
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
