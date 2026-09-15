"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Get from Batfish (batfish-start-run).
 * Covers the three auto-detected behaviors and the config that drives them.
 */
export function BatfishStartRunHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Three auto-detected behaviors, chosen by what&apos;s resolvable at run time — there is
          no mode/toggle field to set:
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">Nothing configured, no run metadata</span>{" "}
            — clears devices to an empty placeholder and makes{" "}
            <span className="font-medium text-foreground">zero Batfish calls</span>. This is the
            step&apos;s original role: letting a <HelpCode>git</HelpCode>-mode{" "}
            <span className="font-medium text-foreground">Init Batfish Snapshot</span> step (which
            needs no live devices) satisfy the canvas&apos;s connection rule.
          </li>
          <li>
            <span className="font-medium text-foreground">
              This run&apos;s own Init Batfish Snapshot already ran
            </span>{" "}
            — resolves that snapshot, queries every matching node, and{" "}
            <span className="font-medium text-foreground">replaces</span> the device list with one
            device per node.
          </li>
          <li>
            <span className="font-medium text-foreground">batfish_source_id + network set</span> —
            same device population, but against a standing network directly, no Init step needed
            in this run at all.
          </li>
        </ul>
        <HelpWarning title="This behavior depends on run state and config, not an explicit toggle">
          <p>
            If devices come back unexpectedly empty or populated, check: is there an upstream Init
            Batfish Snapshot step in this same run, and are{" "}
            <HelpCode>batfish_source_id</HelpCode>/<HelpCode>network</HelpCode> below set? A
            genuine misconfiguration (a malformed snapshot record, or a{" "}
            <HelpCode>network</HelpCode> that doesn&apos;t exist) fails the step loudly — it is
            never silently treated as &quot;no devices&quot;.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Two instances in one workflow">
        <p>
          A workflow can legitimately use this step twice: once before{" "}
          <span className="font-medium text-foreground">Init Batfish Snapshot</span> (placeholder
          role, satisfies the connection rule) and once after it (real device population from the
          snapshot that step just built). This is what makes Validate Facts&apos;s{" "}
          <HelpCode>facts_source: git</HelpCode> usable with no live device-selection step
          anywhere in the workflow.
        </p>
        <HelpExample>
          Get from Batfish → Init Batfish Snapshot (config_source: git) → Get from Batfish →
          Validate Facts
        </HelpExample>
      </HelpSection>

      <HelpSection title="nodes_filter">
        <p>
          NodeSpecifier restricting which nodes are listed as devices (e.g.{" "}
          <HelpCode>/^r/</HelpCode> or <HelpCode>node1|node2</HelpCode>). Leave blank to list
          every node in the snapshot. Only relevant when this step actually queries Batfish
          (cases 2/3 above) — ignored in the placeholder case, since no query is made.
        </p>
      </HelpSection>

      <HelpSection title="Device identity">
        <p>
          Synthesized devices carry a Batfish-sourced identity, not the original inventory device
          — the same shape <span className="font-medium text-foreground">Batfish Routing Table</span>
          &apos;s own <HelpCode>devices</HelpCode> outcome uses. Wire this step&apos;s output into
          a <span className="font-medium text-foreground">Get Nautobot Attributes</span> step to
          resolve each node against Nautobot and get real attributes.
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

      <HelpSection title="Querying a network directly">
        <p>
          Leave <HelpCode>batfish_source_id</HelpCode>/<HelpCode>network</HelpCode> blank to use
          the snapshot from an upstream Init Batfish Snapshot step in this run. Set both to query
          any network directly — e.g. a production network refreshed nightly by a Schedule — with
          no Init step needed in this workflow. This always overrides the run&apos;s own snapshot
          when set.
        </p>
        <p>
          Leave <HelpCode>snapshot</HelpCode> blank to use the most recently created snapshot in
          that network.
        </p>
      </HelpSection>
    </div>
  );
}
