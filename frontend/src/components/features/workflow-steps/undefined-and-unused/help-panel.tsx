"use client";

import { HelpCode, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Undefined & Unused.
 * Covers every Configuration control with practical examples.
 */
export function UndefinedAndUnusedHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Runs Batfish&apos;s <HelpCode>undefinedReferences</HelpCode> and{" "}
          <HelpCode>unusedStructures</HelpCode> &ldquo;hygiene&rdquo; questions against an
          already-initialized snapshot. A device with a configuration reference to a
          structure that doesn&apos;t exist (e.g. a route-map naming an undefined ACL) routes to{" "}
          <HelpCode>undefined</HelpCode>. A device with a defined structure (ACL, route-map,
          prefix-list, ...) that is never referenced anywhere routes to{" "}
          <HelpCode>unused</HelpCode>.
        </p>
        <HelpWarning title="A device can land in both undefined and unused">
          <p>
            These two outcomes are not exclusive — a device with both kinds of findings is
            routed down both branches at once, each carrying the same device with its own
            finding detail attached.
          </p>
        </HelpWarning>
        <p>
          <HelpCode>success</HelpCode> only carries devices with zero findings and no error.{" "}
          <HelpCode>failure</HelpCode> carries devices whose config didn&apos;t parse cleanly, or
          that have no matching node in the snapshot at all — for those devices,
          undefined/unused results would be unreliable, so they are excluded from every other
          outcome.
        </p>
      </HelpSection>

      <HelpSection title="nodes">
        <p>
          A Batfish NodeSpecifier restricting which nodes to check. Left blank, this step
          auto-scopes to exactly this run&apos;s devices (by name, lowercased) — set it
          explicitly only to check a different node set than what&apos;s upstream on the
          canvas.
        </p>
      </HelpSection>

      <HelpSection title="Reading the result downstream">
        <p>
          A device in <HelpCode>undefined</HelpCode> gets{" "}
          <HelpCode>{"device.parsed[\"<output_key>.undefined\"] = {parsed, error}"}</HelpCode>{" "}
          — a list of rows (struct type, reference name, context, line numbers). A device in{" "}
          <HelpCode>unused</HelpCode> gets the same shape under{" "}
          <HelpCode>{"\"<output_key>.unused\""}</HelpCode>. A device in both outcomes carries
          both keys.
        </p>
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
