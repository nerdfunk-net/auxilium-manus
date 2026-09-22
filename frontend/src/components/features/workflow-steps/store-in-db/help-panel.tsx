"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Store in DB.
 * Covers every Configuration control with practical examples.
 */
export function StoreInDbHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Persists device data to the application database, keyed by device name and
          a storage key you choose. A later{" "}
          <span className="font-medium text-foreground">Read from DB</span> step
          retrieves it and overwrites device data with it — this is how you hand data
          from one run (or workflow) to a future one.
        </p>
      </HelpSection>

      <HelpSection title="storage_key">
        <p>
          Name for this stored item, unique per device. Storing again under the same{" "}
          <HelpCode>storage_key</HelpCode> for the same device overwrites it; a
          different key leaves earlier stored data for that device untouched, so one
          device can hold several independent items (e.g. a backup and a site id).
        </p>
        <HelpExample>
          storage_key: site_backup
          <br />
          content_source: device_data
        </HelpExample>
      </HelpSection>

      <HelpSection title="content_source">
        <p>
          What to store for each device. Stored as <HelpCode>content_source</HelpCode>.
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>device_data</HelpCode> — all attribute bags plus parsed output
            (everything the device has accumulated so far).
          </li>
          <li>
            <HelpCode>attribute_bags</HelpCode> — all namespaced attribute bags only
            (e.g. <HelpCode>nautobot</HelpCode>, <HelpCode>git</HelpCode>), not parsed
            command/template output.
          </li>
          <li>
            <HelpCode>single_attribute</HelpCode> — one resolved attribute path (pick{" "}
            <HelpCode>attribute_path</HelpCode>).
          </li>
          <li>
            <HelpCode>rendered_template</HelpCode> — output from an upstream Render
            Jinja Template step (pick <HelpCode>source_step</HelpCode> and optional{" "}
            <HelpCode>parsed_output_key</HelpCode>).
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="attribute_path">
        <p>
          Shown when <HelpCode>content_source</HelpCode> is{" "}
          <HelpCode>single_attribute</HelpCode>. Dot path to the value to store — use{" "}
          <span className="font-medium text-foreground">Browse attributes</span> to
          pick a real path discovered from the workflow&apos;s most recent run.
        </p>
        <HelpExample>
          content_source: single_attribute
          <br />
          attribute_path: nautobot.role.name
        </HelpExample>
      </HelpSection>

      <HelpSection title="allow_secret_storage">
        <p>
          Shown when <HelpCode>content_source</HelpCode> is{" "}
          <HelpCode>single_attribute</HelpCode>. Off by default. When{" "}
          <HelpCode>attribute_path</HelpCode> resolves to a secret-valued attribute
          (e.g. a device password from Nautobot config context, or a TACACS+ key),
          the step fails that device instead of writing it — unless this checkbox is
          enabled, in which case the value is decrypted and stored as plain data.
        </p>
        <HelpExample>
          content_source: single_attribute
          <br />
          attribute_path: nautobot.config_context.credentials[level=15].password
          <br />
          allow_secret_storage: true
        </HelpExample>
      </HelpSection>

      <HelpSection title="source_step / parsed_output_key">
        <p>
          Shown when <HelpCode>content_source</HelpCode> is{" "}
          <HelpCode>rendered_template</HelpCode>. Select the upstream Render Jinja
          Template step that produced the content — stored as{" "}
          <HelpCode>source_step_node_id</HelpCode> (shown as{" "}
          <HelpCode>source_step</HelpCode>). If only one matching step exists it is
          selected automatically; use Advanced → enter node id manually when reusing
          an id from an older workflow.
        </p>
        <p>
          <HelpCode>parsed_output_key</HelpCode> is the render step&apos;s optional
          output key. Leave it empty to store every template the selected step
          produced, keyed by output key.
        </p>
        <HelpExample>
          content_source: rendered_template
          <br />
          source_step_node_id: render-jinja-template-1
          <br />
          parsed_output_key: device_config
        </HelpExample>
      </HelpSection>

      <HelpWarning title="Secret-valued attributes are refused by default">
        <p>
          If <HelpCode>attribute_path</HelpCode> resolves to a secret-valued attribute
          (e.g. <HelpCode>tacacs.shared_secret</HelpCode>), the step refuses to write
          it and fails that device — the database is not a protected secret store the
          way sealed in-run attribute bags are. Enable{" "}
          <HelpCode>allow_secret_storage</HelpCode> only when you specifically intend
          to persist that secret in plain, queryable form for a later step to reuse.
        </p>
      </HelpWarning>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Run an inventory step, and Get Nautobot Attributes if needed.</li>
          <li>
            Choose <HelpCode>content_source</HelpCode> and set{" "}
            <HelpCode>storage_key</HelpCode> to something you&apos;ll recognize in a
            later Read from DB step.
          </li>
          <li>
            Run the workflow once per device you want stored — rows are keyed by
            device name, so any device can be re-stored later without affecting
            others.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
