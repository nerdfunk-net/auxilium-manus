"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Store Artifact.
 * Covers every Configuration control with practical examples.
 */
export function StoreArtifactHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Exports content from the workflow context — running config, command output,
          rendered templates, merged content, diffs, or filtered output — to the
          local filesystem or a Git repository configured under Settings → Sources.
        </p>
        <p>
          Pick what to export (<HelpCode>content_source</HelpCode>), name files with
          a template (<HelpCode>filename_template</HelpCode>), and choose where they
          land (<HelpCode>destination</HelpCode>). Git mode can pull, commit, and push
          in one step; filesystem mode writes under{" "}
          <HelpCode>
            DATA_DIRECTORY/exports/&lt;workflow_id&gt;/&lt;run_id&gt;/
          </HelpCode>
          .
        </p>
      </HelpSection>

      <HelpSection title="destination">
        <p>
          Where exported files are written. Stored as{" "}
          <HelpCode>destination</HelpCode>.
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">Filesystem</span> —{" "}
            <HelpCode>filesystem</HelpCode>. Default. Files go under{" "}
            <HelpCode>
              DATA_DIRECTORY/exports/&lt;workflow_id&gt;/&lt;run_id&gt;/
            </HelpCode>{" "}
            (plus <HelpCode>output_subdirectory</HelpCode>).
          </li>
          <li>
            <span className="font-medium text-foreground">Git repository</span> —{" "}
            <HelpCode>git</HelpCode>. Writes into a git source from Settings →
            Sources. Exposes pull/commit/push options and{" "}
            <HelpCode>repository_subdirectory</HelpCode>.
          </li>
        </ul>
        <HelpExample>
          destination: filesystem
          <br />
          output_subdirectory: backups
          <br />
          filename_template: {"{device.name}"}.cfg
        </HelpExample>
      </HelpSection>

      <HelpSection title="Git destination options">
        <p>
          Shown when <HelpCode>destination</HelpCode> is <HelpCode>git</HelpCode>.
        </p>

        <p className="font-medium text-foreground">git_source_id</p>
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Choose repository</span>{" "}
          (or Change repository) and select a git source from Settings → Sources.
          Same sources as Get from Git. Stored lowercased as{" "}
          <HelpCode>git_source_id</HelpCode>.
        </p>
        <HelpExample>
          git_source_id: network-configs
          <br />
          <span className="text-muted-foreground">
            → writes into the cloned working tree for that source
          </span>
        </HelpExample>

        <p className="font-medium text-foreground">repository_subdirectory</p>
        <p>
          Optional prefix inside the repository before the filename template path.
          Example: <HelpCode>network/backups</HelpCode> places files under that folder
          in the repo.
        </p>

        <p className="font-medium text-foreground">Git sync options</p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>pull_before_write</HelpCode> — pull latest remote changes once
            before writing. Step fails if pull fails.
          </li>
          <li>
            <HelpCode>commit_after_write</HelpCode> — create one commit for all files
            written in this step.
          </li>
          <li>
            <HelpCode>push_after_write</HelpCode> — push after commit. Disable when a
            separate <span className="font-medium text-foreground">Git Push</span>{" "}
            step handles publishing.
          </li>
        </ul>

        <p className="font-medium text-foreground">commit_message_template</p>
        <p>
          Message for the commit when <HelpCode>commit_after_write</HelpCode> is on.
          Placeholders: <HelpCode>{"{timestamp}"}</HelpCode>,{" "}
          <HelpCode>{"{run.id}"}</HelpCode>,{" "}
          <HelpCode>{"{workflow.id}"}</HelpCode>.
        </p>
        <HelpExample>
          destination: git
          <br />
          git_source_id: network-configs
          <br />
          repository_subdirectory: devices
          <br />
          pull_before_write: true
          <br />
          commit_after_write: true
          <br />
          push_after_write: false
          <br />
          commit_message_template: backup {"{timestamp}"} run {"{run.id}"}
        </HelpExample>
      </HelpSection>

      <HelpSection title="content_source">
        <p>
          Which context field to export. Stored as{" "}
          <HelpCode>content_source</HelpCode>.
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">
              Upstream output (auto-detected)
            </span>{" "}
            — resolves from the nearest content-producing upstream step on the canvas.
          </li>
          <li>
            <HelpCode>running_config</HelpCode> — device running configuration
            (requires upstream get-device-configs or similar).
          </li>
          <li>
            <HelpCode>startup_config</HelpCode> — startup configuration on the device
            context.
          </li>
          <li>
            <HelpCode>command_output</HelpCode> — output from a specific Run Command
            step (pick <HelpCode>source_step</HelpCode>).
          </li>
          <li>
            <HelpCode>latest_command_output</HelpCode> — most recent command result on
            the device.
          </li>
          <li>
            <HelpCode>rendered_template</HelpCode> — output from Render Jinja Template
            (pick step + optional <HelpCode>parsed_output_key</HelpCode>).
          </li>
          <li>
            <HelpCode>merged_content</HelpCode> — output from Merge Content.
          </li>
          <li>
            <HelpCode>comparison_diff</HelpCode> — unified diff from Compare Data on
            mismatch.
          </li>
          <li>
            <HelpCode>filtered_output</HelpCode> — output from Filter Output.
          </li>
        </ul>
        <HelpExample>
          content_source: running_config
          <br />
          filename_template: {"{device.name}"}_{"{run.timestamp}"}.cfg
        </HelpExample>
      </HelpSection>

      <HelpSection title="source_step">
        <p>
          Shown when <HelpCode>content_source</HelpCode> is{" "}
          <HelpCode>command_output</HelpCode>, <HelpCode>rendered_template</HelpCode>,{" "}
          <HelpCode>merged_content</HelpCode>, <HelpCode>comparison_diff</HelpCode>, or{" "}
          <HelpCode>filtered_output</HelpCode>. Select the upstream step that produced
          the content. Stored as <HelpCode>source_step_node_id</HelpCode> (shown in
          Configuration as <HelpCode>source_step</HelpCode>).
        </p>
        <p>
          If only one matching step exists on the canvas, it is selected automatically.
          Use Advanced → enter node id manually when reusing an id from an older
          workflow.
        </p>
        <HelpExample>
          content_source: command_output
          <br />
          source_step_node_id: run-command-2
        </HelpExample>
      </HelpSection>

      <HelpSection title="parsed_output_key">
        <p>
          Shown when <HelpCode>content_source</HelpCode> is{" "}
          <HelpCode>rendered_template</HelpCode>. Optional{" "}
          <HelpCode>output_key</HelpCode> from the render step. Leave empty to export
          all templates from the selected step. Selecting a render step may auto-fill
          this from the step&apos;s configured key.
        </p>
        <HelpExample>
          content_source: rendered_template
          <br />
          source_step_node_id: render-jinja-template-1
          <br />
          parsed_output_key: device_config
        </HelpExample>
      </HelpSection>

      <HelpSection title="filename_template">
        <p>
          Path and name for each exported file. Supports placeholders and
          subdirectories.
        </p>
        <p className="font-medium text-foreground">Placeholders</p>
        <ul className="list-disc space-y-0.5 pl-4">
          <li>
            <HelpCode>{"{device.name}"}</HelpCode>,{" "}
            <HelpCode>{"{device.hostname}"}</HelpCode>,{" "}
            <HelpCode>{"{device.primary_ip4}"}</HelpCode>
          </li>
          <li>
            <HelpCode>{"{nautobot.location.name}"}</HelpCode>,{" "}
            <HelpCode>{"{nautobot.role.name}"}</HelpCode>,{" "}
            <HelpCode>{"{nautobot.custom_fields.<slug>}"}</HelpCode>
          </li>
          <li>
            <HelpCode>{"{git.source_file}"}</HelpCode>,{" "}
            <HelpCode>{"{command.name}"}</HelpCode>,{" "}
            <HelpCode>{"{parsed.output_key}"}</HelpCode>
          </li>
          <li>
            <HelpCode>{"{run.timestamp}"}</HelpCode>,{" "}
            <HelpCode>{"{run.id}"}</HelpCode>
          </li>
        </ul>
        <HelpExample>
          filename_template: ./
          {"{nautobot.location.name}"}/{"{device.name}"}.cfg
          <br />
          <span className="text-muted-foreground">
            → e.g. ./Core/router1.cfg under the export or repo path
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="strict_templates">
        <p>
          Default on (<HelpCode>strict_templates: true</HelpCode>). When enabled, the
          step fails if <HelpCode>nautobot.*</HelpCode> or <HelpCode>command.*</HelpCode>{" "}
          placeholders in <HelpCode>filename_template</HelpCode> resolve empty. Turn
          off only when empty segments in filenames are acceptable.
        </p>
      </HelpSection>

      <HelpSection title="output_subdirectory">
        <p>
          Shown when <HelpCode>destination</HelpCode> is{" "}
          <HelpCode>filesystem</HelpCode>. Prefix under{" "}
          <HelpCode>
            DATA_DIRECTORY/exports/&lt;workflow_id&gt;/&lt;run_id&gt;/
          </HelpCode>
          . Default <HelpCode>exports</HelpCode>.
        </p>
        <HelpExample>
          destination: filesystem
          <br />
          output_subdirectory: nightly-backups
          <br />
          filename_template: {"{device.name}"}.cfg
        </HelpExample>
      </HelpSection>

      <HelpWarning title="Not fan-out-safe — use Fan In first">
        <ul className="list-disc space-y-0.5 pl-4">
          <li>
            Do not place Store Artifact (<HelpCode>git</HelpCode>) on a fanned-out
            branch — concurrent child workflows race on the same working tree and
            may corrupt commits.
          </li>
          <li>
            Pattern: inventory (fan-out on) → per-device steps →{" "}
            <span className="font-medium text-foreground">Fan In</span> → store /
            git-push once.
          </li>
          <li>
            For <HelpCode>filesystem</HelpCode> on fanned-out branches, use per-device
            unique paths in <HelpCode>filename_template</HelpCode> (e.g.{" "}
            <HelpCode>{"{device.name}"}</HelpCode>) so children do not overwrite each
            other — or still prefer Fan In before a single export step.
          </li>
        </ul>
      </HelpWarning>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Run Get Device Configs or Run Command upstream so content exists in
            context.
          </li>
          <li>
            Set <HelpCode>content_source</HelpCode> (or use auto-detected upstream
            output).
          </li>
          <li>
            Configure <HelpCode>filename_template</HelpCode> with device-identifying
            placeholders.
          </li>
          <li>
            For git: choose source, set <HelpCode>repository_subdirectory</HelpCode>,
            enable pull/commit as needed; place after Fan In when workflows fan out.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
