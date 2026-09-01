"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Compare Snapshot.
 * Covers every Configuration control with practical examples.
 */
export function ComparePyatsSnapshotHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Compares one or more Genie features (e.g. <HelpCode>bgp</HelpCode>,{" "}
          <HelpCode>ospf</HelpCode>) between a live pyATS snapshot captured earlier in
          this run and a stored reference snapshot, using Genie&rsquo;s own{" "}
          <HelpCode>genie.utils.diff.Diff</HelpCode> — a structure-aware diff of the
          parsed data, unlike a plain text diff. Each device routes to a{" "}
          <HelpCode>match</HelpCode> (every selected feature identical),{" "}
          <HelpCode>mismatch</HelpCode> (any feature differs), or{" "}
          <HelpCode>failure</HelpCode> outcome handle.
        </p>
        <p>
          On mismatch, Genie&rsquo;s diff text is stored per device at{" "}
          <HelpCode>{"{nodeId}.comparison_diff"}</HelpCode> as a{" "}
          <HelpCode>{"{ feature: entry }"}</HelpCode> map (only the differing features)
          for downstream steps (logging, notifications, remediation).
        </p>
      </HelpSection>

      <HelpWarning title="The reference is not a prior-run lookup">
        <p>
          There is no cross-run artifact query in this system. The reference snapshot
          must be a JSON file previously written by a <HelpCode>Store Artifact</HelpCode>{" "}
          step exporting an earlier <HelpCode>Get Snapshot</HelpCode> run&rsquo;s{" "}
          <HelpCode>pyats_snapshot</HelpCode> content to git or the filesystem —
          typically from a prior run, or a deliberate &ldquo;golden config&rdquo; capture.
          <HelpCode>filename_template</HelpCode> must point at that exact file.
        </p>
      </HelpWarning>

      <HelpSection title="Features">
        <p>
          <HelpCode>features</HelpCode> is the set of Genie feature names to compare,
          picked from the same grouped checkbox list as Get Snapshot (e.g.{" "}
          <HelpCode>bgp</HelpCode>, <HelpCode>ospf</HelpCode>,{" "}
          <HelpCode>interface</HelpCode>) — there is no <HelpCode>all</HelpCode> option
          here. Every selected feature is read from the same per-device live and
          reference snapshot file (no <HelpCode>{"{feature}"}</HelpCode> filename
          placeholder). A device routes to <HelpCode>match</HelpCode> only when every
          selected feature is identical.
        </p>
        <HelpExample>
          features: bgp, ospf
          <br />
          filename_template: {"{device.name}"}.pyats-snapshot.json
        </HelpExample>
      </HelpSection>

      <HelpSection title="Source step">
        <p>
          <HelpCode>source_step_node_id</HelpCode> is the upstream{" "}
          <HelpCode>Get Snapshot</HelpCode> step that produced the live snapshot. Pick
          from the dropdown or type directly (e.g.{" "}
          <HelpCode>get-pyats-snapshot-1</HelpCode>).
        </p>
        <HelpExample>
          features: bgp, ospf
          <br />
          source_step_node_id: get-pyats-snapshot-1
        </HelpExample>
      </HelpSection>

      <HelpSection title="Parsed output key">
        <p>
          Optional. Set <HelpCode>parsed_output_key</HelpCode> to the{" "}
          <HelpCode>output_key</HelpCode> from the upstream Get Snapshot step only when
          it produced snapshots under multiple keys and the default (first match) isn&rsquo;t
          the right one.
        </p>
      </HelpSection>

      <HelpSection title="Exclude keys">
        <p>
          <HelpCode>exclude_keys</HelpCode> is an optional comma-separated list of dict
          keys to ignore during the diff, passed straight through to Genie&rsquo;s{" "}
          <HelpCode>Diff(a, b, exclude=[...])</HelpCode>.
        </p>
        <HelpWarning title="Genie does not ignore volatile fields by default">
          <p>
            <HelpCode>genie.utils.diff.Diff</HelpCode> compares every key literally
            unless you list it in <HelpCode>exclude</HelpCode>. Fields that change on
            their own between captures — e.g. <HelpCode>updated</HelpCode>,{" "}
            <HelpCode>uptime</HelpCode>, <HelpCode>last_change</HelpCode>, packet/byte
            counters — will otherwise report as a mismatch even when nothing
            operationally meaningful changed. Add them here to silence that noise.
          </p>
        </HelpWarning>
        <HelpExample>
          exclude_keys: updated, last_change, uptime
        </HelpExample>
      </HelpSection>

      <HelpSection title="Reference location">
        <p>
          <HelpCode>reference_location</HelpCode> chooses where the reference snapshot
          JSON lives:
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">Filesystem</span> —{" "}
            <HelpCode>reference_location: filesystem</HelpCode>. Files under{" "}
            <HelpCode>DATA_DIRECTORY/&lt;reference_subdirectory&gt;/</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">Git repository</span> —{" "}
            <HelpCode>reference_location: git</HelpCode>. Files from a git source in
            Settings → Git Repositories.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Filesystem reference">
        <p>
          <HelpCode>reference_subdirectory</HelpCode> is the folder under the server
          data directory (default <HelpCode>pyats-snapshots</HelpCode>). Combined with{" "}
          <HelpCode>filename_template</HelpCode> to resolve the full path per device.
        </p>
        <HelpExample>
          reference_location: filesystem
          <br />
          reference_subdirectory: pyats-snapshots
          <br />
          filename_template: {"{device.name}"}.pyats-snapshot.json
          <br />
          <span className="text-muted-foreground">
            → reads DATA_DIRECTORY/pyats-snapshots/router1.pyats-snapshot.json
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Git reference">
        <p>When reference location is git, configure:</p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>git_repository_id</HelpCode> — repository from Settings → Git Repositories
            (click Choose repository).
          </li>
          <li>
            <HelpCode>repository_subdirectory</HelpCode> — path inside the repo (e.g.{" "}
            <HelpCode>network/snapshots</HelpCode>).
          </li>
          <li>
            <HelpCode>pull_before_read</HelpCode> — when on, pulls latest changes once
            before reading the reference file.
          </li>
        </ul>
        <HelpExample>
          reference_location: git
          <br />
          git_repository_id: 3
          <br />
          repository_subdirectory: network/snapshots
          <br />
          pull_before_read: true
          <br />
          filename_template: {"{device.name}"}.pyats-snapshot.json
        </HelpExample>
      </HelpSection>

      <HelpSection title="Filename template">
        <p>
          <HelpCode>filename_template</HelpCode> builds the reference file path per
          device. Same placeholders as other reference-backed steps —{" "}
          <HelpCode>{"{device.name}"}</HelpCode>, <HelpCode>{"{device.hostname}"}</HelpCode>
          , <HelpCode>{"{nautobot.location.name}"}</HelpCode>,{" "}
          <HelpCode>{"{run.timestamp}"}</HelpCode>, etc. — but{" "}
          <span className="font-medium text-foreground">no {"{feature}"} placeholder</span>
          : one reference file per device holds every feature being compared, so the
          same file is read for all selected features.
        </p>
        <HelpExample>
          filename_template: {"{nautobot.location.name}"}/{"{device.name}"}.pyats-snapshot.json
        </HelpExample>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">match</span> — every selected
            feature is identical between the live and reference snapshots per
            Genie&rsquo;s diff.
          </li>
          <li>
            <span className="font-medium text-foreground">mismatch</span> — Genie found
            differences in at least one feature. Per-feature diff text is written to{" "}
            <HelpCode>{"{nodeId}.comparison_diff"}</HelpCode> as a{" "}
            <HelpCode>{"{ feature: entry }"}</HelpCode> map (differing features only);{" "}
            <HelpCode>{"{nodeId}.comparison"}</HelpCode> lists{" "}
            <HelpCode>mismatched_features</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — missing
            testbed/source, no live snapshot from the upstream step, any selected
            feature is absent or failed on either side, the reference file is missing or
            not valid snapshot JSON, or the pyATS shim call itself failed.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Add Testbed → Get Snapshot upstream, capturing the features to compare.</li>
          <li>
            Check the <HelpCode>features</HelpCode> to compare and set{" "}
            <HelpCode>source_step_node_id</HelpCode> to point at that Get Snapshot step.
          </li>
          <li>
            Place a previously exported <HelpCode>pyats_snapshot</HelpCode> JSON file
            under filesystem <HelpCode>pyats-snapshots/</HelpCode> or in a git repo; set{" "}
            <HelpCode>filename_template</HelpCode> to match.
          </li>
          <li>
            Wire match / mismatch / failure handles to remediation, logging, or
            notification steps.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
