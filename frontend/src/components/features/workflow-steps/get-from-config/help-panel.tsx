"use client";

import {
  FanOutHelpSection,
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "@/components/features/workflow-steps/shared/step-help";

/**
 * Built-in Help tab content for Get from Config.
 * Covers every Configuration control with practical examples.
 */
export function GetFromConfigHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Searches files in a Git source for a piece of text, and for every
          matching file, parses it with the same Cisco config parser used by{" "}
          <span className="font-medium text-foreground">Parse Cisco Config</span>{" "}
          and adds the resulting hostname to the workflow&apos;s device list. Use
          this when you know a fragment of a device&apos;s configuration (a VLAN
          name, an ACL comment, a serial number) but not its hostname.
        </p>
        <p>
          Only the hostname is kept — the step does not expose the parsed
          config or raw file text to downstream steps. Chain a{" "}
          <span className="font-medium text-foreground">Get Device Configs</span>{" "}
          step afterward if later steps need live config data.
        </p>
      </HelpSection>

      <HelpSection title="Git source">
        <p>
          Choose a source created under Settings → Sources → Git. The step
          stores that source&apos;s ID as <HelpCode>git_source_id</HelpCode>{" "}
          (normalised to lowercase).
        </p>
        <HelpWarning title="Source required">
          <p>
            Without a valid Git source the step cannot clone or search files.
            Show Preview stays disabled until a source and search text are
            configured.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Directory and file filter">
        <p>
          <HelpCode>directory</HelpCode> scopes the search to a subdirectory
          of the source (blank searches from the repository root).{" "}
          <HelpCode>file_filter</HelpCode> is a glob pattern matched against
          each file&apos;s name (blank matches every file).
        </p>
        <HelpExample>
          directory: configs/
          <br />
          file_filter: *.cfg
        </HelpExample>
      </HelpSection>

      <HelpSection title="Recursive">
        <p>
          When enabled (default), subdirectories under <HelpCode>directory</HelpCode>{" "}
          are searched too. Disable to search only the top level of the
          configured directory.
        </p>
      </HelpSection>

      <HelpSection title="Search text and case sensitivity">
        <p>
          <HelpCode>search_text</HelpCode> is the text to look for inside each
          candidate file. By default matching is case-insensitive; enable{" "}
          <HelpCode>case_sensitive</HelpCode> to require an exact-case match.
        </p>
      </HelpSection>

      <HelpSection title="Search history too">
        <p>
          When enabled, files that don&apos;t match in their current version
          are also checked against their Git history (most recent matching
          commit first). If a match is only found in an older commit, that
          commit&apos;s content is parsed — not the current working-tree
          content.
        </p>
        <HelpWarning title="Scope">
          <p>
            History search only checks the history of files that still exist
            in the current working tree — it cannot find a match in a file
            that was later deleted.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Show Preview">
        <p>
          <span className="font-medium text-foreground">Show Preview</span>{" "}
          clones or refreshes the source, runs the search, and — for every
          matching file — attempts to parse it and shows the resulting
          hostname (or <HelpCode>unparseable</HelpCode> if the file
          isn&apos;t a recognizable Cisco config) before you save or run the
          workflow. Preview is read-only.
        </p>
      </HelpSection>

      <FanOutHelpSection />

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> —
            the search ran (including zero matches) and any devices found
            were added to context.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> —
            Git clone/pull failed or the source is missing.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Configure a Git source pointing at your device config repo.</li>
          <li>
            Set <HelpCode>directory</HelpCode> / <HelpCode>file_filter</HelpCode>{" "}
            to narrow the search, and enter the <HelpCode>search_text</HelpCode>{" "}
            you&apos;re looking for.
          </li>
          <li>Preview the matches, then enable fan-out if needed.</li>
        </ol>
      </HelpSection>
    </div>
  );
}
