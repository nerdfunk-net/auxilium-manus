"use client";

import { HelpExample, HelpSection } from "../shared/step-help";

/**
 * Built-in Help tab content for Show Summary.
 * No configuration — explains the device x step table rendered in run detail.
 */
export function ShowSummaryHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Renders a table summarizing this workflow run: one row per device,
          one column per step that ran, with a green success or red failure
          indicator in each cell. There is no configuration — place it
          anywhere on the canvas where a run overview is useful, typically
          near the end of the workflow.
        </p>
        <p>
          The table is built entirely from the run&apos;s already-recorded
          step results, so it reflects the whole run — including steps that
          ran after this node — not just the steps upstream of it.
        </p>
      </HelpSection>

      <HelpSection title="Reading the table">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">Green</span> — the
            step completed successfully for that device.
          </li>
          <li>
            <span className="font-medium text-foreground">Red</span> — the
            step failed for that device, or the step failed to run at all.
            Click the cell to open the detailed error.
          </li>
          <li>
            <span className="font-medium text-foreground">Dash</span> — the
            device did not reach this step, or the step was skipped because
            an earlier failure blocked it.
          </li>
        </ul>
      </HelpSection>

      <HelpExample>
        Get Devices → Reachable → Get Device Configs → Show Summary
      </HelpExample>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> —
            always fires; this step never fails on its own.
          </li>
        </ul>
      </HelpSection>
    </div>
  );
}
