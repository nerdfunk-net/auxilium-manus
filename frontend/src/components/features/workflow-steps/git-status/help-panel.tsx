"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Git Status.
 * Covers every Configuration control, the outcomes and the result metadata.
 */
export function GitStatusHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Inspects the local working tree of the selected Git repository and routes the
          workflow on whether it is <HelpCode>clean</HelpCode> or{" "}
          <HelpCode>dirty</HelpCode>. It never changes the working tree; the only side
          effect is an optional fetch from origin.
        </p>
      </HelpSection>

      <HelpSection title="git_repository_id">
        <p>
          Choose a repository from Settings → Git Repositories. The step inspects the
          existing cached working tree (it is cloned first if none exists yet).
        </p>
      </HelpSection>

      <HelpSection title="fetch_remote">
        <p>
          On (default): runs <HelpCode>git fetch</HelpCode> so the ahead/behind counts
          reflect the real origin. Needs network access and credentials. Off: compares
          against the last-known <HelpCode>origin/&lt;branch&gt;</HelpCode> and may be stale.
        </p>
      </HelpSection>

      <HelpSection title="check_uncommitted / check_untracked / check_sync">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>check_uncommitted</HelpCode> — modified or staged tracked files
            (reason <HelpCode>uncommitted_changes</HelpCode>).
          </li>
          <li>
            <HelpCode>check_untracked</HelpCode> — files git does not track (reason{" "}
            <HelpCode>untracked_files</HelpCode>).
          </li>
          <li>
            <HelpCode>check_sync</HelpCode> — reasons <HelpCode>ahead_of_origin</HelpCode>,{" "}
            <HelpCode>behind_origin</HelpCode>, <HelpCode>branch_mismatch</HelpCode> and{" "}
            <HelpCode>no_remote_branch</HelpCode>.
          </li>
        </ul>
        <p>A disabled check never makes the tree dirty.</p>
      </HelpSection>

      <HelpSection title="use_change_request_branch">
        <p>
          When this run deploys an approved change request, inspect that change
          request&apos;s <HelpCode>manus/cr-*</HelpCode> branch instead of the
          repository&apos;s default branch. No effect on ordinary runs.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">clean</span> — every enabled
            check passed.
          </li>
          <li>
            <span className="font-medium text-foreground">dirty</span> — at least one
            enabled check found something. The reasons are in the result.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — repository
            missing, clone/fetch failed (auth, network), or no repository configured.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Only one branch runs its git steps">
        <p>
          The outcome that was not taken is marked inactive. Git Clone, Git Pull and Git
          Push wired to it do nothing (they report a skipped result) instead of running
          against an empty device set, so a dirty tree is never pushed by the{" "}
          <HelpCode>clean</HelpCode> branch.
        </p>
      </HelpSection>

      <HelpSection title="Result details">
        <p>
          Stored in run metadata under <HelpCode>&lt;node_id&gt;.git_operation</HelpCode> and
          shown as the step summary:
        </p>
        <HelpExample>
          clean: false
          <br />
          reasons: [&quot;uncommitted_changes&quot;, &quot;behind_origin&quot;]
          <br />
          modified_files: [&quot;config/router1.cfg&quot;]
          <br />
          untracked_files: [] · ahead_count: 0 · behind_count: 3
          <br />
          <span className="text-muted-foreground">→ summary: dirty: 1 modified, 3 behind</span>
        </HelpExample>
        <p>File lists are capped at 100 entries each; counts are always exact.</p>
      </HelpSection>

      <HelpWarning title="Result is per repository">
        <p>
          The status describes the repository, not a device. On a fanned-out workflow it
          runs once per child; place it before the inventory step&apos;s fan-out or after
          a Fan In if you want a single check.
        </p>
      </HelpWarning>
    </div>
  );
}
