"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Read Config.
 * Covers every Configuration control with practical examples.
 */
export function ReadConfigHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads a configuration file from disk or a Git source — located per device by{" "}
          <HelpCode>path_template</HelpCode> — and sets it as the device&apos;s running
          configuration, exactly as if an upstream Get Configs step had fetched it live.
          Downstream steps (Store Artifact, Upload Config, Configure Replace Config, Compare
          Data, …) consume it the same way either way.
        </p>
        <p>
          Built for the &quot;device is dead but I have a backup&quot; scenario: a device fails
          and has no reachable running config of its own, but a config saved earlier (e.g. by
          Store Artifact) still exists. Place after an inventory selector so devices have a
          name/hostname to resolve the path template against.
        </p>
      </HelpSection>

      <HelpSection title="Source">
        <p>
          <HelpCode>source</HelpCode> chooses where the file lives:
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">Filesystem</span> —{" "}
            <HelpCode>source: filesystem</HelpCode>. Reads relative to the default export
            directory (Settings → General). This is a fixed, non-run-scoped root, unlike Store
            Artifact&apos;s filesystem writes, so a file saved once can be found again without
            knowing which run wrote it.
          </li>
          <li>
            <span className="font-medium text-foreground">Git repository</span> —{" "}
            <HelpCode>source: git</HelpCode>. Reads from a git source configured under Settings →
            Sources, selected via <HelpCode>git_repository_id</HelpCode>. The repository is always
            refreshed (cloned or pulled) before reading, so the latest committed content is used.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Path template">
        <p>
          <HelpCode>path_template</HelpCode> is the relative file path to read, resolved per
          device. It supports the same device-attribute placeholders as Store Artifact&apos;s
          filename template, and may include subdirectories.
        </p>
        <HelpExample>
          path_template: {"{device.name}"}.cfg
          <br />
          <span className="text-muted-foreground">→ reads router1.cfg</span>
        </HelpExample>
        <HelpExample>
          path_template: {"{nautobot.location.name}"}/{"{device.name}"}.cfg
          <br />
          <span className="text-muted-foreground">→ reads DC1/router1.cfg</span>
        </HelpExample>
        <HelpWarning title="Placeholders must resolve">
          <p>
            A <HelpCode>{"{nautobot.*}"}</HelpCode> or <HelpCode>{"{git.*}"}</HelpCode>{" "}
            placeholder that resolves empty (e.g. no upstream Get Nautobot Attributes step) fails
            that device rather than silently reading the wrong file — pick a template that only
            uses attributes every device in this run actually has.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Overwrite existing">
        <p>
          <HelpCode>overwrite_existing</HelpCode> is the only behavioral toggle:
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">Off (default)</span> — a device that
            already has a running config in this run (e.g. a Get Configs step upstream
            succeeded) is left untouched; Read Config does nothing for it. This makes it safe to
            place Read Config as a fallback after a live fetch, so the backup is only used when
            the device truly couldn&apos;t be reached.
          </li>
          <li>
            <span className="font-medium text-foreground">On</span> — always reads the file and
            replaces whatever running config the device already has.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Output">
        <p>
          A successful read produces the same output as Get Configs:{" "}
          <HelpCode>running_config</HelpCode> / <HelpCode>running_config_ref</HelpCode> on the
          device context.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the file was read (or
            the device already had a running config and was left unchanged).
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — per device when the
            file doesn&apos;t exist at the resolved path, or a placeholder in{" "}
            <HelpCode>path_template</HelpCode> couldn&apos;t be resolved.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            A scheduled workflow runs Get Configs → Store Artifact (git,{" "}
            <HelpCode>filename_template: {"{device.name}"}.cfg</HelpCode>) nightly, backing up
            every device&apos;s running config to a git source.
          </li>
          <li>
            When a device dies, target its replacement with an inventory step, then add Read
            Config (git, the same <HelpCode>path_template</HelpCode> as the backup job used) to
            load its last known-good config.
          </li>
          <li>
            Chain Upload Config → Configure Replace Config to push that config onto the
            replacement device.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
