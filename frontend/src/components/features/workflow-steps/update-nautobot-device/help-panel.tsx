"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Update Nautobot Device.
 * Covers every Configuration control with practical examples.
 */
export function UpdateNautobotDeviceHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Updates an existing device record in Nautobot — core fields, custom fields,
          and optionally interfaces — using values from the workflow context or fixed
          literals. Place it after an inventory or attribute step so each device in
          context is patched in place.
        </p>
        <p>
          Configure a Nautobot source, open{" "}
          <span className="font-medium text-foreground">Edit Update</span> to define
          which fields change and how the target device is resolved, then save.
        </p>
      </HelpSection>

      <HelpSection title="Nautobot source">
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Configure Source</span>{" "}
          (or Edit Source) and choose a source from Settings → Sources → Nautobot.
          The step stores <HelpCode>nautobot_source_id</HelpCode>.
        </p>
        <p>
          Credentials (URL + token) are resolved from settings at run time — they are
          not pasted into the step config.
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
            Without a valid source the step cannot call the Nautobot API. If the ID
            is missing from Settings, the Configuration panel shows &quot;Source not
            found in settings&quot;.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Device identifier">
        <p>
          Open <span className="font-medium text-foreground">Edit Update</span> and
          set <HelpCode>device_identifier.mode</HelpCode>:
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">From workflow context</span>{" "}
            — <HelpCode>mode: from_context</HelpCode>. Uses each device already in
            the workflow (UUID or name from the upstream inventory step). Default for
            per-device fan-out workflows.
          </li>
          <li>
            <span className="font-medium text-foreground">Explicit UUID or name</span>{" "}
            — <HelpCode>mode: explicit</HelpCode>. Targets one device regardless of
            context. Set <HelpCode>device_identifier.id</HelpCode> (UUID) and/or{" "}
            <HelpCode>device_identifier.name</HelpCode> (name). UUID takes precedence
            when both are set.
          </li>
        </ul>
        <HelpExample>
          device_identifier:
          <br />
          {"  "}mode: from_context
          <br />
          <br />
          device_identifier:
          <br />
          {"  "}mode: explicit
          <br />
          {"  "}name: lab-switch-01
        </HelpExample>
      </HelpSection>

      <HelpSection title="Update fields">
        <p>
          In <span className="font-medium text-foreground">Edit Update</span>, enable
          only the fields you want to change. Disabled fields are not sent to Nautobot.
          Each enabled field has a <HelpCode>value</HelpCode> that can be:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            A fixed literal — e.g. <HelpCode>active</HelpCode>,{" "}
            <HelpCode>access-switch</HelpCode>
          </li>
          <li>
            A context path — e.g. <HelpCode>{"{nautobot.origin}"}</HelpCode>,{" "}
            <HelpCode>{"{custom.site}"}</HelpCode>
          </li>
          <li>
            A path with default — e.g.{" "}
            <HelpCode>{"{custom.serial | default('N/A')}"}</HelpCode>
          </li>
        </ul>
        <p className="font-medium text-foreground">Built-in fields:</p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>name</HelpCode> — device name (e.g.{" "}
            <HelpCode>cityA</HelpCode> or <HelpCode>{"{custom.name}"}</HelpCode>)
          </li>
          <li>
            <HelpCode>location</HelpCode> — Nautobot location (e.g.{" "}
            <HelpCode>{"{nautobot.origin}"}</HelpCode>)
          </li>
          <li>
            <HelpCode>serial</HelpCode> — serial number
          </li>
          <li>
            <HelpCode>role</HelpCode> — device role (e.g.{" "}
            <HelpCode>access-switch</HelpCode>)
          </li>
          <li>
            <HelpCode>status</HelpCode> — status slug (e.g.{" "}
            <HelpCode>active</HelpCode>)
          </li>
          <li>
            <HelpCode>device_type</HelpCode> — model (e.g.{" "}
            <HelpCode>C9300-24T</HelpCode>)
          </li>
          <li>
            <HelpCode>platform</HelpCode> — platform slug
          </li>
          <li>
            <HelpCode>software_version</HelpCode> — OS version (e.g.{" "}
            <HelpCode>17.9.1</HelpCode>)
          </li>
          <li>
            <HelpCode>tags</HelpCode> — comma-separated tags (e.g.{" "}
            <HelpCode>lab, prod</HelpCode> or <HelpCode>{"{custom.tags}"}</HelpCode>)
          </li>
        </ul>
        <HelpExample>
          update_fields:
          <br />
          {"  "}status:
          <br />
          {"    "}enabled: true
          <br />
          {"    "}value: active
          <br />
          {"  "}software_version:
          <br />
          {"    "}enabled: true
          <br />
          {"    "}value: {"{device.parsed.version}"}
        </HelpExample>
      </HelpSection>

      <HelpSection title="Custom fields">
        <p>
          Add rows under <HelpCode>custom_fields</HelpCode> in Edit Update. Each row
          has a Nautobot custom field name and a value (fixed or templated). Only
          enabled rows with a non-empty name are sent.
        </p>
        <HelpExample>
          custom_fields:
          <br />
          {"  "}deployment_site:
          <br />
          {"    "}enabled: true
          <br />
          {"    "}value: {"{custom.site | default('N/A')}"}
        </HelpExample>
      </HelpSection>

      <HelpSection title="Interfaces">
        <p>
          Optional interface create/update rows. Each interface supports:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>name</HelpCode> — interface name (required, e.g.{" "}
            <HelpCode>GigabitEthernet0/1</HelpCode>)
          </li>
          <li>
            <HelpCode>type</HelpCode> — Nautobot interface type (e.g.{" "}
            <HelpCode>1000base-t</HelpCode>)
          </li>
          <li>
            <HelpCode>status</HelpCode> — status slug (e.g.{" "}
            <HelpCode>active</HelpCode>)
          </li>
          <li>
            <HelpCode>ip_address</HelpCode> — address with prefix (e.g.{" "}
            <HelpCode>10.0.0.1/24</HelpCode> or{" "}
            <HelpCode>{"{device.primary_ip4}"}</HelpCode>)
          </li>
          <li>
            <HelpCode>description</HelpCode> — free-text description
          </li>
          <li>
            <HelpCode>is_primary_ipv4</HelpCode> — when on, marks this IP as the
            device primary IPv4 in Nautobot
          </li>
        </ul>
        <HelpExample>
          interfaces:
          <br />
          {"  "}- name: Management0
          <br />
          {"    "}type: 1000base-t
          <br />
          {"    "}status: active
          <br />
          {"    "}ip_address: 10.0.0.1/24
          <br />
          {"    "}is_primary_ipv4: true
        </HelpExample>
      </HelpSection>

      <HelpSection title="IP prefix options">
        <p>
          When assigning IP addresses to interfaces:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>add_prefix</HelpCode> — when on (default), bare host addresses
            get a prefix appended using <HelpCode>default_prefix_length</HelpCode>.
            Turn off if you always supply CIDR notation.
          </li>
          <li>
            <HelpCode>default_prefix_length</HelpCode> — suffix added to host-only
            values (default <HelpCode>/24</HelpCode>). Example:{" "}
            <HelpCode>10.0.0.1</HelpCode> becomes <HelpCode>10.0.0.1/24</HelpCode>.
          </li>
          <li>
            <HelpCode>sync_interfaces</HelpCode> — when on, reconciles Nautobot
            interfaces with the configured list (may remove interfaces not listed).
            Leave off for additive updates only.
          </li>
        </ul>
        <HelpExample>
          add_prefix: true
          <br />
          default_prefix_length: /24
          <br />
          sync_interfaces: false
        </HelpExample>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — Nautobot
            accepted the update for the device.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — missing
            source, unknown device, validation error, or API failure. Check run logs
            and verify field slugs match your Nautobot instance.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Configure a Nautobot source (Settings → Sources).</li>
          <li>
            Place after Get from Nautobot or another step that puts devices in context.
          </li>
          <li>
            Edit Update: leave device identifier on from_context, enable only the
            fields you need, use context paths where values come from upstream steps.
          </li>
          <li>
            Add interfaces only when you need IP or interface metadata synced back to
            Nautobot.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
