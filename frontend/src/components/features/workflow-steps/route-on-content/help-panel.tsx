"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Route on Content.
 * Covers every Configuration control with practical examples.
 */
export function RouteOnContentHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Searches device content — running config, command output, a rendered
          template, and more — for fixed text or a regular expression, and routes
          each device to <HelpCode>match</HelpCode>, <HelpCode>mismatch</HelpCode>, or{" "}
          <HelpCode>failure</HelpCode>.
        </p>
        <p>
          Real-world example: Cisco changed TACACS+ syntax across IOS releases —
          newer devices use <HelpCode>tacacs server NAME</HelpCode>, older ones use{" "}
          <HelpCode>tacacs-server host &lt;ip&gt; key &lt;key&gt;</HelpCode>. A fixed-text
          search for <HelpCode>tacacs-server</HelpCode> tells the two apart without
          needing Parse Cisco Config or a regular expression.
        </p>
      </HelpSection>

      <HelpSection title="Content source">
        <p>
          <HelpCode>content_source</HelpCode> selects what to search — the same set
          Compare Data supports:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>running_config</HelpCode> / <HelpCode>startup_config</HelpCode> —
            from Get Device Configs.
          </li>
          <li>
            <HelpCode>command_output</HelpCode> — a specific Run Command step (requires
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
            <HelpCode>filtered_output</HelpCode> — output from Filter Output.
          </li>
          <li>
            <HelpCode>comparison_diff</HelpCode> — the unified diff from Compare Data.
          </li>
        </ul>
        <HelpExample>
          content_source: running_config
        </HelpExample>
      </HelpSection>

      <HelpSection title="Source step">
        <p>
          When content source is <HelpCode>command_output</HelpCode>,{" "}
          <HelpCode>rendered_template</HelpCode>, <HelpCode>merged_content</HelpCode>,{" "}
          <HelpCode>filtered_output</HelpCode>, or <HelpCode>comparison_diff</HelpCode>,
          set <HelpCode>source_step_node_id</HelpCode> to the upstream node ID. Pick
          from the dropdown or type directly.
        </p>
      </HelpSection>

      <HelpSection title="Fixed text vs. regular expression">
        <p>
          <HelpCode>match_mode</HelpCode> chooses how <HelpCode>pattern</HelpCode> is
          interpreted:
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">fixed_text</span> — a literal
            substring search. Simple and predictable — use this whenever you&apos;re just
            checking whether some text is present.
          </li>
          <li>
            <span className="font-medium text-foreground">regex</span> — a Python-style
            regular expression, for patterns fixed text can&apos;t express (alternation,
            anchors, wildcards, capturing a value).
          </li>
        </ul>
        <HelpExample>
          match_mode: fixed_text
          <br />
          pattern: tacacs-server
          <br />
          <span className="text-muted-foreground">
            → true whether it appears anywhere in the config
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Pattern and {path.to.attribute} placeholders">
        <p>
          <HelpCode>pattern</HelpCode> supports the same{" "}
          <HelpCode>{"{path.to.attribute}"}</HelpCode> placeholder syntax as Workflow
          Log — each placeholder is resolved per device (attribute bags, parsed output,
          or core device fields) and substituted before matching.
        </p>
        <HelpExample>
          match_mode: fixed_text
          <br />
          {"pattern: tacacs-server host {nautobot.tacacs_ip}"}
          <br />
          <span className="text-muted-foreground">
            → checks for that device&apos;s expected TACACS+ IP specifically
          </span>
        </HelpExample>
        <HelpWarning title="Placeholder values are regex-escaped in regex mode">
          <p>
            In <HelpCode>regex</HelpCode> mode, a resolved placeholder value (e.g. an IP
            address) is escaped before being spliced into the pattern, so characters
            like <HelpCode>.</HelpCode> are matched literally instead of acting as
            regex wildcards. A device whose placeholder doesn&apos;t resolve to
            anything (pattern renders to an empty string) routes to{" "}
            <span className="font-medium text-foreground">failure</span>.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Case sensitive">
        <p>
          <HelpCode>case_sensitive</HelpCode> — when disabled (default), matching
          ignores letter case in both modes.
        </p>
      </HelpSection>

      <HelpSection title="Multiline (regex only)">
        <p>
          <HelpCode>multiline</HelpCode> only applies in <HelpCode>regex</HelpCode>{" "}
          mode — fixed-text matching is unaffected either way. When enabled,{" "}
          <HelpCode>^</HelpCode> and <HelpCode>$</HelpCode> match at the start/end of
          each line within the content, not just the start/end of the whole text —
          the standard regex &quot;multiline&quot; flag (like JavaScript&apos;s{" "}
          <HelpCode>m</HelpCode> flag).
        </p>
        <HelpExample>
          match_mode: regex
          <br />
          pattern: ^tacacs-server
          <br />
          multiline: true
          <br />
          <span className="text-muted-foreground">
            → matches a line starting with tacacs-server anywhere in a multi-line config
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">match</span> — the pattern
            was found in the content.
          </li>
          <li>
            <span className="font-medium text-foreground">mismatch</span> — the content
            was read fine but the pattern wasn&apos;t found.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — the selected
            content source wasn&apos;t available on the device, the pattern was invalid
            regex, or a <HelpCode>{"{path.to.attribute}"}</HelpCode> placeholder
            resolved to nothing.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Add Get Device Configs (or another content-producing step) upstream.</li>
          <li>Set content_source; pick source step when required.</li>
          <li>
            Choose fixed text or regex, and write the pattern — use{" "}
            <HelpCode>{"{path.to.attribute}"}</HelpCode> for per-device values.
          </li>
          <li>
            Connect <span className="font-medium text-foreground">match</span> /{" "}
            <span className="font-medium text-foreground">mismatch</span> /{" "}
            <span className="font-medium text-foreground">failure</span> to the
            appropriate downstream branches.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
