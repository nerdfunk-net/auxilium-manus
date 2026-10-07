"use client";

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
export function GetGitDevicesHelpPanel() {
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

      <HelpSection title="Git repository">
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Configure Repository</span>{" "}
          (or Edit Repository) and choose a repository created under Settings → Git
          Repositories. The step stores that repository&apos;s numeric ID as{" "}
          <HelpCode>git_repository_id</HelpCode>.
        </p>
        <p>
          Clone URL, branch, credentials, and optional directory are resolved from
          the repository configuration at preview and run time.
        </p>
        <HelpExample>
          git_repository_id: 3
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
          <HelpCode>device_mapping</HelpCode> maps keys of each device entry in
          the file to Nautobot attributes. Click{" "}
          <span className="font-medium text-foreground">Configure Mapping</span>,
          add a row per key, type the file key (nested keys as{" "}
          <HelpCode>parent.child</HelpCode>) and pick the Nautobot attribute from
          the list. <span className="font-medium text-foreground">Load keys from
          repository</span> suggests the keys found in your files.
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            A key must be mapped to <HelpCode>Device name</HelpCode>; entries
            without a value for it are skipped.
          </li>
          <li>
            Mapped values are available downstream as{" "}
            <HelpCode>{"{nautobot.location.name}"}</HelpCode>,{" "}
            <HelpCode>{"{nautobot.status.name}"}</HelpCode>, … The raw entry stays
            available as <HelpCode>{"{git.<key>}"}</HelpCode>.
          </li>
          <li>
            Device name, primary IPv4 address, platform and network driver also
            set the device itself (used for SSH).
          </li>
          <li>
            Each Nautobot attribute can be mapped once; internal IDs cannot be
            mapped.
          </li>
        </ul>
        <p>
          With no mapping configured, the default reads{" "}
          <HelpCode>name</HelpCode>, <HelpCode>primary_ip4</HelpCode> and{" "}
          <HelpCode>network_driver</HelpCode>.
        </p>
        <HelpExample>
          # mapping: device_name → Device name, site → Location
          <br />
          devices:
          <br />
          {"  "}- device_name: router1
          <br />
          {"    "}site: City A
        </HelpExample>
      </HelpSection>

      <HelpSection title="Show Preview">
        <p>
          <span className="font-medium text-foreground">Show Preview</span>{" "}
          clones or refreshes the repo, applies the filename pattern, parses
          matching YAML files, and lists discovered devices before you save or
          run the workflow. The button stays disabled until both{" "}
          <HelpCode>git_repository_id</HelpCode> and a non-empty{" "}
          <HelpCode>filename_pattern</HelpCode> are set.
        </p>
        <p>
          Preview is read-only — it does not change the workflow context. Use it
          to confirm file paths and the mapped fields before a long run.
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
