"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Update Content.
 * Covers every Configuration control with practical examples.
 */
export function UpdateContentHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Applies one or more ordered regex search/replace rules to a device&apos;s running or
          startup config text and stores the result as a new artifact for downstream
          steps. Use this to rewrite lines such as an NTP server address before the
          config is uploaded back to the device. Run this after a Get Configs step so a{" "}
          <HelpCode>running_config</HelpCode> / <HelpCode>startup_config</HelpCode> is
          available on each device.
        </p>
      </HelpSection>

      <HelpSection title="Content source">
        <p>
          <HelpCode>content_source</HelpCode> selects which config text to edit:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>running_config</HelpCode> — the device&apos;s active configuration.
          </li>
          <li>
            <HelpCode>startup_config</HelpCode> — the device&apos;s saved boot configuration.
          </li>
        </ul>
        <HelpExample>content_source: running_config</HelpExample>
      </HelpSection>

      <HelpSection title="Replace rules">
        <p>
          <HelpCode>replace_rules</HelpCode> is the ordered list of search/replace rules
          applied to the content. It starts empty. Use{" "}
          <span className="font-medium text-foreground">+</span> to add a rule, the pencil
          button to edit, and <span className="font-medium text-foreground">−</span> to
          remove. Rules run in list order — each rule sees the text produced by the
          previous rule.
        </p>
        <HelpExample>
          replace_rules:
          <br />
          {"  "}- pattern: {"ntp server 192\\.168\\.1\\.10"}
          <br />
          {"    "}replacement: ntp server 192.168.178.10
          <br />
          {"    "}replace_all: true
        </HelpExample>
      </HelpSection>

      <HelpSection title="Pattern and replacement">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>pattern</HelpCode> — Python regular expression matched against the
            config text (with capture groups if needed).
          </li>
          <li>
            <HelpCode>replacement</HelpCode> — fixed text, or a template using backrefs
            such as <HelpCode>\1</HelpCode> or named groups{" "}
            <HelpCode>\g&lt;name&gt;</HelpCode> to reuse captured groups.
          </li>
        </ul>
        <HelpExample>
          pattern: {"(ntp server )\\d+\\.\\d+\\.\\d+\\.\\d+"}
          <br />
          replacement: {"\\g<1>192.168.178.10"}
          <br />
          <span className="text-muted-foreground">
            → ntp server 192.168.1.10 → ntp server 192.168.178.10
          </span>
        </HelpExample>
        <p>
          A rule that does not match anything leaves the text unchanged for that rule and
          is not an error — later rules still run.
        </p>
      </HelpSection>

      <HelpSection title="Replace all">
        <p>
          <HelpCode>replace_all</HelpCode> controls how many matches a rule rewrites:
          checked (default) replaces every occurrence; unchecked replaces only the first
          match.
        </p>
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
            <HelpCode>$</HelpCode> match start/end of each line (useful for line-anchored
            config patterns).
          </li>
          <li>
            <HelpCode>dotall</HelpCode> — <HelpCode>.</HelpCode> matches newline
            characters.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Probe tab">
        <p>
          Open the <span className="font-medium text-foreground">Probe</span> tab in the
          step modal to test a rule against a pasted config snippet before running the
          workflow. If multiple rules exist, pick which one to probe. Probe uses the same{" "}
          <HelpCode>pattern</HelpCode>, <HelpCode>replacement</HelpCode>,{" "}
          <HelpCode>regex_flags</HelpCode>, and <HelpCode>replace_all</HelpCode> from that
          rule.
        </p>
        <HelpWarning title="Sample text only">
          <p>
            Probe runs against the sample text you paste in, not a live device&apos;s stored
            config.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the config was
            rewritten and stored for every device that reached this step.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — a device had no{" "}
            <HelpCode>running_config</HelpCode>/<HelpCode>startup_config</HelpCode> ref
            (add a Get Configs step upstream) or another error occurred.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Get Nautobot Devices → Get Configs to populate running_config.</li>
          <li>
            Add Update Content, set content_source to running_config, and add one or more
            replace rules — use Probe to validate each pattern against a sample line.
          </li>
          <li>
            Place before an upload/deploy step so the rewritten config is what gets
            pushed to the device.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
