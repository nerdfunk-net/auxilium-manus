"use client";

import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Merge Content.
 * Covers every Configuration control with practical examples.
 */
export function MergeContentHelpPanel(_props: PluginConfigPanelProps) {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Combines output from one or more upstream steps into a single blob on the
          device context. Use it when Compare Data, Store Artifact, or Filter Output
          needs multiple command outputs or filtered blocks in one artifact.
        </p>
        <p>
          Merged result is stored at{" "}
          <HelpCode>{"{nodeId}.merged_content"}</HelpCode> and referenced by
          downstream steps via content source <HelpCode>merged_content</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Content source">
        <p>
          <HelpCode>content_source</HelpCode> selects which upstream step type to
          merge:
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">Command output</span> —{" "}
            <HelpCode>content_source: command_output</HelpCode>. Merge raw output from
            Run Command steps.
          </li>
          <li>
            <span className="font-medium text-foreground">Filtered output</span> —{" "}
            <HelpCode>content_source: filtered_output</HelpCode>. Merge cleaned output
            from Filter Output steps.
          </li>
          <li>
            <span className="font-medium text-foreground">Merged content</span> —{" "}
            <HelpCode>content_source: merged_content</HelpCode>. Re-merge output from
            other Merge Content steps (combine prior merges).
          </li>
        </ul>
        <HelpExample>
          content_source: command_output
          <br />
          source_step_node_ids:
          <br />
          {"  "}- run-command-1
          <br />
          {"  "}- run-command-2
        </HelpExample>
      </HelpSection>

      <HelpSection title="Source steps">
        <p>
          <HelpCode>source_step_node_ids</HelpCode> is a list of canvas node IDs to
          include. Check the boxes for specific steps, or leave none selected to merge{" "}
          <span className="font-medium text-foreground">all</span> upstream results
          of the chosen type (when content source is command output, all upstream
          run-command results are merged).
        </p>
        <HelpExample>
          source_step_node_ids:
          <br />
          {"  "}- run-command-show-version
          <br />
          {"  "}- run-command-show-route
          <br />
          <span className="text-muted-foreground">
            → only these two steps; order follows workflow graph
          </span>
        </HelpExample>
        <p>
          Changing content source clears the selection — re-check steps after
          switching between command output, filtered output, or merged content.
        </p>
      </HelpSection>

      <HelpSection title="Merge mode">
        <p>
          <HelpCode>merge_mode</HelpCode> controls output shape:
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">Sectioned text</span> —{" "}
            <HelpCode>text_sectioned</HelpCode> (default). Adds{" "}
            <HelpCode>=== {"{step}"} ===</HelpCode> headers before each block.
            Best for human-readable artifacts and diffs.
          </li>
          <li>
            <span className="font-medium text-foreground">Plain text</span> —{" "}
            <HelpCode>text_plain</HelpCode>. Joins blocks with{" "}
            <HelpCode>section_separator</HelpCode> only; no headers.
          </li>
          <li>
            <span className="font-medium text-foreground">JSON structure</span> —{" "}
            <HelpCode>json_merged</HelpCode>. Produces{" "}
            <HelpCode>{"{ \"step-node-id\": ..., ... }"}</HelpCode> keyed by source
            node ID. Best for programmatic downstream use.
          </li>
        </ul>
        <HelpExample>
          merge_mode: text_sectioned
          <br />
          include_command_header: true
          <br />
          <span className="text-muted-foreground">
            → === show version === followed by output, then next block
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Section separator">
        <p>
          For <HelpCode>text_sectioned</HelpCode> and <HelpCode>text_plain</HelpCode>,{" "}
          <HelpCode>section_separator</HelpCode> is inserted between each block
          (default newline). Type <HelpCode>\n</HelpCode> for a literal newline or
          use a custom delimiter such as <HelpCode>\n---\n</HelpCode>.
        </p>
        <HelpExample>
          merge_mode: text_plain
          <br />
          section_separator: \n\n
        </HelpExample>
        <p>
          Not used when merge mode is <HelpCode>json_merged</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Include command header">
        <p>
          When merge mode is <HelpCode>text_sectioned</HelpCode>,{" "}
          <HelpCode>include_command_header</HelpCode> (default on) prepends a header
          like <HelpCode>=== show version ===</HelpCode> before each block. Turn off
          for sectioned text without command labels.
        </p>
        <HelpExample>
          merge_mode: text_sectioned
          <br />
          include_command_header: false
          <br />
          section_separator: \n---\n
        </HelpExample>
      </HelpSection>

      <HelpSection title="Downstream usage">
        <p>
          In Compare Data or Store Artifact, set content source to{" "}
          <HelpCode>merged_content</HelpCode> and select this step as the source.
          Reference the parsed key <HelpCode>{"{nodeId}.merged_content"}</HelpCode> in
          attribute or template paths when needed.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — merge
            completed; combined content is on the device context.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — no
            upstream output found for the selected steps or type. Verify upstream
            steps ran and node IDs are correct.
          </li>
        </ul>
      </HelpSection>

      <HelpWarning title="Merge after filter when comparing">
        <p>
          Merge filtered output (not raw commands) when building artifacts for Compare
          Data — filter each source first, then merge the cleaned blocks.
        </p>
      </HelpWarning>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Add one or more Run Command (or Filter Output) steps upstream.</li>
          <li>Choose content source and select which steps to include.</li>
          <li>Pick merge mode: sectioned text for backups, JSON for structured pipelines.</li>
          <li>Point Compare Data or Store Artifact at merged content downstream.</li>
        </ol>
      </HelpSection>
    </div>
  );
}
