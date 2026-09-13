"use client";

import { HelpCode, HelpExample, HelpSection } from "../shared/step-help";

/**
 * Built-in Help tab content for Start Batfish Run.
 * No configuration -- explains why this step exists and when to use it.
 */
export function BatfishStartRunHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Produces an empty device context. Its only purpose is to satisfy
          the canvas connection rule that an{" "}
          <HelpCode>Init Batfish Snapshot</HelpCode> step needs some
          upstream step wired in — even when that step&apos;s
          <HelpCode>config_source</HelpCode> is <HelpCode>git</HelpCode> and
          it reads no devices from this run at all.
        </p>
        <p>
          There is no configuration, and no live device contact is made —
          it never SSHes into anything, so it is not a reintroduction of the
          mass-device-collection cost this step exists to avoid.
        </p>
      </HelpSection>

      <HelpSection title="When to use it">
        <p>
          Only for git-mode Batfish workflows that select no real devices.
          Live-mode Batfish workflows keep using a normal device-selection
          step (e.g. an inventory step) as before — this step is not needed
          there.
        </p>
        <HelpExample>
          Start Batfish Run → Init Batfish Snapshot (config_source: git) →
          Batfish Routing Table
        </HelpExample>
      </HelpSection>

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
