"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Get Snapshot.
 * Covers every Configuration control with practical examples.
 */
export function GetPyatsSnapshotHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Captures a Genie <HelpCode>learn()</HelpCode> snapshot of live device
          operational state via the pyATS shim — BGP, OSPF, interfaces, platform, and
          more, as opposed to configuration text (that&apos;s Get &amp; Parse Config
          instead).
        </p>
        <p>
          Feature support varies a lot by platform, so a device isn&apos;t failed just
          because one requested feature isn&apos;t supported or configured — only when{" "}
          <strong>every</strong> requested feature fails to learn. Successful and failed
          features are both recorded in the result, so partial coverage is visible
          rather than silently dropped.
        </p>
        <HelpWarning title="Requires an upstream Add Testbed step">
          <p>
            This step reads its device connection details and credential from the{" "}
            <HelpCode>pyats_testbed</HelpCode> bag written by an Add Testbed step earlier
            in the workflow — it has no credential or source configuration of its own.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Features">
        <p>
          Select one or more Genie feature names to learn, or check{" "}
          <HelpCode>all</HelpCode> to learn everything the platform supports in one call
          (checking <HelpCode>all</HelpCode> clears individual selections, and vice
          versa).
        </p>
        <HelpExample>
          features: [bgp, interface]
          <br />
          <span className="text-muted-foreground">
            → learns BGP and interface state only
          </span>
        </HelpExample>
        <HelpExample>
          features: [all]
          <br />
          <span className="text-muted-foreground">→ learns every supported feature</span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Output key">
        <p>
          <HelpCode>output_key</HelpCode> names the slot where the snapshot is stored on
          each device. Downstream steps and templates reference{" "}
          <HelpCode>device.parsed.{"{output_key}"}</HelpCode>.
        </p>
        <HelpExample>
          output_key: pyats_snapshot
          <br />
          <span className="text-muted-foreground">
            → device.parsed.pyats_snapshot.features.bgp.success
          </span>
        </HelpExample>
        <p>
          The full per-feature Genie data is stored as a durable artifact (referenced via{" "}
          <HelpCode>device.parsed.{"{output_key}"}.artifact_ref</HelpCode>) — view it from
          a workflow run detail page, or chain a Store Artifact step afterward to export
          it to a filesystem path or git repository.
        </p>
      </HelpSection>
    </div>
  );
}
