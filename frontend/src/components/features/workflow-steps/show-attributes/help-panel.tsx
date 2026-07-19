"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Show Attributes.
 * Covers every Configuration control with practical examples.
 */
export function ShowAttributesHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Dumps the entire workflow context for inspection: device identity, every
          attribute bag (Nautobot, Git, custom), parsed values, command metadata,
          errors, pending commands, and workflow metadata. Use it to debug what
          upstream steps produced before routing, filtering, or exporting.
        </p>
        <p>
          Output goes to worker logs (STDOUT) or a file under the run directory.
          Choose JSON for machine-readable dumps or pretty text for quick human
          review in logs or on disk.
        </p>
      </HelpSection>

      <HelpSection title="output_destination">
        <p>
          Select where the dump is written. Stored as{" "}
          <HelpCode>output_destination</HelpCode>.
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">STDOUT</span> —{" "}
            <HelpCode>stdout</HelpCode>. Prints to worker logs (visible in
            backend/Hatchet logs and run metadata). Best for short debugging runs
            when you do not need a persistent file.
          </li>
          <li>
            <span className="font-medium text-foreground">File</span> —{" "}
            <HelpCode>file</HelpCode>. Writes under{" "}
            <HelpCode>
              DATA_DIRECTORY/show-attributes/&lt;workflow_id&gt;/&lt;run_id&gt;/
            </HelpCode>
            . Use when you want to download or diff context snapshots across runs.
          </li>
        </ul>
        <HelpExample>
          output_destination: stdout
          <br />
          <span className="text-muted-foreground">
            → full context appears in the run log for this step
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="output_format">
        <p>
          How the context is serialized. Stored as{" "}
          <HelpCode>output_format</HelpCode>.
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">JSON</span> —{" "}
            <HelpCode>json</HelpCode>. Full workflow context as indented JSON.
            Default. Good for piping into jq or storing structured snapshots.
          </li>
          <li>
            <span className="font-medium text-foreground">Pretty text</span> —{" "}
            <HelpCode>pretty_text</HelpCode>. Human-readable sections for devices,
            bags, parsed data, and metadata. Easier to skim in logs or a text editor.
          </li>
        </ul>
        <HelpExample>
          output_format: pretty_text
          <br />
          output_destination: file
          <br />
          filename: context-review.txt
        </HelpExample>
      </HelpSection>

      <HelpSection title="show_parsed_templates">
        <p>
          Toggle backed by <HelpCode>show_parsed_templates</HelpCode>. When off
          (default), rendered Jinja output from upstream{" "}
          <span className="font-medium text-foreground">Render Jinja Template</span>{" "}
          steps appears only as artifact references in{" "}
          <HelpCode>device.parsed</HelpCode> entries of kind{" "}
          <HelpCode>rendered_template</HelpCode>.
        </p>
        <p>
          When on, the step also prints the full rendered template body inline in
          the dump — useful when you need to verify template output without opening
          artifact files.
        </p>
        <HelpExample>
          show_parsed_templates: true
          <br />
          <span className="text-muted-foreground">
            → dump includes rendered template text, not just artifact paths
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="filename">
        <p>
          Shown only when <HelpCode>output_destination</HelpCode> is{" "}
          <HelpCode>file</HelpCode>. Relative path inside the run directory (
          <HelpCode>
            DATA_DIRECTORY/show-attributes/&lt;workflow_id&gt;/&lt;run_id&gt;/
          </HelpCode>
          ). Parent path segments are allowed.
        </p>
        <p>
          Default is <HelpCode>attributes.txt</HelpCode>. Match the extension to{" "}
          <HelpCode>output_format</HelpCode> when it helps downstream tooling.
        </p>
        <HelpExample>
          filename: debug/context.json
          <br />
          <span className="text-muted-foreground">
            → writes to …/show-attributes/&lt;workflow_id&gt;/&lt;run_id&gt;/debug/context.json
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="append">
        <p>
          Shown only when <HelpCode>output_destination</HelpCode> is{" "}
          <HelpCode>file</HelpCode>. When off (default), each run overwrites the
          file. When on (<HelpCode>append: true</HelpCode>), new output is appended
          with a separator instead of replacing the file.
        </p>
        <p>
          Useful when the same step runs multiple times in one workflow (e.g. after
          different branches) and you want a single combined trace file.
        </p>
        <HelpExample>
          output_destination: file
          <br />
          filename: trace.log
          <br />
          append: true
        </HelpExample>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — context
            was serialized and written to the chosen destination. Check logs or the
            run directory for the dump.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — write or
            serialization failed (e.g. disk error). Inspect run logs for details.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Place after inventory and any steps whose output you want to inspect.
          </li>
          <li>
            For quick checks: <HelpCode>stdout</HelpCode> +{" "}
            <HelpCode>pretty_text</HelpCode>, then open the run log.
          </li>
          <li>
            For retained snapshots: <HelpCode>file</HelpCode> +{" "}
            <HelpCode>json</HelpCode>, set <HelpCode>filename</HelpCode>, enable{" "}
            <HelpCode>show_parsed_templates</HelpCode> if Jinja output matters.
          </li>
        </ol>
        <HelpWarning title="Debugging only">
          <p>
            Full context dumps can be large and may include sensitive data. Avoid
            leaving Show Attributes on production paths unless you need it.
          </p>
        </HelpWarning>
      </HelpSection>
    </div>
  );
}
