"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Get OSPF Facts (batfish-ospf-facts).
 * Covers every Configuration control with practical examples.
 */
export function BatfishOspfFactsHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Combines up to four Batfish OSPF questions —{" "}
          <HelpCode>ospfProcessConfiguration</HelpCode>,{" "}
          <HelpCode>ospfAreaConfiguration</HelpCode>,{" "}
          <HelpCode>ospfInterfaceConfiguration</HelpCode>, and{" "}
          <HelpCode>ospfEdges</HelpCode> — of the Batfish snapshot an upstream{" "}
          <span className="font-medium text-foreground">Init Batfish Snapshot</span> step
          created, into one merged OSPF picture per device. Unlike{" "}
          <span className="font-medium text-foreground">Batfish Node/Interface Properties</span>{" "}
          (one Batfish question each), this step makes up to four calls and merges their
          results per node.
        </p>
        <HelpWarning title="Snapshot source: upstream Init step, or a network set directly">
          <p>
            By default this step reads the snapshot location from an upstream{" "}
            <HelpCode>Init Batfish Snapshot</HelpCode> step&apos;s run metadata. See
            &quot;Querying a network directly&quot; below to target any network instead, with no
            Init step required in this workflow.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Questions">
        <p>
          Each question is independently toggleable — at least one must stay enabled. Disabling a
          question omits it entirely from both the result artifacts and the merged device
          payload (it never appears as a null/empty value).
        </p>
        <p>
          <HelpCode>nodes</HelpCode> (optional) restricts every enabled question to matching node
          names — the same filter Batfish Node/Interface Properties use.
        </p>
      </HelpSection>

      <HelpSection title="Devices outcome — the merged payload">
        <p>
          Alongside <HelpCode>success</HelpCode> (a plain passthrough of whatever devices came
          in, unchanged, plus this step&apos;s result metadata), this step emits{" "}
          <HelpCode>devices</HelpCode> — one device per distinct node seen in{" "}
          <span className="font-medium text-foreground">any</span> enabled question&apos;s
          results (a Batfish-sourced identity, not the original inventory device). Each device is
          enriched at <HelpCode>parsed.{"{node_id}.{output_key}"}.parsed</HelpCode> with:
        </p>
        <HelpExample>
          Process: [...] {"//"} list — a node in more than one VRF gets more than one entry
          <br />
          Areas: [...] {"//"} list — an ABR in more than one area gets more than one entry
          <br />
          Interfaces: {"{"}
          &quot;GigabitEthernet0/1&quot;: {"{"}...{"}"}, ...{"}"} {"//"} dict keyed by interface
          name
          <br />
          Adjacencies: [...] {"//"} list — each entry carries its own local and remote interface
        </HelpExample>
        <p>
          Only keys for enabled questions appear. <HelpCode>Process</HelpCode> and{" "}
          <HelpCode>Areas</HelpCode> are always lists, even with a single matching row — a node
          running OSPF in more than one VRF, or an ABR spanning more than one area, would
          otherwise silently lose data.
        </p>
        <HelpWarning title="Enable case-insensitive lookup on Get Nautobot Attributes">
          <p>
            Batfish always lowercases parsed node hostnames. A Nautobot device named with any
            uppercase letters (e.g. <HelpCode>R1</HelpCode>) won&apos;t match by name purely due
            to casing unless{" "}
            <span className="font-medium text-foreground">Get Nautobot Attributes</span>&apos;s{" "}
            <HelpCode>case_insensitive_lookup</HelpCode> option is turned on.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Output key and result storage">
        <p>
          <HelpCode>output_key</HelpCode> names the shared prefix for this step&apos;s results.
          Each enabled question gets its own workflow-level JSON artifact — a row count plus the
          raw Batfish rows — stored at{" "}
          <HelpCode>{"{node_id}.{output_key}.<process|areas|interfaces|edges>"}</HelpCode> in
          this run&apos;s metadata, viewable individually in the run detail view. The{" "}
          <HelpCode>devices</HelpCode> outcome above merges all enabled questions&apos; rows
          together per device — it is not a separate artifact.
        </p>
      </HelpSection>

      <HelpSection title="Querying a network directly">
        <p>
          Leave <HelpCode>batfish_source_id</HelpCode>/<HelpCode>network</HelpCode> blank to use
          the snapshot from an upstream Init Batfish Snapshot step in this run (default). Set
          both to query any network directly — e.g. a production network refreshed nightly by a
          Schedule — with no Init step needed in this workflow. This always overrides the
          run&apos;s own snapshot when set.
        </p>
        <p>
          Leave <HelpCode>snapshot</HelpCode> blank to use the most recently created snapshot in
          that network.
        </p>
      </HelpSection>
    </div>
  );
}
