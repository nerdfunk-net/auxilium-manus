"use client";

import { HelpCode, HelpSection } from "../shared/step-help";
import { BATFISH_FACT_KEYS } from "../shared/batfish-fact-keys";

/**
 * Built-in Help tab content for Extract Facts.
 * Covers every Configuration control with practical examples.
 */
export function BatfishExtractFactsHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Retrieves the configuration facts Batfish actually parsed (hostname, NTP/TACACS/
          DNS servers, interfaces, BGP/OSPF settings, etc.) for a set of nodes in an
          already-initialized snapshot, via Batfish&apos;s <HelpCode>extract_facts</HelpCode>{" "}
          question — no expected values, just what Batfish sees. Unlike Validate Facts, there
          is only one outcome (<HelpCode>success</HelpCode>); nothing here is a pass/fail
          check.
        </p>
      </HelpSection>

      <HelpSection title="nodes_filter">
        <p>
          A Batfish NodeSpecifier restricting which nodes to extract facts for. Left blank,
          this step defaults to exactly this run&apos;s devices (by name, lowercased) rather
          than the whole network — set it to <HelpCode>/.*/ </HelpCode> explicitly to extract
          every node in the snapshot instead.
        </p>
      </HelpSection>

      <HelpSection title="Reading the result downstream">
        <p>
          Each device that Batfish returned facts for gets{" "}
          <HelpCode>{"device.parsed[\"<output_key>\"] = {parsed, error}"}</HelpCode> — the
          same shape run-command&apos;s parsers use. A downstream Render Jinja Template step
          can read e.g.{" "}
          <HelpCode>{"{{ parsed.batfish_extract_facts.parsed.TACACS.TACACS_Servers }}"}</HelpCode>
          . A device Batfish had no facts for (e.g. its name doesn&apos;t match a snapshot
          node) gets <HelpCode>parsed: null</HelpCode> and a non-fatal{" "}
          <HelpCode>error</HelpCode> message instead — this never fails the step.
        </p>
      </HelpSection>

      <HelpSection title="Available fact keys">
        <p className="leading-5">{BATFISH_FACT_KEYS.join(", ")}</p>
      </HelpSection>

      <HelpSection title="Querying a network directly">
        <p>
          Leave <HelpCode>batfish_source_id</HelpCode>/<HelpCode>network</HelpCode> blank to
          use the snapshot from an upstream Init Batfish Snapshot step in this run (default).
          Set both to query any network directly — e.g. a production network refreshed
          nightly by a Schedule — with no Init step needed in this workflow.
        </p>
        <p>
          Leave <HelpCode>snapshot</HelpCode> blank to use the most recently created snapshot
          in that network.
        </p>
      </HelpSection>
    </div>
  );
}
