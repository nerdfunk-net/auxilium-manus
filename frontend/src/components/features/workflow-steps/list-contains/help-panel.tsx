"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for List Contains.
 * Covers every Configuration control with practical examples.
 */
export function ListContainsHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Checks whether a specific value is present anywhere in a list resolved
          from device context — no Jinja template required. The classic use case:
          checking whether a specific TACACS+ server is among a device&apos;s parsed
          AAA servers after Parse Cisco Config.
        </p>
        <p>
          Each device routes to exactly one outcome:{" "}
          <span className="font-medium text-foreground">match</span> (found),{" "}
          <span className="font-medium text-foreground">mismatch</span> (list
          resolved fine, value not found), or{" "}
          <span className="font-medium text-foreground">failure</span> (the list
          itself couldn&apos;t be read).
        </p>
      </HelpSection>

      <HelpSection title="List path">
        <p>
          <HelpCode>list_path</HelpCode> is the dot path to the list to search. It
          supports the same paths as Route on Attribute — <HelpCode>device.*</HelpCode>{" "}
          scalars, attribute bags (<HelpCode>nautobot.tags</HelpCode>), and{" "}
          <HelpCode>parsed.*</HelpCode> for a step&apos;s parsed output.
        </p>
        <HelpExample>
          list_path: parsed.cisco_config.aaa_servers.servers
          <br />
          <span className="text-muted-foreground">
            → the list of AAA servers parsed by Parse Cisco Config under output_key
            &quot;cisco_config&quot;
          </span>
        </HelpExample>
        <HelpWarning title="Must resolve to a list">
          <p>
            A device where <HelpCode>list_path</HelpCode> isn&apos;t populated (e.g.
            it never went through Parse Cisco Config), or resolves to something
            other than a list, routes to{" "}
            <span className="font-medium text-foreground">failure</span> — this
            usually means the workflow needs an upstream step added, or the path has
            a typo.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Field">
        <p>
          <HelpCode>field</HelpCode> names the field to read from each list item
          before comparing — needed when the list holds objects (like AAA servers,
          each with a <HelpCode>name</HelpCode>/<HelpCode>protocol</HelpCode>/
          <HelpCode>address</HelpCode>). Leave it empty when the list holds plain
          values directly (e.g. a list of VLAN ids).
        </p>
        <HelpExample>
          list_path: parsed.cisco_config.aaa_servers.servers
          <br />
          field: address
          <br />
          <span className="text-muted-foreground">
            → compares value against each server&apos;s address
          </span>
          <br />
          <br />
          list_path: parsed.cisco_config.vlans
          <br />
          field: (empty)
          <br />
          <span className="text-muted-foreground">
            → compares value against each VLAN id directly
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Value">
        <p>
          <HelpCode>value</HelpCode> is what to look for. Use a fixed value, or wrap
          a dot path in braces to resolve it per device — the same convention as Add
          to ISE and Update ISE TACACS+ Key — optionally with a fallback.
        </p>
        <HelpExample>
          value: 10.0.0.5
          <br />
          <span className="text-muted-foreground">— fixed value, same for every device</span>
          <br />
          <br />
          {"value: {custom.expected_tacacs_ip}"}
          <br />
          <span className="text-muted-foreground">
            — resolved per device from an attribute bag
          </span>
          <br />
          <br />
          {"value: {custom.expected_tacacs_ip | default('10.0.0.5')}"}
          <br />
          <span className="text-muted-foreground">
            — falls back to the default if the attribute isn&apos;t set
          </span>
        </HelpExample>
        <HelpWarning title="Unresolved expression fails the device">
          <p>
            A device whose <HelpCode>value</HelpCode> expression resolves to nothing
            (no default, and the attribute is absent) routes to{" "}
            <span className="font-medium text-foreground">failure</span>, not{" "}
            <span className="font-medium text-foreground">mismatch</span>.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Checking one specific list entry vs. “any entry at all”">
        <p>
          This step answers &quot;is this specific value present?&quot;. If you only
          need &quot;is there any entry at all&quot; (regardless of which one), Route
          on Attribute with <HelpCode>{"{exists}"}</HelpCode> on the same{" "}
          <HelpCode>list_path</HelpCode> is simpler and skips the field/value
          configuration entirely.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">match</span> — the value
            was found in the list.
          </li>
          <li>
            <span className="font-medium text-foreground">mismatch</span> — the list
            resolved fine (including an empty list) but the value wasn&apos;t found.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> —{" "}
            <HelpCode>list_path</HelpCode> wasn&apos;t populated or didn&apos;t
            resolve to a list, or <HelpCode>value</HelpCode> resolved to nothing.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Add Get Configs → Parse Cisco Config upstream.</li>
          <li>
            Set <HelpCode>list_path</HelpCode> to the parsed list you care about, and{" "}
            <HelpCode>field</HelpCode> if it&apos;s a list of objects.
          </li>
          <li>Set the value to check for.</li>
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
