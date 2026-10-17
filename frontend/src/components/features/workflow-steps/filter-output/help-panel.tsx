"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Filter Output.
 * Covers every Configuration control with practical examples.
 */
export function FilterOutputHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Removes volatile or unwanted fields from command or merged content before
          comparison or storage. Applies regex patterns or dot-path selectors to strip
          keys/lines that would cause false mismatches (uptime, timestamps, dynamic
          routes).
        </p>
        <p>
          The filtered result is stored on the device context as{" "}
          <HelpCode>filtered_output</HelpCode> for downstream Compare Data, Merge
          Content, or Store Artifact steps.
        </p>
      </HelpSection>

      <HelpSection title="Content source">
        <p>
          <HelpCode>content_source</HelpCode> selects where input comes from:
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">
              Upstream output (auto-detected)
            </span>{" "}
            — picks the nearest upstream run-command or merge-content step
            automatically when available.
          </li>
          <li>
            <span className="font-medium text-foreground">Command output</span> —{" "}
            <HelpCode>content_source: command_output</HelpCode>. Read output from a
            specific Run Command step.
          </li>
          <li>
            <span className="font-medium text-foreground">Merged content</span> —{" "}
            <HelpCode>content_source: merged_content</HelpCode>. Read output from a
            Merge Content step.
          </li>
        </ul>
        <HelpExample>
          content_source: command_output
          <br />
          source_step_node_id: run-command-2
        </HelpExample>
      </HelpSection>

      <HelpSection title="Source step">
        <p>
          <HelpCode>source_step_node_id</HelpCode> identifies the upstream step node
          (canvas node ID). Choose from the dropdown or type the ID directly (e.g.{" "}
          <HelpCode>run-command-3</HelpCode>).
        </p>
        <p>
          When only one matching upstream step exists, it is auto-selected. The step
          must exist in the same workflow branch.
        </p>
        <HelpExample>
          source_step_node_id: run-command-3
          <br />
          <span className="text-muted-foreground">
            → filters output from the Run Command node run-command-3
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Source command">
        <p>
          When <HelpCode>content_source</HelpCode> is{" "}
          <HelpCode>command_output</HelpCode>, <HelpCode>source_command</HelpCode> is
          optional. Leave empty to filter the first command&apos;s output. Enter the
          exact command string to filter a specific command from a multi-command Run
          Command step.
        </p>
        <HelpExample>
          source_command: show ip route
          <br />
          <span className="text-muted-foreground">
            → filters only the show ip route block, not show version
          </span>
        </HelpExample>
        <p>
          Omit this field when the Run Command step has a single command or you want
          the first entry in the list.
        </p>
      </HelpSection>

      <HelpSection title="Filter rules">
        <p>
          <HelpCode>filter_rules</HelpCode> is a list of removal rules applied in
          order. Add at least one rule. Each rule is either{" "}
          <HelpCode>pattern</HelpCode> or <HelpCode>path</HelpCode>.
        </p>

        <p className="font-medium text-foreground">Pattern (regex)</p>
        <p>
          Regex matched against JSON key names (recursive) or text line content.
          Matching keys/lines are removed.
        </p>
        <HelpExample>
          filter_rules:
          <br />
          {"  "}- pattern: ^uptime
          <br />
          {"  "}- pattern: Last configuration change
          <br />
          <span className="text-muted-foreground">
            → strips uptime fields and config-change timestamps from parsed JSON or text
          </span>
        </HelpExample>

        <p className="font-medium text-foreground">Path (dot notation)</p>
        <p>
          Dot-notation path to remove a specific nested JSON key. Example:{" "}
          <HelpCode>route.ospf</HelpCode> removes{" "}
          <HelpCode>data.route.ospf</HelpCode> from parsed output.
        </p>
        <HelpExample>
          filter_rules:
          <br />
          {"  "}- path: route.ospf
          <br />
          {"  "}- path: interfaces.GigabitEthernet0/1.last_flapped
        </HelpExample>
      </HelpSection>

      <HelpSection title="When to use">
        <p>
          Place Filter Output <span className="font-medium text-foreground">before</span>{" "}
          Compare Data or Store Artifact when source data includes fields that change
          every run but are not meaningful for drift detection.
        </p>
        <HelpWarning title="Filter before compare">
          <p>
            Comparing raw command output with uptime or dynamic routing tables often
            produces false mismatches. Filter volatile fields first, then compare or
            store the cleaned result.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — filtering
            completed; <HelpCode>filtered_output</HelpCode> is on the device context.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — missing
            source step, no upstream output, or invalid rules. Verify{" "}
            <HelpCode>source_step_node_id</HelpCode> and that the upstream step ran
            successfully.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Add Run Command (or Merge Content) upstream.</li>
          <li>Set content source and pick the source step.</li>
          <li>
            Optionally set source_command when filtering one command from a list.
          </li>
          <li>
            Add pattern rules for timestamps/uptime and path rules for nested JSON
            keys you want stripped.
          </li>
          <li>Wire Compare Data or Store Artifact to filtered output downstream.</li>
        </ol>
      </HelpSection>
    </div>
  );
}
