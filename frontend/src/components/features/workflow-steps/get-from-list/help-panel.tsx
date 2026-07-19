"use client";

import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import {
  FanOutHelpSection,
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Get from List.
 * Covers every Configuration control with practical examples.
 */
export function GetFromListHelpPanel(_props: PluginConfigPanelProps) {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Adds a fixed list of device names to the workflow context as targets
          for downstream steps. Use when you already know the exact hostnames and
          do not need Nautobot, ISE, or Git to resolve the inventory.
        </p>
        <p>
          Each name becomes a workflow device with identity only — no IP,
          platform, or credentials until a later step enriches the context.
        </p>
      </HelpSection>

      <HelpSection title="Devices">
        <p>
          <HelpCode>devices</HelpCode> is a list of device names (one per row).
          Click the plus button to add rows; use the minus button to remove a
          row (at least one row always remains).
        </p>
        <p>
          Names are passed through as typed — use the same hostname your SSH or
          API steps expect (FQDN or short name, consistently).
        </p>
        <HelpExample>
          devices:
          <br />
          {"  "}- router1.example.com
          <br />
          {"  "}- router2.example.com
          <br />
          {"  "}- switch-core-01
        </HelpExample>
        <HelpWarning title="At least one name required">
          <p>
            Blank rows are ignored at run time, but you must configure at least
            one non-empty device name. The Configuration panel shows &quot;Enter
            at least one device name&quot; until you do.
          </p>
        </HelpWarning>
      </HelpSection>

      <FanOutHelpSection />

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — all
            configured device names were added to context.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — no
            valid device names (empty list after trimming).
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Enter one or more device hostnames.</li>
          <li>
            Enable fan-out when the next steps are expensive per device (Get
            Device Configs, Run Command).
          </li>
          <li>
            Chain Get Nautobot Attributes or Get Device Configs to enrich devices
            if you need IP or platform data.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
