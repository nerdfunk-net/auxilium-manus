"use client";

import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import {
  FanOutHelpSection,
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Get from Git.
 * Covers every Configuration control with practical examples.
 */
export function GetGitDevicesHelpPanel(_props: PluginConfigPanelProps) {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads device definitions from YAML files in a Git repository and adds
          them to the workflow context. Use when your source of truth for device
          inventory lives in Git (e.g. NetBox-style YAML exports, Ansible
          inventory files, or hand-maintained device manifests).
        </p>
        <p>
          Downstream steps receive device identity fields mapped from each YAML
          entry (name, primary IP, network driver by default).
        </p>
      </HelpSection>

      <HelpSection title="Git source">
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Configure Source</span>{" "}
          (or Edit Source) and choose a source created under Settings → Sources
          → Git. The step stores that source&apos;s ID as{" "}
          <HelpCode>git_source_id</HelpCode> (normalised to lowercase).
        </p>
        <p>
          Clone URL, branch, credentials, and optional subdirectory are resolved
          from settings at preview and run time.
        </p>
        <HelpExample>
          git_source_id: device-inventory
        </HelpExample>
        <HelpWarning title="Source required">
          <p>
            Without a valid Git source the step cannot clone or read files.
            Show Preview stays disabled until a source and filename pattern are
            configured.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Filename pattern">
        <p>
          <HelpCode>filename_pattern</HelpCode> is a glob pattern relative to
          the repository root (or the source&apos;s configured subdirectory).
          Only files matching the pattern are scanned for device entries.
        </p>
        <HelpExample>
          filename_pattern: *.yaml
          <br />
          filename_pattern: configs/*.yaml
          <br />
          filename_pattern: sites/lab/devices/*.yml
        </HelpExample>
        <p>
          Default if unset: <HelpCode>*.yaml</HelpCode>. Use a narrower pattern
          when the repo contains non-device YAML you want to skip.
        </p>
      </HelpSection>

      <HelpSection title="Device mapping">
        <p>
          <HelpCode>device_mapping</HelpCode> controls how YAML keys map to
          workflow device fields. Click{" "}
          <span className="font-medium text-foreground">Configure Mapping</span>{" "}
          to review or customise mappings (UI coming in a future release).
        </p>
        <p>
          Until custom mapping is available, the default reads these keys from
          each device entry in the YAML file:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>name</HelpCode> — device hostname
          </li>
          <li>
            <HelpCode>primary_ip4</HelpCode> — management IPv4
          </li>
          <li>
            <HelpCode>network_driver</HelpCode> — Netmiko / platform driver
          </li>
        </ul>
        <HelpExample>
          # configs/router1.yaml
          <br />
          name: router1
          <br />
          primary_ip4: 10.0.0.1
          <br />
          network_driver: cisco_ios
        </HelpExample>
      </HelpSection>

      <HelpSection title="Show Preview">
        <p>
          <span className="font-medium text-foreground">Show Preview</span>{" "}
          clones or refreshes the repo, applies the filename pattern, parses
          matching YAML files, and lists discovered devices before you save or
          run the workflow. The button stays disabled until both{" "}
          <HelpCode>git_source_id</HelpCode> and a non-empty{" "}
          <HelpCode>filename_pattern</HelpCode> are set.
        </p>
        <p>
          Preview is read-only — it does not change the workflow context. Use it
          to confirm file paths and field mapping before a long run.
        </p>
      </HelpSection>

      <FanOutHelpSection />

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — YAML
            files were read and devices (including zero matches) were added to
            context.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — Git
            clone/pull failed, the source is missing, or parsing hit an
            unexpected error.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Configure a Git source pointing at your device inventory repo.</li>
          <li>
            Set <HelpCode>filename_pattern</HelpCode> to match your YAML layout
            (e.g. <HelpCode>configs/*.yaml</HelpCode>).
          </li>
          <li>Preview the device list, then enable fan-out if needed.</li>
          <li>
            Add Fan In before any git-push or store-artifact step on a fanned-out
            branch.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
