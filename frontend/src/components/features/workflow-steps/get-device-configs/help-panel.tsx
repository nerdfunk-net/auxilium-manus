"use client";

import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Get Device Configs.
 * Covers every Configuration control with practical examples.
 */
export function GetDeviceConfigsHelpPanel(_props: PluginConfigPanelProps) {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Connects to each workflow device over SSH (via Netmiko) and retrieves
          running and/or startup configuration text. Output is stored as
          artifacts and referenced on the device context for downstream steps
          such as Compare Data, Store Artifact, or Render Jinja Template.
        </p>
        <p>
          Place after an inventory selector (Get from Nautobot, Get from List,
          etc.) so devices have a reachable management IP and platform driver.
        </p>
      </HelpSection>

      <HelpSection title="Credential reference">
        <p>
          <HelpCode>credential_reference</HelpCode> selects an SSH credential
          from Settings → Credentials. Only active, non-expired SSH credentials
          appear in the dropdown. The value stored is the credential{" "}
          <span className="font-medium text-foreground">name</span>, not its
          internal ID.
        </p>
        <HelpExample>
          credential_reference: network-admin-ssh
          <br />
          <span className="text-muted-foreground">
            → username/password or key from that credential record
          </span>
        </HelpExample>
        <HelpWarning title="SSH credential required">
          <p>
            Without a credential the step cannot connect. If no SSH credentials
            exist, the Configuration panel shows &quot;No SSH credentials in
            Settings → Credentials&quot;.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Config format">
        <p>
          <HelpCode>config_format</HelpCode> controls which configurations are
          fetched from the device:
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">
              Running and startup
            </span>{" "}
            — <HelpCode>config_format: both</HelpCode> (default). Fetches both
            when the platform supports it.
          </li>
          <li>
            <span className="font-medium text-foreground">Running only</span> —
            <HelpCode>config_format: running</HelpCode>. Current active
            configuration.
          </li>
          <li>
            <span className="font-medium text-foreground">Startup only</span> —
            <HelpCode>config_format: startup</HelpCode>. Saved startup
            configuration (where applicable).
          </li>
        </ul>
        <HelpExample>
          config_format: both
        </HelpExample>
      </HelpSection>

      <HelpSection title="Output">
        <p>
          Successful fetches produce artifact content and set references on each
          device:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>running_config</HelpCode> /{" "}
            <HelpCode>running_config_ref</HelpCode> — when running config was
            requested and returned
          </li>
          <li>
            <HelpCode>startup_config</HelpCode> /{" "}
            <HelpCode>startup_config_ref</HelpCode> — when startup config was
            requested and returned
          </li>
        </ul>
        <p>
          Downstream steps can read the inline content or follow the artifact
          reference depending on size and step type.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — SSH
            session completed for the device. Individual config types may still
            be empty if the platform does not expose them.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — per
            device when SSH fails (bad credentials, unreachable host, unsupported
            command). Check run logs for the specific device error.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Create an SSH credential in Settings → Credentials with access to
            your network devices.
          </li>
          <li>
            After an inventory step, select that credential and choose{" "}
            <HelpCode>both</HelpCode> for backups or <HelpCode>running</HelpCode>{" "}
            for drift checks only.
          </li>
          <li>
            Chain Store Artifact or Compare Data to persist or diff the
            retrieved configs.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
