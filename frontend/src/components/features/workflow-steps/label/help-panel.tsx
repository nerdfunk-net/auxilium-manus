"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

export function LabelHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this decoration does">
        <p>
          Places styled text on the workflow canvas for notes, section titles, or
          phase labels. It is saved with the workflow layout but is never executed
          and cannot be connected to other steps.
        </p>
      </HelpSection>

      <HelpSection title="text">
        <p>The string shown on the canvas.</p>
        <HelpExample>Phase 1 — inventory</HelpExample>
      </HelpSection>

      <HelpSection title="font_size">
        <p>
          Font size in pixels (typically <HelpCode>12</HelpCode>–
          <HelpCode>32</HelpCode>).
        </p>
      </HelpSection>

      <HelpSection title="font_family">
        <p>
          One of <HelpCode>sans</HelpCode>, <HelpCode>serif</HelpCode>, or{" "}
          <HelpCode>mono</HelpCode> — system font stacks only.
        </p>
      </HelpSection>

      <HelpSection title="color">
        <p>
          Text color as a hex value, e.g. <HelpCode>#0f172a</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="width / height">
        <p>
          Box size in pixels. Drag the resize handles on the canvas, or set
          exact values here.
        </p>
      </HelpSection>

      <HelpWarning title="Not a workflow step">
        <p>
          Label never appears in run results and is skipped by the execution
          engine. Use Log Message if you need runtime logging.
        </p>
      </HelpWarning>
    </div>
  );
}
