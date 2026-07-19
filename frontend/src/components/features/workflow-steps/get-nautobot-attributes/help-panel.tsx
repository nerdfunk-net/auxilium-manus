"use client";

import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Get Nautobot Attributes.
 * Covers every Configuration control with practical examples.
 */
export function GetNautobotAttributesHelpPanel(_props: PluginConfigPanelProps) {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Enriches each workflow device with data from Nautobot — interfaces,
          custom fields, tags, config context, secret groups, and hardware ports.
          Use after an inventory step so devices already have a Nautobot identity
          (name or ID) to query against.
        </p>
        <p>
          Selected attribute groups are fetched per device and merged into the
          device context for downstream steps (Route on Attribute, Update
          Attribute, Render Jinja Template, etc.).
        </p>
      </HelpSection>

      <HelpSection title="Nautobot source">
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Configure Source</span>{" "}
          (or Edit Source) and choose a source created under Settings → Sources
          → Nautobot. The step stores that source&apos;s ID as{" "}
          <HelpCode>nautobot_source_id</HelpCode>.
        </p>
        <p>
          Credentials (URL + token) are resolved from settings at run time — they
          are not pasted into the step config.
        </p>
        <HelpExample>
          nautobot_source_id: prod-lab
          <br />
          <span className="text-muted-foreground">
            → resolves to https://nautobot.example.com with the stored token
          </span>
        </HelpExample>
        <HelpWarning title="Source required">
          <p>
            Without a valid source the step cannot query Nautobot. If the ID is
            missing from Settings, the Configuration panel shows &quot;Source not
            found in settings&quot;.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Attribute groups">
        <p>
          <HelpCode>list_of_attributes</HelpCode> selects which Nautobot data
          to pull for each device. Click{" "}
          <span className="font-medium text-foreground">Edit Attributes</span>{" "}
          to open the picker and toggle groups on or off. At least one group
          should be selected.
        </p>

        <p className="font-medium text-foreground">Available groups:</p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>interfaces</HelpCode> — all interfaces on the device
            (name, type, enabled, IP assignments, etc.).
          </li>
          <li>
            <HelpCode>custom_fields</HelpCode> — Nautobot custom field values
            defined on the device model.
          </li>
          <li>
            <HelpCode>tags</HelpCode> — tags assigned to the device.
          </li>
          <li>
            <HelpCode>config_context</HelpCode> — merged config context data
            (structured JSON from Nautobot context sources).
          </li>
          <li>
            <HelpCode>secret_groups</HelpCode> — secret group associations and
            resolved secret metadata (not plaintext secrets unless your Nautobot
            setup exposes them).
          </li>
          <li>
            <HelpCode>console_ports</HelpCode> — console ports and console server
            ports.
          </li>
          <li>
            <HelpCode>power_ports</HelpCode> — power ports and power outlets.
          </li>
        </ul>

        <HelpExample>
          list_of_attributes:
          <br />
          {"  "}- interfaces
          <br />
          {"  "}- custom_fields
          <br />
          {"  "}- tags
        </HelpExample>

        <HelpWarning title="Select only what you need">
          <p>
            Each group adds API calls per device. For large inventories, limit
            groups to those downstream steps actually consume — e.g. skip{" "}
            <HelpCode>power_ports</HelpCode> if you only need custom fields for
            routing.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — Nautobot
            queries completed. Fetched attributes are on each device context.
            Devices not found in Nautobot may be marked failed per device.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — the
            step could not run (missing source, bad credentials, no attribute
            groups selected, or an unexpected error).
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Configure a Nautobot source.</li>
          <li>
            Place after Get from Nautobot or another step that sets device
            identity from Nautobot.
          </li>
          <li>
            Edit Attributes and enable the groups your workflow needs (often{" "}
            <HelpCode>custom_fields</HelpCode> and{" "}
            <HelpCode>interfaces</HelpCode>).
          </li>
          <li>
            Chain Route on Attribute or Update Attribute to branch or write
            based on the enriched data.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
