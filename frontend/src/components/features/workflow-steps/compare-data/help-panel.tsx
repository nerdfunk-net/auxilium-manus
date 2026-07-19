"use client";

import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Compare Data.
 * Covers every Configuration control with practical examples.
 */
export function CompareDataHelpPanel(_props: PluginConfigPanelProps) {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Compares workflow data (running config, command output, merged content,
          etc.) against a reference file on the filesystem or in a git repository.
          Each device routes to a <HelpCode>match</HelpCode>,{" "}
          <HelpCode>mismatch</HelpCode>, or <HelpCode>failure</HelpCode> outcome handle.
        </p>
        <p>
          On mismatch, a unified diff is stored per device at{" "}
          <HelpCode>{"{nodeId}.comparison_diff"}</HelpCode> for downstream steps
          (logging, notifications, remediation).
        </p>
      </HelpSection>

      <HelpSection title="Content source">
        <p>
          <HelpCode>content_source</HelpCode> selects what to compare:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">
              Upstream output (auto-detected)
            </span>{" "}
            — nearest content-producing step when available.
          </li>
          <li>
            <HelpCode>running_config</HelpCode> — from Get Device Configs (or similar).
          </li>
          <li>
            <HelpCode>startup_config</HelpCode> — startup configuration on device context.
          </li>
          <li>
            <HelpCode>command_output</HelpCode> — specific Run Command step (requires
            source step).
          </li>
          <li>
            <HelpCode>latest_command_output</HelpCode> — most recent command result on
            the device.
          </li>
          <li>
            <HelpCode>rendered_template</HelpCode> — output from Render Jinja Template
            (requires source step + parsed_output_key).
          </li>
          <li>
            <HelpCode>merged_content</HelpCode> — output from Merge Content.
          </li>
          <li>
            <HelpCode>filtered_output</HelpCode> — output from Filter Output (recommended
            after stripping volatile fields).
          </li>
        </ul>
        <HelpExample>
          content_source: filtered_output
          <br />
          source_step_node_id: filter-output-1
        </HelpExample>
      </HelpSection>

      <HelpSection title="Source step">
        <p>
          When content source is <HelpCode>command_output</HelpCode>,{" "}
          <HelpCode>rendered_template</HelpCode>, <HelpCode>merged_content</HelpCode>,
          or <HelpCode>filtered_output</HelpCode>, set{" "}
          <HelpCode>source_step_node_id</HelpCode> to the upstream node ID. Pick from
          the dropdown or type directly (e.g. <HelpCode>run-command-3</HelpCode>).
        </p>
        <HelpExample>
          content_source: command_output
          <br />
          source_step_node_id: run-command-2
        </HelpExample>
      </HelpSection>

      <HelpSection title="Parsed output key">
        <p>
          When <HelpCode>content_source</HelpCode> is{" "}
          <HelpCode>rendered_template</HelpCode>, set{" "}
          <HelpCode>parsed_output_key</HelpCode> to the{" "}
          <HelpCode>output_key</HelpCode> from the Render Jinja Template step. This
          selects <HelpCode>device.parsed.{"{output_key}"}</HelpCode> as the left-hand
          comparison input.
        </p>
        <HelpExample>
          content_source: rendered_template
          <br />
          source_step_node_id: render-jinja-1
          <br />
          parsed_output_key: device_config
        </HelpExample>
      </HelpSection>

      <HelpSection title="Reference location">
        <p>
          <HelpCode>reference_location</HelpCode> chooses where reference files live:
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">Filesystem</span> —{" "}
            <HelpCode>reference_location: filesystem</HelpCode>. Files under{" "}
            <HelpCode>DATA_DIRECTORY/&lt;reference_subdirectory&gt;/</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">Git repository</span> —{" "}
            <HelpCode>reference_location: git</HelpCode>. Files from a git source in
            Settings → Sources.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Filesystem reference">
        <p>
          <HelpCode>reference_subdirectory</HelpCode> is the folder under the server
          data directory (default <HelpCode>references</HelpCode>). Combined with{" "}
          <HelpCode>filename_template</HelpCode> to resolve the full path per device.
        </p>
        <HelpExample>
          reference_location: filesystem
          <br />
          reference_subdirectory: references
          <br />
          filename_template: {"{device.name}"}.cfg
          <br />
          <span className="text-muted-foreground">
            → reads DATA_DIRECTORY/references/router1.cfg
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Git reference">
        <p>
          When reference location is git, configure:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>git_source_id</HelpCode> — repository from Settings → Sources
            (click Choose repository).
          </li>
          <li>
            <HelpCode>repository_subdirectory</HelpCode> — path inside the repo (e.g.{" "}
            <HelpCode>network/backups</HelpCode>).
          </li>
          <li>
            <HelpCode>pull_before_read</HelpCode> — when on, pulls latest changes once
            before reading the reference file.
          </li>
        </ul>
        <HelpExample>
          reference_location: git
          <br />
          git_source_id: config-repo
          <br />
          repository_subdirectory: devices/core
          <br />
          pull_before_read: true
          <br />
          filename_template: {"{device.name}"}.cfg
        </HelpExample>
      </HelpSection>

      <HelpSection title="Filename template">
        <p>
          <HelpCode>filename_template</HelpCode> builds the reference file path per
          device. Supports placeholders:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>{"{device.name}"}</HelpCode>,{" "}
            <HelpCode>{"{device.hostname}"}</HelpCode>,{" "}
            <HelpCode>{"{device.primary_ip4}"}</HelpCode>
          </li>
          <li>
            <HelpCode>{"{nautobot.location.name}"}</HelpCode>,{" "}
            <HelpCode>{"{nautobot.role.name}"}</HelpCode>
          </li>
          <li>
            <HelpCode>{"{git.source_file}"}</HelpCode>,{" "}
            <HelpCode>{"{command.name}"}</HelpCode>,{" "}
            <HelpCode>{"{parsed.output_key}"}</HelpCode>
          </li>
          <li>
            <HelpCode>{"{run.timestamp}"}</HelpCode>, <HelpCode>{"{run.id}"}</HelpCode>
          </li>
        </ul>
        <HelpExample>
          filename_template: {"{nautobot.location.name}"}/{"{device.name}"}.cfg
        </HelpExample>
      </HelpSection>

      <HelpSection title="Comparison options">
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>strict_templates</HelpCode> — when on (default), unresolved
            filename placeholders fail the step instead of silently skipping.
          </li>
          <li>
            <HelpCode>normalize_line_endings</HelpCode> — when on (default), normalizes
            CRLF/LF before diffing.
          </li>
          <li>
            <HelpCode>ignore_trailing_whitespace</HelpCode> — when on, ignores trailing
            spaces on each line (off by default).
          </li>
        </ul>
        <HelpExample>
          strict_templates: true
          <br />
          normalize_line_endings: true
          <br />
          ignore_trailing_whitespace: false
        </HelpExample>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">match</span> — workflow data
            equals the reference file (after normalization options).
          </li>
          <li>
            <span className="font-medium text-foreground">mismatch</span> — content
            differs. Unified diff written to{" "}
            <HelpCode>{"{nodeId}.comparison_diff"}</HelpCode> on the device context.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — reference
            file missing, unreadable, placeholder error, or upstream data unavailable.
          </li>
        </ul>
      </HelpSection>

      <HelpWarning title="Filter volatile fields first">
        <p>
          Compare raw command output only when stable. Prefer Filter Output upstream
          to strip uptime, timestamps, and dynamic routes before comparison.
        </p>
      </HelpWarning>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Produce content upstream (Get Device Configs, Run Command + Filter Output,
            etc.).
          </li>
          <li>Set content source; pick source step when required.</li>
          <li>
            Place reference files under filesystem references/ or in a git repo; set
            filename_template to match your naming convention.
          </li>
          <li>
            Wire match / mismatch / failure handles to remediation, logging, or
            notification steps.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
