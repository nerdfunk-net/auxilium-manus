"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Read from File.
 * Covers every Configuration control with practical examples.
 */
export function ReadFromFileHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads a YAML or JSON file from the local export directory or a Git repository, parses
          it once, and deep-merges the resulting mapping into every device&apos;s attribute bag
          at <HelpCode>destination_path</HelpCode>. A later Render Jinja Template step then
          references the values, e.g. <HelpCode>{"{{ data.region }}"}</HelpCode>.
        </p>
        <p>
          Built for structured data that is shared across all target devices — site defaults, a
          region map, per-run parameters kept in a repo. Place it after an inventory selector so
          there are devices to enrich.
        </p>
      </HelpSection>

      <HelpSection title="Source">
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">Filesystem</span> —{" "}
            <HelpCode>source: filesystem</HelpCode>. Reads relative to the default export
            directory (Settings → General), a fixed non-run-scoped root.
          </li>
          <li>
            <span className="font-medium text-foreground">Git repository</span> —{" "}
            <HelpCode>source: git</HelpCode>, selected via <HelpCode>git_repository_id</HelpCode>.
            The repository is refreshed (cloned or pulled) before reading.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Path">
        <p>
          <HelpCode>path</HelpCode> is a single fixed relative path within the root. It is read
          once per run, not per device. Subdirectories are allowed; the resolved path must stay
          inside the root.
        </p>
        <HelpExample>path: data/site-defaults.yaml</HelpExample>
      </HelpSection>

      <HelpSection title="Format">
        <p>
          <HelpCode>format</HelpCode> is <HelpCode>yaml</HelpCode>, <HelpCode>json</HelpCode>, or{" "}
          <HelpCode>auto</HelpCode> (default). <HelpCode>auto</HelpCode> picks by file extension
          (<HelpCode>.json</HelpCode> / <HelpCode>.yaml</HelpCode> / <HelpCode>.yml</HelpCode>),
          otherwise tries JSON then YAML. Choose <HelpCode>json</HelpCode> explicitly for strict
          JSON parse errors.
        </p>
      </HelpSection>

      <HelpSection title="Destination path">
        <p>
          <HelpCode>destination_path</HelpCode> is <HelpCode>bag</HelpCode> or{" "}
          <HelpCode>bag.field</HelpCode> form. The first segment is the attribute bag name.
        </p>
        <HelpExample>
          destination_path: data.site
          <br />
          file: {"{ region: emea, dns: [1.1.1.1] }"}
          <br />
          <span className="text-muted-foreground">→ {"{{ data.site.dns[0] }}"} = 1.1.1.1</span>
        </HelpExample>
        <HelpWarning title="Reserved namespaces">
          <p>
            <HelpCode>parsed</HelpCode> and <HelpCode>run_input</HelpCode> are populated by the
            workflow engine and <HelpCode>device.*</HelpCode> scalar fields are read-only — none
            can be a merge destination.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Overwrite">
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">Off (default)</span> — existing keys
            at the destination are kept; only keys new to the file are added.
          </li>
          <li>
            <span className="font-medium text-foreground">On</span> — a file value wins on a key
            collision.
          </li>
        </ul>
        <p>Nested objects always merge key-by-key regardless of this toggle.</p>
        <HelpWarning title="Lists are replaced wholesale">
          <p>
            A list in the file replaces the list at the destination entirely — it is never
            concatenated or unioned. (Still subject to the overwrite toggle.)
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the file was merged
            into every device (or there were no devices).
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — per device, only if a
            merge into that device&apos;s bag raised.
          </li>
        </ul>
        <p>
          The <span className="font-medium text-foreground">whole step node fails</span> (not a
          per-device failure) when the file is missing, cannot be parsed, or does not parse to a
          mapping.
        </p>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Get from Nautobot / Get from List — select the target devices.</li>
          <li>
            Read from File — <HelpCode>path: data/site-defaults.yaml</HelpCode>,{" "}
            <HelpCode>destination_path: data</HelpCode>.
          </li>
          <li>
            Render Jinja Template — body references <HelpCode>{"{{ data.region }}"}</HelpCode>.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
