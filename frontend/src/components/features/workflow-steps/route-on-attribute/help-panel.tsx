"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Route on Attribute.
 * Covers every Configuration control with practical examples.
 */
export function RouteOnAttributeHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Branches the workflow per device based on an attribute value. Each route
          rule maps matching values to a named outcome handle on the canvas. Use it
          to send IOS devices down one path and NX-OS down another, or to split
          devices that have a TACACS key from those that do not.
        </p>
        <p>
          Routes are evaluated top to bottom — the{" "}
          <span className="font-medium text-foreground">first match wins</span>.
        </p>
      </HelpSection>

      <HelpSection title="Attribute path">
        <p>
          <HelpCode>attribute_path</HelpCode> is the dot-path read from each
          device&apos;s context. Examples:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>device.network_driver</HelpCode> — Netmiko driver from inventory
          </li>
          <li>
            <HelpCode>nautobot.role.name</HelpCode> — Nautobot role
          </li>
          <li>
            <HelpCode>custom.tacacs_key</HelpCode> — user-defined attribute from
            Update Attribute or upstream steps
          </li>
          <li>
            <HelpCode>parsed.cisco_config.running.hostname</HelpCode> — a step&apos;s parsed
            output (e.g. Parse Cisco Config, Render Jinja Template)
          </li>
        </ul>
        <p>
          A segment can also filter a list down to one matching item using{" "}
          <HelpCode>key[field=value]</HelpCode>, e.g.{" "}
          <HelpCode>parsed.cisco_config.running.access_lists[name=MGMT_100].style</HelpCode>{" "}
          reads the <HelpCode>style</HelpCode> field of just the ACL named{" "}
          <HelpCode>MGMT_100</HelpCode> — see the List Contains step&apos;s help for
          a full worked example (checking whether an ACL permits a specific
          source).
        </p>
        <HelpExample>
          attribute_path: device.network_driver
        </HelpExample>
      </HelpSection>

      <HelpSection title="Batfish">
        <p>
          A Batfish step (e.g. Extract Facts) writes its per-device result to{" "}
          <HelpCode>device.parsed[output_key]</HelpCode>, so it&apos;s reachable the
          same way as any other parsed output —{" "}
          <HelpCode>parsed.&lt;output_key&gt;.parsed.&lt;Fact&gt;</HelpCode>. For
          Extract Facts, <HelpCode>output_key</HelpCode> defaults to{" "}
          <HelpCode>batfish_extract_facts</HelpCode> and{" "}
          <HelpCode>.parsed</HelpCode> holds that device&apos;s node facts —
          the same shape Batfish&apos;s own <HelpCode>extractFacts</HelpCode>{" "}
          question returns per node, e.g.:
        </p>
        <HelpExample>
          {"{"}
          <br />
          {"  "}&quot;TACACS&quot;: {"{"}
          <br />
          {"    "}&quot;TACACS_Servers&quot;: [&quot;ISE_SERVER_1&quot;],
          <br />
          {"    "}&quot;TACACS_Source_Interface&quot;: null
          <br />
          {"  "}{"}"}
          <br />
          {"}"}
        </HelpExample>
        <p>
          Route on whether a device has a TACACS+ server configured by pointing
          at <HelpCode>TACACS_Servers</HelpCode> and matching on{" "}
          <HelpCode>{"{exists}"}</HelpCode> / <HelpCode>{"{empty}"}</HelpCode> —
          it&apos;s a list, so literal values won&apos;t match (see &ldquo;Special
          match tokens&rdquo; below):
        </p>
        <HelpExample>
          attribute_path:
          parsed.batfish_extract_facts.parsed.TACACS.TACACS_Servers
          <br />
          routes:
          <br />
          {"  "}- outcome: has_tacacs
          <br />
          {`    values: {exists}`}
          <br />
          default_outcome: no_tacacs
        </HelpExample>
      </HelpSection>

      <HelpSection title="Catching why a step failed (error.*)">
        <p>
          Wire a step&apos;s <HelpCode>failure</HelpCode> outcome straight into this
          node and set <HelpCode>attribute_path</HelpCode> to{" "}
          <HelpCode>error.code</HelpCode> (or <HelpCode>error.message</HelpCode>,{" "}
          <HelpCode>error.step_id</HelpCode>, <HelpCode>error.node_id</HelpCode>,{" "}
          <HelpCode>error.occurred_at</HelpCode>) to branch on{" "}
          <span className="font-medium text-foreground">why</span> it failed,
          instead of only knowing that it did. This reads the device&apos;s most
          recently accumulated error — the one the upstream step just added — so
          it only resolves to something when placed right after that step&apos;s
          failure handle.
        </p>
        <p>
          Worked example: <HelpCode>Add to Nautobot</HelpCode> fails with
          <HelpCode>device_already_exists</HelpCode> when the device it tried to
          create already exists there (Nautobot&apos;s own uniqueness-violation
          400 response, e.g. &ldquo;A device named &apos;LAB&apos; ... already
          exists in this location ...&rdquo;) — every other failure (a missing
          required field, an unreachable Nautobot source, a permissions error)
          keeps its own distinct code instead. Route the known, recoverable
          case to an update path and send everything else to a default
          &ldquo;stop the workflow&rdquo; path:
        </p>
        <HelpExample>
          attribute_path: error.code
          <br />
          routes:
          <br />
          {"  "}- outcome: update_existing
          <br />
          {"    "}values: device_already_exists
          <br />
          default_outcome: stop_workflow
        </HelpExample>
        <p>
          Connect <HelpCode>update_existing</HelpCode> to whatever updates the
          device instead of creating it (e.g. <HelpCode>Update Nautobot Device</HelpCode>
          ), and <HelpCode>stop_workflow</HelpCode> to{" "}
          <HelpCode>Notify On Error</HelpCode> or nothing further — an unhandled
          error (missing attribute, source down, permissions) should stop the
          run, not be treated as &ldquo;already exists.&rdquo;
        </p>
        <HelpWarning title="Only the most recent error is visible here">
          <p>
            A device can accumulate more than one error across a run (see{" "}
            <HelpCode>Notify On Error</HelpCode>, which reports every one of
            them), but <HelpCode>error.*</HelpCode> here only ever resolves the{" "}
            <span className="font-medium text-foreground">latest</span> one.
            That is exactly right when this node sits directly on one step&apos;s
            failure handle (the common case), but if devices could reach this
            node after failing at more than one earlier step, an older failure
            reason won&apos;t be visible — route those cases before the errors
            pile up, or use <HelpCode>Notify On Error</HelpCode> instead.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Routes">
        <p>
          <HelpCode>routes</HelpCode> is an ordered list of rules. Each rule has:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>outcome</HelpCode> — canvas handle name (e.g.{" "}
            <HelpCode>ios</HelpCode>, <HelpCode>nxos</HelpCode>). Connect edges from
            this handle to downstream steps.
          </li>
          <li>
            <HelpCode>values</HelpCode> — comma-separated literals or special tokens
            that must match the resolved attribute.
          </li>
        </ul>
        <HelpExample>
          routes:
          <br />
          {"  "}- outcome: ios
          <br />
          {"    "}values: cisco_ios, ios
          <br />
          {"  "}- outcome: nxos
          <br />
          {"    "}values: cisco_nxos, nxos
        </HelpExample>
        <p>
          Use <span className="font-medium text-foreground">Add route</span> for more
          rules. At least one route is required. Put more specific rules above broader
          ones — first match wins.
        </p>
        <HelpWarning title="Match values is a plain comma-separated field">
          <p>
            The <span className="font-medium text-foreground">Match values</span>{" "}
            box takes values separated by commas — no brackets or quotes, exactly
            as shown in the examples in this tab (e.g.{" "}
            <HelpCode>{"{exists}"}</HelpCode>, or{" "}
            <HelpCode>cisco_ios, ios</HelpCode> for more than one). Typing brackets
            or quotes (e.g. <HelpCode>[&quot;{"{exists}"}&quot;]</HelpCode>) is
            treated as one literal value equal to that whole bracketed string,
            which will never match.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Special match tokens">
        <p>
          Besides literal strings, route values can use existence tokens (click the
          chip buttons in Configuration to insert):
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>{"{absent}"}</HelpCode> — attribute_path does not exist on the
            context.
          </li>
          <li>
            <HelpCode>{"{null}"}</HelpCode> — value is null.
          </li>
          <li>
            <HelpCode>{"{empty}"}</HelpCode> — value is an empty string, list, or
            object.
          </li>
          <li>
            <HelpCode>{"{exists}"}</HelpCode> — value is present and non-empty (e.g.
            check whether a TACACS+ key was found).
          </li>
        </ul>
        <HelpExample>
          routes:
          <br />
          {"  "}- outcome: has_key
          <br />
          {`    values: {exists}`}
          <br />
          {"  "}- outcome: missing_key
          <br />
          {`    values: {absent}, {empty}`}
        </HelpExample>
        <HelpWarning title="Lists and objects only support existence tokens">
          <p>
            When <HelpCode>attribute_path</HelpCode> resolves to a list or object —
            e.g. <HelpCode>parsed.cisco_config.running.aaa_servers.servers</HelpCode>, a
            parsed list of AAA servers — literal values never match it; only{" "}
            <HelpCode>{"{exists}"}</HelpCode>/<HelpCode>{"{empty}"}</HelpCode>/
            <HelpCode>{"{absent}"}</HelpCode> work, to check whether it&apos;s
            populated at all. To check whether one specific value is present in
            that list (e.g. one particular server address, or whether an ACL
            permits a specific source), use the{" "}
            <span className="font-medium text-foreground">List Contains</span>{" "}
            step instead — it&apos;s built for exactly that.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Default outcome">
        <p>
          <HelpCode>default_outcome</HelpCode> is the handle used when no route
          matches. Example: <HelpCode>unmatched</HelpCode> for devices whose driver
          is not ios or nxos.
        </p>
        <HelpExample>
          default_outcome: unmatched
        </HelpExample>
        <HelpWarning title="Empty default fails the step">
          <p>
            Leave default_outcome empty to fail the step when nothing matches. Set a
            named default to send unmatched devices to a catch-all path instead.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Case sensitive">
        <p>
          <HelpCode>case_sensitive</HelpCode> controls literal matching (special
          tokens are unaffected). When off (default),{" "}
          <HelpCode>cisco_ios</HelpCode> matches <HelpCode>CISCO_IOS</HelpCode>. Enable
          when exact casing matters.
        </p>
        <HelpExample>
          case_sensitive: false
          <br />
          routes:
          <br />
          {"  "}- outcome: ios
          <br />
          {"    "}values: cisco_ios
        </HelpExample>
      </HelpSection>

      <HelpSection title="Outcomes">
        <p>
          Each configured route outcome plus <HelpCode>default_outcome</HelpCode>{" "}
          appears as a green output handle on the canvas node. Devices traverse
          exactly one handle per run.
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            Named route outcomes — device matched that rule&apos;s values.
          </li>
          <li>
            Default outcome — no rule matched; only when default_outcome is set.
          </li>
          <li>
            Step failure — no match and default_outcome is empty.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Ensure the attribute exists (inventory, Run Command, Update Attribute).
          </li>
          <li>Set attribute_path to the field you want to branch on.</li>
          <li>
            Add routes in priority order; use special tokens for presence checks.
          </li>
          <li>Set default_outcome for a catch-all path.</li>
          <li>Connect each outcome handle to the appropriate downstream branch.</li>
        </ol>
      </HelpSection>
    </div>
  );
}
