"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Git Push.
 * Covers every Configuration control with practical examples.
 */
export function GitPushHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Pushes committed changes from the selected Settings git source to its remote.
          Use after Store Artifact (git) or other steps that modified the working tree
          when <HelpCode>push_after_write</HelpCode> is disabled on those steps — or
          as a single publish step at the end of a batch workflow.
        </p>
        <p>
          Prefer placing Git Push after{" "}
          <span className="font-medium text-foreground">Fan In</span> so one push
          publishes all device exports instead of many concurrent pushes from child
          workflows.
        </p>
      </HelpSection>

      <HelpSection title="git_source_id">
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Choose repository</span>{" "}
          (or Change repository) and select a git source from Settings → Sources.
          Stored as <HelpCode>git_source_id</HelpCode> (lowercase). Must match Git
          Clone, Store Artifact, and Git Pull steps in the same workflow.
        </p>
        <HelpExample>
          git_source_id: network-configs
          <br />
          <span className="text-muted-foreground">
            → push the local branch for that source to its configured remote
          </span>
        </HelpExample>
        <HelpWarning title="Source required">
          <p>
            Without <HelpCode>git_source_id</HelpCode> the step cannot push. Ensure a
            clone exists and commits are present if you expect changes on the remote.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="commit_before_push">
        <p>
          Default on (<HelpCode>commit_before_push: true</HelpCode>). When enabled,
          stages and commits exported files from upstream Store Artifact steps before
          pushing. Disable only when commits were already created upstream (e.g. Store
          Artifact with <HelpCode>commit_after_write</HelpCode>).
        </p>
        <HelpExample>
          commit_before_push: true
          <br />
          <span className="text-muted-foreground">
            → one commit for pending changes, then push
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="commit_message_template">
        <p>
          Shown when <HelpCode>commit_before_push</HelpCode> is on. Message for the
          commit created immediately before push. Placeholders:{" "}
          <HelpCode>{"{timestamp}"}</HelpCode>, <HelpCode>{"{run.id}"}</HelpCode>,{" "}
          <HelpCode>{"{workflow.id}"}</HelpCode>.
        </p>
        <HelpExample>
          commit_before_push: true
          <br />
          commit_message_template: workflow {"{workflow.id}"} run {"{run.id}"} at{" "}
          {"{timestamp}"}
        </HelpExample>
      </HelpSection>

      <HelpWarning title="Prefer after Fan In">
        <ul className="list-disc space-y-0.5 pl-4">
          <li>
            Do not put Git Push on a fanned-out branch — children race on the same
            repository.
          </li>
          <li>
            Pattern: fan-out → per-device exports (filesystem or in-memory) → Fan In →
            Store Artifact (git) → Git Push once.
          </li>
        </ul>
      </HelpWarning>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — changes
            reached the remote (with optional commit). Verify on the git host.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — push or
            commit failed (auth, rejected non-fast-forward, nothing to commit). Check
            run logs and remote state.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Git Clone for <HelpCode>git_source_id</HelpCode>.</li>
          <li>Store Artifact (git) with commits; or filesystem exports then Fan In.</li>
          <li>
            Git Push after Fan In with <HelpCode>commit_before_push</HelpCode> and a
            descriptive <HelpCode>commit_message_template</HelpCode>.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
