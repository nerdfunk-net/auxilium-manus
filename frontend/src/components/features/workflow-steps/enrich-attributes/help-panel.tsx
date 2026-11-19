"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Enrich Attributes.
 */
export function EnrichAttributesHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads a CSV lookup file from the local export directory or a Git repository. One column
          (<HelpCode>key_column</HelpCode>) identifies the device. A device is matched when its
          own attribute <HelpCode>device_attribute_path</HelpCode> equals (or contains) the key of
          a row. The other columns of that row are added to the device&apos;s attribute bag at{" "}
          <HelpCode>destination_path</HelpCode>.
        </p>
        <HelpExample>
          file (delimiter ;):
          <br />
          serial;data
          <br />
          131184641;example data
          <br />
          <br />
          key_column: serial
          <br />
          device_attribute_path: nautobot.serial
          <br />
          destination_path: inventory
          <br />
          <span className="text-muted-foreground">
            → device with serial 131184641 gets {"{{ inventory.data }}"} = example data
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Source, path and delimiter">
        <p>
          <HelpCode>source</HelpCode> is the export directory (<HelpCode>filesystem</HelpCode>)
          or a Git repository, refreshed before reading. <HelpCode>path</HelpCode> is one fixed
          relative path and stays inside the root. The first row is the header; values are
          trimmed text. <HelpCode>delimiter</HelpCode> defaults to <HelpCode>;</HelpCode> and can
          be any single character or <HelpCode>tab</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Matching">
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">Match</span> — the device value must
            equal the key.
          </li>
          <li>
            <span className="font-medium text-foreground">Contains</span> — the device value must
            contain the key (an empty key never matches).
          </li>
          <li>
            <HelpCode>case_insensitive</HelpCode> ignores upper/lower case in both modes.
          </li>
        </ul>
        <HelpWarning title="Several matching rows">
          <p>
            The first matching row in file order is used; the others are ignored. In{" "}
            <HelpCode>contains</HelpCode> mode a short key earlier in the file therefore beats a
            longer one, so order the file accordingly. Duplicate keys in{" "}
            <HelpCode>match</HelpCode> mode log one warning for the file.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Destination path and overwrite">
        <p>
          Every column except the key column becomes <HelpCode>destination_path.&lt;column&gt;</HelpCode>
          . The key column itself is not copied. With <HelpCode>overwrite</HelpCode> off
          (default) existing keys are kept; on, the file value wins. Empty cells are skipped. A column
          is never written onto a sealed (encrypted) attribute: that device takes the{" "}
          <HelpCode>failure</HelpCode> outcome.
        </p>
        <p>
          <HelpCode>parsed</HelpCode> and <HelpCode>run_input</HelpCode> and{" "}
          <HelpCode>device.*</HelpCode> scalar fields cannot be a destination.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — every device,
            including devices with no matching row or no value at the device path (left
            unchanged).
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — per device, only if
            merging into that device&apos;s bag raised.
          </li>
        </ul>
        <p>
          The <span className="font-medium text-foreground">whole step node fails</span> when the
          file is missing, cannot be read as CSV, or has no header column named{" "}
          <HelpCode>key_column</HelpCode> (or a column name appears twice).
        </p>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Get Nautobot Attributes — selects the devices and reads their serial numbers.</li>
          <li>
            Enrich Attributes — <HelpCode>key_column: serial</HelpCode>,{" "}
            <HelpCode>device_attribute_path: nautobot.serial</HelpCode>.
          </li>
          <li>
            Render Jinja Template or Log Attributes — use <HelpCode>inventory.data</HelpCode>.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
