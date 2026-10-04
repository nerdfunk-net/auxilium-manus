"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Get from DB.
 * Covers every Configuration control with practical examples.
 */
export function GetFromDbHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads data previously saved by the Store in DB step and writes it into a
          device attribute, so later steps (routing, templates, compare) can use it.
          Records are looked up per device by device name and storage key (table{" "}
          <HelpCode>device_data_records</HelpCode>).
        </p>
      </HelpSection>

      <HelpSection title="storage_key">
        <p>
          The key the data was stored under. It must match the{" "}
          <HelpCode>storage_key</HelpCode> used in Store in DB.
        </p>
        <HelpExample>storage_key: site_backup</HelpExample>
      </HelpSection>

      <HelpSection title="destination_path">
        <p>
          Dot path (<HelpCode>bag.field</HelpCode>) the stored value is written to. The
          value keeps its stored shape — a string stays a string, a dictionary becomes
          a nested attribute. An existing value at the path is overwritten. Use{" "}
          <span className="font-medium text-foreground">Browse attributes</span> to
          pick a path from the workflow&apos;s most recent run.
        </p>
        <HelpExample>
          destination_path: stored.site_backup
          <br />
          (read later as stored.site_backup.nautobot.role.name)
        </HelpExample>
      </HelpSection>

      <HelpWarning title="Missing records fail the device">
        <p>
          A device with no stored record under the storage key is marked failed and
          follows the <HelpCode>failure</HelpCode> outcome; devices with a record
          continue on <HelpCode>success</HelpCode>. The destination cannot be{" "}
          <HelpCode>parsed.*</HelpCode> or <HelpCode>run_input.*</HelpCode> — those
          namespaces are reserved for the workflow engine.
        </p>
      </HelpWarning>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            In one workflow, use Store in DB with a <HelpCode>storage_key</HelpCode>.
          </li>
          <li>
            In a later run or workflow, add Get from DB with the same key and a{" "}
            <HelpCode>destination_path</HelpCode>.
          </li>
          <li>
            Route the <HelpCode>failure</HelpCode> outcome to handle devices that have
            nothing stored yet.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
