"use client";

import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Update Attribute.
 * Covers every Configuration control with practical examples.
 */
export function UpdateAttributeHelpPanel(_props: PluginConfigPanelProps) {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Writes or transforms values on the workflow device context — either a fixed
          literal or a regex-based extraction from an existing attribute. Use it to
          normalize names, copy fields between paths, or prepare values for Route on
          Attribute and downstream API steps.
        </p>
      </HelpSection>

      <HelpSection title="Mode">
        <p>
          <HelpCode>mode</HelpCode> selects how the destination value is produced:
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">Fixed value</span> —{" "}
            <HelpCode>mode: fixed</HelpCode>. Writes <HelpCode>fixed_value</HelpCode>{" "}
            directly to <HelpCode>destination_path</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">Regular expression</span> —{" "}
            <HelpCode>mode: regex</HelpCode>. Reads <HelpCode>source_path</HelpCode>,
            matches <HelpCode>pattern</HelpCode>, writes{" "}
            <HelpCode>destination_template</HelpCode> (with backrefs) to{" "}
            <HelpCode>destination_path</HelpCode>.
          </li>
        </ul>
        <HelpExample>
          mode: fixed
          <br />
          destination_path: custom.site
          <br />
          fixed_value: office-a
        </HelpExample>
      </HelpSection>

      <HelpSection title="Destination path">
        <p>
          <HelpCode>destination_path</HelpCode> is the dot-path where the result is
          stored (created or overwritten). Examples:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>device.name</HelpCode> — core device fields
          </li>
          <li>
            <HelpCode>nautobot.location.name</HelpCode> — Nautobot attribute bags
          </li>
          <li>
            <HelpCode>custom.location</HelpCode> — user-defined custom attributes
          </li>
        </ul>
        <HelpExample>
          destination_path: custom.short_name
        </HelpExample>
      </HelpSection>

      <HelpSection title="Fixed value mode">
        <p>
          When mode is <HelpCode>fixed</HelpCode>, set{" "}
          <HelpCode>fixed_value</HelpCode> to the literal string written to the
          destination. The attribute is created if it does not exist.
        </p>
        <HelpExample>
          mode: fixed
          <br />
          destination_path: custom.environment
          <br />
          fixed_value: production
        </HelpExample>
      </HelpSection>

      <HelpSection title="Regex mode">
        <p>
          When mode is <HelpCode>regex</HelpCode>, configure:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>source_path</HelpCode> — attribute to read (same path rules as
            destination).
          </li>
          <li>
            <HelpCode>pattern</HelpCode> — Python regular expression with capture
            groups.
          </li>
          <li>
            <HelpCode>destination_template</HelpCode> — output string with backrefs
            such as <HelpCode>\1</HelpCode> or named groups{" "}
            <HelpCode>\g&lt;location&gt;</HelpCode>.
          </li>
        </ul>
        <HelpExample>
          mode: regex
          <br />
          source_path: device.name
          <br />
          pattern: ^([^-]+)-.*
          <br />
          destination_template: DC-\1
          <br />
          destination_path: custom.datacenter
          <br />
          <span className="text-muted-foreground">
            → router1-lab → DC-router1 at custom.datacenter
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Regex flags">
        <p>
          <HelpCode>regex_flags</HelpCode> adjusts pattern matching:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>case_insensitive</HelpCode> — ignore letter case when matching.
          </li>
          <li>
            <HelpCode>multiline</HelpCode> — <HelpCode>^</HelpCode> and{" "}
            <HelpCode>$</HelpCode> match start/end of each line.
          </li>
          <li>
            <HelpCode>dotall</HelpCode> — <HelpCode>.</HelpCode> matches newline
            characters.
          </li>
        </ul>
        <HelpExample>
          regex_flags:
          <br />
          {"  "}case_insensitive: true
          <br />
          {"  "}multiline: false
          <br />
          {"  "}dotall: false
        </HelpExample>
      </HelpSection>

      <HelpSection title="Probe tab">
        <p>
          When mode is <HelpCode>regex</HelpCode>, open the{" "}
          <span className="font-medium text-foreground">Probe</span> tab in the step
          modal to test your pattern and destination template against sample input
          before running the workflow. Probe uses the same{" "}
          <HelpCode>source_path</HelpCode>, <HelpCode>pattern</HelpCode>,{" "}
          <HelpCode>destination_template</HelpCode>, and <HelpCode>regex_flags</HelpCode>{" "}
          from Configuration.
        </p>
        <HelpWarning title="Probe is regex-only">
          <p>
            The Probe tab appears only when mode is regular expression. Fixed-value
            updates do not need probing.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — attribute
            written (fixed) or pattern matched and template applied (regex).
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — regex mode
            with no match, invalid pattern, or missing source path. Use Probe to
            debug patterns.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Fixed mode: set destination_path and fixed_value for simple tagging or
            defaults.
          </li>
          <li>
            Regex mode: set source_path and pattern, use Probe to validate, then set
            destination_template with backrefs.
          </li>
          <li>
            Place before Route on Attribute when routing depends on a derived custom
            field.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
