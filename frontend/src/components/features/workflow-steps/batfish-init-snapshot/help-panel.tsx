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
        <HelpWarning title="Not concurrency-safe (live mode)">
          <p>
            In <HelpCode>live</HelpCode> mode this step needs every
            device&apos;s config together in one upload, so it must run{" "}
            <strong>after a Fan In</strong> in a fanned-out workflow — never
            inside the fanned-out branch. Same reasoning as{" "}
            <HelpCode>store-artifact</HelpCode> / git steps: concurrent
            children would race on the same shared upload — and so would two
            independent (non-fan-out) branches in the same run that both run
            this step. <HelpCode>git</HelpCode> mode reads nothing from this
            run&apos;s devices, so this restriction doesn&apos;t apply to it.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Config source: live vs. git">
        <p>
          <strong>Live</strong> (default) uses this run&apos;s device
          running-configs, pulled during the current workflow run — the
          right choice for ad-hoc/lab debugging against a handful of
          devices.
        </p>
        <p>
          <strong>Git</strong> reads already-collected configs from a Git
          repository instead — no live device contact at all, so it scales
          to a production fleet without SSHing every device in the same run.
          It ignores this run&apos;s device selection entirely, so wire an
          upstream <HelpCode>Start Batfish Run</HelpCode> step (which seeds
          an empty device context) instead of a real device-selection step
          when no devices are otherwise selected.
        </p>
        <HelpExample>
          base_path: configs/running
          <br />
          glob_pattern: **/*.cfg
          <br />
          <span className="text-muted-foreground">
            → every .cfg file under configs/running/ in the repository
          </span>
        </HelpExample>
        <HelpExample>
          base_path: (blank)
          <br />
          glob_pattern: **/*.running.cfg
          <br />
          <span className="text-muted-foreground">
            → every file anywhere in the repo ending in .running.cfg
            (filename-suffix convention)
          </span>
        </HelpExample>
        <p>
          Filenames are cosmetic to Batfish — it identifies each device from
          the config text&apos;s own hostname line, not the path or
          filename that matched.
        </p>
      </HelpSection>

      <HelpSection title="Batfish source">
        <p>
          Select which configured Batfish source (Settings → Sources →
          Batfish) this step should use. Only the source ID is stored on the
          step; the host and port are resolved from settings at runtime.
        </p>
      </HelpSection>

      <HelpSection title="Network name">
        <p>
          Optional. By default this step targets a Batfish network named{" "}
          <HelpCode>manus-workflow-&lt;workflow_id&gt;</HelpCode>. Set{" "}
          <HelpCode>network_name</HelpCode> to target a stable network name
          instead — useful for a production network refreshed on a schedule,
          queried later by other workflows that don&apos;t share this
          workflow&apos;s ID.
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
