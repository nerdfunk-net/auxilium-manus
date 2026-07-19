"use client";

import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Git Pull.
 * Covers every Configuration control with practical examples.
 */
export function GitPullHelpPanel(_props: PluginConfigPanelProps) {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Pulls the latest remote changes once for the selected Settings git source.
          Use before read or write steps when another process may have pushed to the
          same branch — or when Store Artifact has{" "}
          <HelpCode>pull_before_write</HelpCode> disabled and you want an explicit
          pull earlier in the graph.
        </p>
        <p>
          Requires an existing working tree for that source (typically from an upstream{" "}
          <span className="font-medium text-foreground">Git Clone</span> step or a
          prior run).
        </p>
      </HelpSection>

      <HelpSection title="git_source_id">
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Choose repository</span>{" "}
          (or Change repository) and select a git source from Settings → Sources.
          Stored as <HelpCode>git_source_id</HelpCode> (lowercase). Must match the
          source used by Git Clone and other git steps in this workflow.
        </p>
        <HelpExample>
          git_source_id: network-configs
          <br />
          <span className="text-muted-foreground">
            → git pull on the cached clone for that source
          </span>
        </HelpExample>
        <HelpWarning title="Source required">
          <p>
            Without <HelpCode>git_source_id</HelpCode> the step cannot pull. Ensure
            the source exists in Settings and a clone is available.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpWarning title="Not fan-out-safe">
        <p>
          Do not run Git Pull on a fanned-out branch for the same{" "}
          <HelpCode>git_source_id</HelpCode> — parallel children pull and write
          concurrently and can corrupt the shared working tree.
        </p>
        <p>
          Pattern: per-device steps on fan-out branches →{" "}
          <span className="font-medium text-foreground">Fan In</span> → Git Pull (once)
          → Store Artifact / Git Push.
        </p>
      </HelpWarning>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — local
            branch is updated from remote. Downstream steps see latest commits.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — pull failed
            (conflicts, auth, network, or no clone). Resolve in logs; you may need Git
            Clone first.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Git Clone (or prior run) for the same <HelpCode>git_source_id</HelpCode>.</li>
          <li>Git Pull immediately before Store Artifact or Get from Git when freshness matters.</li>
          <li>On fanned-out workflows, place Git Pull only after Fan In.</li>
        </ol>
      </HelpSection>
    </div>
  );
}
