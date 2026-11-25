"use client";

import { HelpCode, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for From Change Request.
 * Covers every Configuration control (see doc/CICD_PIPELINE.md).
 */
export function FromChangeRequestHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          First step of a <strong>deploy</strong> workflow. It rebuilds the device list from the
          snapshot that Open Change Request captured, checks out the{" "}
          <HelpCode>{"manus/cr-{id}"}</HelpCode> branch pinned to the reviewed commit and restores
          the configured branch afterwards. No upstream inventory step is needed.
        </p>
        <p>
          A typical deploy workflow is From Change Request → Upload Config → Configure Replace
          Config.
        </p>
      </HelpSection>

      <HelpSection title="load_configs">
        <p>
          On (default): each device&apos;s committed config file is loaded as{" "}
          <HelpCode>running_config</HelpCode>, so you can go straight to Upload Config or
          Configure Replace Config. Off: only the devices are produced.
        </p>
      </HelpSection>

      <HelpWarning title="Only for runs started by a change request">
        <p>
          The step fails when the run was not started by approving a change request.
        </p>
      </HelpWarning>
    </div>
  );
}
