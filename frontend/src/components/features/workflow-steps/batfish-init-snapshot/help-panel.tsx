"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Init Batfish Snapshot.
 * Covers every Configuration control with practical examples.
 */
export function BatfishInitSnapshotHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Assembles this run&apos;s device running-configs into a fresh{" "}
          <HelpCode>Batfish</HelpCode> snapshot and records its location (and
          the connection to use) in this run&apos;s metadata. Downstream
          Batfish steps — Routing Table, Path Check, ACL Check — find that
          snapshot automatically; they have no source configuration of
          their own.
        </p>
        <p>
          One Batfish network is used per Manus workflow, and one snapshot
          per run, so history for a given workflow is browsable in Batfish
          over time.
        </p>
        <HelpWarning title="Not fan-out-safe">
          <p>
            This step needs every device&apos;s config together in one
            upload, so it must run <strong>after a Fan In</strong> in a
            fanned-out workflow — never inside the fanned-out branch. Same
            reasoning as <HelpCode>store-artifact</HelpCode> / git steps:
            concurrent children would race on the same shared upload.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Batfish source">
        <p>
          Select which configured Batfish source (Settings → Sources →
          Batfish) this step should use. Only the source ID is stored on the
          step; the host and port are resolved from settings at runtime.
        </p>
      </HelpSection>

      <HelpSection title="Retain snapshots">
        <p>
          After a successful run, snapshots for this workflow&apos;s Batfish
          network beyond the <HelpCode>retain_snapshots</HelpCode> most
          recent are deleted — sorted by when Batfish actually created each
          one, not by name (snapshot names aren&apos;t chronologically
          sortable).
        </p>
        <HelpExample>
          retain_snapshots: 5
          <br />
          <span className="text-muted-foreground">
            → keeps the 5 most recently created snapshots for this workflow
          </span>
        </HelpExample>
      </HelpSection>
    </div>
  );
}
