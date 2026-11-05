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
            <HelpCode>{"{custom.site}"}</HelpCode>. Click the search icon next to a
            field&apos;s value input to browse real attribute paths from the
            workflow&apos;s most recent run instead of typing one — selecting a
            path fills in the value and enables the field.
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
          {"    "}value: {"{parsed.version}"}
        </HelpExample>
      </HelpSection>

      <HelpSection title="Custom fields">
        <p>
          Add rows under <HelpCode>custom_fields</HelpCode> in Edit Update. Each row
          has a Nautobot custom field name and a value (fixed or templated) — the
          search icon next to the value input opens the same attribute browser.
          Only enabled rows with a non-empty name are sent.
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
          Interfaces have three sources, chosen by the <HelpCode>interfaces_source</HelpCode>{" "}
          dropdown above the rows:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">Manual</span> — a fixed list you
            type in advance. Each row supports:
            <ul className="list-disc space-y-1 py-1 pl-4">
              <li>
                <HelpCode>name</HelpCode> — interface name (required, e.g.{" "}
                <HelpCode>GigabitEthernet0/1</HelpCode>)
              </li>
              <li>
                <HelpCode>type</HelpCode> — Nautobot interface type (e.g.{" "}
                <HelpCode>1000base-t</HelpCode>)
              </li>
              <li>
                <HelpCode>status</HelpCode> — status slug (e.g. <HelpCode>active</HelpCode>)
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
              <li>
                <HelpCode>mac_address</HelpCode>, <HelpCode>port_type</HelpCode>,{" "}
                <HelpCode>mode</HelpCode> (access / tagged / tagged-all),{" "}
                <HelpCode>speed</HelpCode> (Kbps, or text such as <HelpCode>1 Gbit</HelpCode>),{" "}
                <HelpCode>duplex</HelpCode> (auto / full / half), <HelpCode>mtu</HelpCode> and{" "}
                <HelpCode>vrf</HelpCode> (must already exist in Nautobot). A MAC in the Cisco form{" "}
                <HelpCode>aabb.cc00.0100</HelpCode> is converted to{" "}
                <HelpCode>AA:BB:CC:00:01:00</HelpCode>.
              </li>
            </ul>
          </li>
          <li>
            <span className="font-medium text-foreground">All from Nautobot origin</span> —
            ignores the rows and updates every interface present in the device&apos;s nautobot
            attribute bag, each with however many IP addresses it actually has. Populate that
            bag upstream with a <span className="font-medium text-foreground">Config to
            Attributes</span> step (<HelpCode>source_format: genie</HelpCode> after a{" "}
            <span className="font-medium text-foreground">Get &amp; Parse Config</span> step,
            or <HelpCode>source_format: cisco_config_parser</HelpCode> after a{" "}
            <span className="font-medium text-foreground">Parse Cisco Config</span> step). An
            IOS <HelpCode>ip address ... secondary</HelpCode> line is carried through as an
            explicit Nautobot IP role of <HelpCode>secondary</HelpCode>. Not available when{" "}
            <HelpCode>device_identifier.mode</HelpCode> is <HelpCode>explicit</HelpCode> — that
            mode has no upstream device to read a bag from. To change single values (for
            example a MAC address) put them into the bag first with an{" "}
            <span className="font-medium text-foreground">Update Attribute</span> step whose{" "}
            <HelpCode>destination_path</HelpCode> selects the interface by name:{" "}
            <HelpCode>nautobot.interfaces[name=Ethernet0/0].mac_address</HelpCode>. The item is
            updated, or appended when the bag has no such interface. The name may be a
            placeholder, e.g. <HelpCode>{"nautobot.interfaces[name={custom.ifname}].mtu"}</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">From a parsed list</span> — updates
            one interface per row of a list on the device, for example the TextFSM output of{" "}
            <HelpCode>show interfaces</HelpCode>. Pick the list with{" "}
            <HelpCode>source path</HelpCode> (browse button), then name the column that holds
            each field (<HelpCode>interface</HelpCode> → name, <HelpCode>mac_address</HelpCode>{" "}
            → MAC address, …). <span className="font-medium text-foreground">Fixed values</span>{" "}
            apply to every row, existing interfaces included. Blank cells are skipped, so an
            existing Nautobot value is never wiped, and an existing interface needs no type.
            TextFSM output has no Nautobot interface type, so leave Type unmapped and use{" "}
            <span className="font-medium text-foreground">Type for new interfaces</span>{" "}
            (<HelpCode>new_interface_type</HelpCode>) instead: <HelpCode>Do not create</HelpCode>{" "}
            skips interfaces missing in Nautobot with a warning, <HelpCode>guessed from the
            interface name</HelpCode> creates them (<HelpCode>Ethernet…</HelpCode> →{" "}
            <HelpCode>1000base-t</HelpCode>, <HelpCode>Loopback…</HelpCode> →{" "}
            <HelpCode>virtual</HelpCode>, <HelpCode>Port-channel…</HelpCode> →{" "}
            <HelpCode>lag</HelpCode>, unknown → <HelpCode>other</HelpCode>), and{" "}
            <HelpCode>always with this type</HelpCode> creates them all with one type. The type
            is used only for interfaces that do not exist yet; an existing interface keeps its
            type. Not available when <HelpCode>device_identifier.mode</HelpCode> is{" "}
            <HelpCode>explicit</HelpCode>, and <HelpCode>sync_interfaces</HelpCode> is switched
            off for it: that option deletes every Nautobot interface missing from the list, so a
            list that is short for any reason would delete real interfaces.
          </li>
        </ul>
        <HelpWarning title="IP addresses are only touched when given">
          <p>
            An interface row that carries no IP address (for example a MAC-only update)
            leaves the interface&apos;s existing IP addresses alone. A row with an IP address
            still replaces the interface&apos;s IPs with the given ones.
          </p>
        </HelpWarning>
        <HelpExample>
          interfaces_source: parsed_list
          <br />
          parsed_list:
          <br />
          {"  "}source_path: parsed.show_interfaces.parsed
          <br />
          {"  "}field_map: {"{"} name: interface, mac_address: mac_address, mtu: mtu {"}"}
          <br />
          {"  "}new_interface_type: {"{"} mode: infer {"}"}
        </HelpExample>
        <HelpExample>
          interfaces_source: manual
          <br />
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

      <HelpSection title="Dry run">
        <p>
          When <HelpCode>dry_run</HelpCode> is on, the step does nothing — no Nautobot
          calls are made and no device or interface fields are changed. It only logs
          that dry run is enabled and reports success. Since nothing changes, the
          device&apos;s existing attribute bag already reflects its current settings,
          so there is no separate dry-run preview in the run&apos;s detail view.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — Nautobot
            accepted the update for the device (or, with <HelpCode>dry_run</HelpCode>{" "}
            on, the step was skipped without error).
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
