"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Fan In.
 * No configuration — explains rejoin behaviour after fan-out.
 */
export function FanInHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Rejoins a fanned-out workflow into a single execution path. Steps before Fan
          In may run once per device (or per chunk) in parallel Hatchet child
          workflows; steps after Fan In run once over the merged workflow context
          containing all devices.
        </p>
        <p>
          There is no configuration on this node — place it on the canvas where
          parallel per-device work should end and shared steps should begin.
        </p>
      </HelpSection>

      <HelpSection title="When to use Fan In">
        <p>
          Enable fan-out on an inventory step (Get from Nautobot, Get from Git, etc.)
          when downstream steps do expensive or isolated per-device work — SSH, API
          calls, config retrieval. Add Fan In before any step that must run exactly
          once for the whole run.
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">Store Artifact</span> with{" "}
            <HelpCode>destination: git</HelpCode>
          </li>
          <li>
            <span className="font-medium text-foreground">Git Push</span>,{" "}
            <span className="font-medium text-foreground">Git Pull</span>,{" "}
            <span className="font-medium text-foreground">Git Clone</span> on the same
            shared source
          </li>
          <li>
            Single summary email, report, or merge step that aggregates all devices
          </li>
        </ul>
      </HelpSection>

      <HelpExample>
        Get from Nautobot (fan_out: per_device)
        <br />
        → Get Device Configs (× N children)
        <br />
        → Fan In
        <br />
        → Store Artifact (git, commit + push)
      </HelpExample>

      <HelpWarning title="Place git and store steps after Fan In">
        <p>
          Git working trees and shared git sinks are not fan-out-safe. Concurrent
          children race on clone, pull, commit, and push. Always merge with Fan In
          before Store Artifact (git) or Git Push so exports and publishes happen once.
        </p>
        <p>
          For filesystem Store Artifact on fan-out branches, use unique per-device
          paths in <HelpCode>filename_template</HelpCode> — or still prefer Fan In
          before one consolidated export.
        </p>
      </HelpWarning>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — child
            workflow results are merged; downstream steps see the combined context.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — merge or
            child completion failed. Inspect which fan-out branch failed in run logs.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Inventory step with fan-out enabled (per device or chunked).</li>
          <li>Per-device steps on the parallel branch (configs, commands, etc.).</li>
          <li>Fan In node on the convergence edge.</li>
          <li>Shared git/export or summary steps after Fan In only.</li>
        </ol>
      </HelpSection>
    </div>
  );
}
