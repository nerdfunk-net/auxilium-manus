"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Update Config Context.
 * Covers every Configuration control with practical examples.
 */
export function UpdateConfigContextHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Writes, updates, or appends into a Nautobot device&apos;s{" "}
          <span className="font-medium text-foreground">local config context</span> (
          <HelpCode>local_config_context_data</HelpCode>) — the per-device JSON blob
          Nautobot layers on top of any global config context at render time. Typical
          uses: pushing a freshly generated TACACS+ key or password into a device&apos;s
          credentials, or adding a new configuration section without disturbing the rest.
        </p>
        <HelpWarning title="Nautobot replaces this field wholesale">
          <p>
            There is no server-side partial update on this field. For{" "}
            <HelpCode>update</HelpCode> and <HelpCode>append</HelpCode>, this step reads
            the current value, computes the new document, and writes the whole thing
            back — so other steps writing to the same device&apos;s config context at the
            same time can race. Prefer one Update Config Context step per device per run.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Nautobot source and device_identifier">
        <p>
          Click <span className="font-medium text-foreground">Configure Source</span> to
          choose a Nautobot source created under Settings → Sources. Leave{" "}
          <HelpCode>device_identifier</HelpCode> as{" "}
          <span className="font-medium text-foreground">From workflow context</span> when
          this step runs after an inventory step — it targets whichever devices reached
          it. Switch to{" "}
          <span className="font-medium text-foreground">Explicit device</span> only when
          running this step standalone, and supply an id or a name.
        </p>
      </HelpSection>

      <HelpSection title="mode">
        <p>Given this existing local config context:</p>
        <HelpExample>{`{
  "credentials": [
    { "level": "", "password": "old-pw", "privilege": 15, "username": "noc" }
  ]
}`}</HelpExample>
        <ul className="list-disc space-y-2 pl-4">
          <li>
            <span className="font-medium text-foreground">Write</span> — replaces the
            entire config context, regardless of what is currently there.{" "}
            <HelpCode>path</HelpCode> is ignored; the resolved value must be a JSON
            object.
          </li>
          <li>
            <span className="font-medium text-foreground">Update</span> — sets the value
            at <HelpCode>path</HelpCode>, leaving every other key untouched. Example:{" "}
            <HelpCode>path: credentials.0.password</HelpCode> with a new password value
            changes only that one field, keeping <HelpCode>username</HelpCode> and{" "}
            <HelpCode>privilege</HelpCode> as they were.
          </li>
          <li>
            <span className="font-medium text-foreground">Append</span> — adds a new key
            at <HelpCode>path</HelpCode>. If something is already there and both the
            existing value and the new value are objects, they are merged (new keys
            added, matching keys overwritten, other keys kept). Example:{" "}
            <HelpCode>path: tacacs</HelpCode> with an object value adds a brand-new{" "}
            <HelpCode>tacacs</HelpCode> root key while leaving{" "}
            <HelpCode>credentials</HelpCode> exactly as it was. Leave{" "}
            <HelpCode>path</HelpCode> empty to merge the resolved value&apos;s own
            top-level keys directly into the document root instead — a rendered
            template of <HelpCode>{`{"xxx": {"key": "value"}}`}</HelpCode> with an
            empty path produces:
          </li>
        </ul>
        <HelpExample>{`{
  "credentials": [
    { "level": "", "password": "old-pw", "privilege": 15, "username": "noc" }
  ],
  "xxx": { "key": "value" }
}`}</HelpExample>
      </HelpSection>

      <HelpSection title="path">
        <p>
          A dotted path into <HelpCode>local_config_context_data</HelpCode>. A segment is
          treated as a list index only when it is a plain number and the current position
          is a list — for example <HelpCode>credentials.0.password</HelpCode> (or{" "}
          <HelpCode>credentials[0].password</HelpCode>) reaches into the first item of the{" "}
          <HelpCode>credentials</HelpCode> list. Missing dict keys
          are created automatically; list indices are never extended, so the target item
          must already exist.
        </p>
        <p>
          Required for Update. Ignored for Write. Optional for Append — an empty path
          merges the resolved value&apos;s own top-level keys directly into the document
          root (the resolved value must be a JSON object in that case).
        </p>
      </HelpSection>

      <HelpSection title="Per-device values in path">
        <p>
          Wrap an attribute path in braces to fill part of <HelpCode>path</HelpCode> from
          each device — typically the value that picks a list item. Define the attribute
          once, then reuse it here and later when rendering a template. For example, with
          an attribute <HelpCode>custom.tacacs_server</HelpCode> set by an{" "}
          <span className="font-medium text-foreground">Update Attribute</span> step:
        </p>
        <HelpExample>{`path: tacacs[server={custom.tacacs_server}].key

device A (custom.tacacs_server = "tacacs-server")
  -> tacacs[server=tacacs-server].key`}</HelpExample>
        <p>
          The same attribute can feed a template, e.g.{" "}
          <HelpCode>{"{{ custom.tacacs_server }}"}</HelpCode>, so the config context and
          the rendered config always agree. Use{" "}
          <span className="font-medium text-foreground">Browse attributes</span> to find
          the attribute name.
        </p>
        <HelpWarning title="An unresolved placeholder fails the device">
          <p>
            If the attribute is missing or empty for a device, that device fails and
            nothing is written — an empty value could otherwise select the wrong list item.
            The resolved value may not contain <HelpCode>[</HelpCode> or{" "}
            <HelpCode>]</HelpCode>. Placeholders need a workflow device, so they don&apos;t
            work with an explicit device identifier.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Copy key from global config context if missing locally">
        <p>
          A device&apos;s config context has two parts in Nautobot: the{" "}
          <span className="font-medium text-foreground">global</span> context (
          <HelpCode>config_context</HelpCode>, merged from assigned contexts such as a
          location) and the device&apos;s own{" "}
          <span className="font-medium text-foreground">local</span> context (
          <HelpCode>local_config_context_data</HelpCode>, often empty). This step can only
          write the local one — the global context cannot be changed from here.
        </p>
        <p>
          With this option on (Update, or Append with a path), the step checks whether the
          local context contains the first key of <HelpCode>path</HelpCode> (for{" "}
          <HelpCode>tacacs[address=1.2.3.4].key</HelpCode> that is{" "}
          <HelpCode>tacacs</HelpCode>). If not, it copies that key and its whole value from
          the global context into the local one, applies your change, and writes both in a
          single request. Other keys in the global context are not copied, and any keys the
          local context already has are kept. If the local context already has the key, it is
          updated in place and nothing is copied.
        </p>
        <HelpWarning title="The device keeps its own copy">
          <p>
            After the copy, later changes to that key in the global context no longer reach
            this device — its local value wins. Leave this option off to get an error instead
            of creating a local copy.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="value_source">
        <p>Where the new value comes from:</p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">Device attribute</span> — a
            dotted attribute path (same syntax as other steps), for example{" "}
            <HelpCode>tacacs.shared_secret</HelpCode> after a{" "}
            <span className="font-medium text-foreground">Secret Generate</span> or{" "}
            <span className="font-medium text-foreground">Generate Password</span> step,
            or <HelpCode>custom_fields.tacacs_key</HelpCode> from Nautobot itself. Use{" "}
            <span className="font-medium text-foreground">Browse attributes</span> to pick
            from what earlier steps produced.
          </li>
          <li>
            <span className="font-medium text-foreground">Rendered template</span> — a
            stored Jinja2 template, rendered once per device the same way{" "}
            <span className="font-medium text-foreground">Render Jinja Template</span>{" "}
            does. If the rendered text parses as JSON it is used as that value (an
            object, array, number, or boolean); otherwise the raw rendered text is used
            as a plain string.
          </li>
        </ul>
        <HelpWarning title="Write mode needs a JSON object">
          <p>
            For mode <HelpCode>write</HelpCode>, the resolved value must be a JSON object
            — a template that renders a single key or a plain string will fail that
            device with a configuration error.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the device
            resolved in Nautobot and its local config context was written.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — the device
            could not be resolved in Nautobot, the value source could not be resolved, or
            the path/value combination was invalid for the chosen mode (for example an
            out-of-range list index, or a non-object value in write mode).
          </li>
        </ul>
      </HelpSection>
    </div>
  );
}
