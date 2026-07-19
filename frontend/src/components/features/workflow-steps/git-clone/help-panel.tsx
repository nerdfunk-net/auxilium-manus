"use client";

import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Git Clone.
 * Covers every Configuration control with practical examples.
 */
export function GitCloneHelpPanel(_props: PluginConfigPanelProps) {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Clones or re-clones the selected Settings git source into the worker&apos;s
          local working tree before other steps run. Use at the start of a workflow
          that reads from or writes to a repository — or after a long gap when you
          need a fresh clone.
        </p>
        <p>
          Downstream steps such as Get from Git, Store Artifact (git), Git Pull, and
          Git Push all reference the same <HelpCode>git_source_id</HelpCode> working
          tree once it exists.
        </p>
      </HelpSection>

      <HelpSection title="git_source_id">
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Choose repository</span>{" "}
          (or Change repository) and select a git source created under Settings →
          Sources. The step stores that source&apos;s ID as{" "}
          <HelpCode>git_source_id</HelpCode> (normalized to lowercase).
        </p>
        <p>
          Credentials and remote URL are resolved from settings at run time — they are
          not pasted into the step config. Same source picker as Get from Git and
          Store Artifact.
        </p>
        <HelpExample>
          git_source_id: network-configs
          <br />
          <span className="text-muted-foreground">
            → clone https://git.example.com/network/configs.git into the worker cache
          </span>
        </HelpExample>
        <HelpWarning title="Source required">
          <p>
            Without a valid <HelpCode>git_source_id</HelpCode> the step cannot clone.
            Configuration shows &quot;Not configured&quot; until you pick a repository.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpWarning title="Not fan-out-safe for the same source">
        <p>
          If the workflow fans out per device, do not run Git Clone on every child
          against the same <HelpCode>git_source_id</HelpCode> — parallel clones and
          writes contend for one working tree.
        </p>
        <p>
          Pattern: Git Clone once before fan-out, or clone on the main path only;
          per-device work on fanned branches;{" "}
          <span className="font-medium text-foreground">Fan In</span> before shared
          git steps (Store Artifact, Git Push).
        </p>
      </HelpWarning>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — repository
            is cloned or refreshed in the worker cache. Downstream git steps can
            operate on it.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — clone failed
            (bad credentials, network, or missing source). Fix Settings → Sources and
            check run logs.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Configure a git source under Settings → Sources.</li>
          <li>
            Add Git Clone as the first git step; select the same{" "}
            <HelpCode>git_source_id</HelpCode> later steps will use.
          </li>
          <li>
            Follow with Get from Git, Store Artifact, or Git Pull/Push as needed — after
            Fan In if the workflow fans out per device.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
