"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

export function BackgroundHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this decoration does">
        <p>
          Places a colored rectangle on the canvas, always drawn behind other
          steps. Use it to visually group phases or highlight regions of the
          workflow. It is never executed and cannot be connected to other steps.
        </p>
      </HelpSection>

      <HelpSection title="color">
        <p>
          Fill color as a hex value, e.g. <HelpCode>#e2e8f0</HelpCode>.
        </p>
        <HelpExample>#fef3c7</HelpExample>
      </HelpSection>

      <HelpSection title="width / height">
        <p>
          Rectangle size in pixels. Drag the resize handles on the canvas, or
          set exact values here.
        </p>
      </HelpSection>

      <HelpWarning title="Not a workflow step">
        <p>
          Background never appears in run results and is skipped by the
          execution engine. It exists only to make the canvas easier to read.
        </p>
      </HelpWarning>
    </div>
  );
}
