"use client";

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
export function UpdateAttributeHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Writes or transforms values on the workflow device context — either a fixed
          literal or a regex-based extraction from an existing attribute. Configure one or
          more attribute updates in a list; they run in order for each device. Use this to
          normalize names, copy fields between paths, or prepare values for Route on
          Attribute and downstream API steps.
        </p>
      </HelpSection>

      <HelpSection title="Attributes list">
        <p>
          <HelpCode>attributes</HelpCode> is the list of updates applied by this step.
          It starts empty. Use <span className="font-medium text-foreground">+</span> to
          add an update, the pencil button to edit, and{" "}
          <span className="font-medium text-foreground">−</span> to remove. Each entry
          has its own mode and fields.
        </p>
        <HelpExample>
          attributes:
          <br />
          {"  "}- mode: fixed
          <br />
          {"    "}destination_path: custom.site
          <br />
          {"    "}fixed_value: office-a
          <br />
          {"  "}- mode: regex
          <br />
          {"    "}source_path: device.name
          <br />
          {"    "}destination_path: custom.datacenter
          <br />
          {"    "}pattern: ^([^-]+)-.*
          <br />
          {"    "}destination_template: DC-\1
        </HelpExample>
      </HelpSection>

      <HelpSection title="Mode">
        <p>
          <HelpCode>mode</HelpCode> (per attribute) selects how the destination value is
          produced:
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
          When any attribute uses <HelpCode>mode: regex</HelpCode>, open the{" "}
          <span className="font-medium text-foreground">Probe</span> tab in the step
          modal to test that pattern and destination template against sample input
          before running the workflow. If multiple regex updates exist, pick which one
          to probe. Probe uses the same <HelpCode>source_path</HelpCode>,{" "}
          <HelpCode>pattern</HelpCode>, <HelpCode>destination_template</HelpCode>, and{" "}
          <HelpCode>regex_flags</HelpCode> from that attribute.
        </p>
        <HelpWarning title="Probe is regex-only">
          <p>
            The Probe tab appears only when at least one attribute uses regular
            expression mode. Fixed-value updates do not need probing.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — step
            completed. Fixed updates always write; regex updates that do not match are
            skipped for that device.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Click + and choose fixed mode: set destination_path and fixed_value for
            simple tagging or defaults.
          </li>
          <li>
            Add another entry in regex mode: set source_path and pattern, use Probe to
            validate, then set destination_template with backrefs.
          </li>
          <li>
            Place before Route on Attribute when routing depends on derived custom
            fields.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
