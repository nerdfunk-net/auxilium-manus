"use client";

import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Get ISE TACACS Key.
 * Covers every Configuration control with practical examples.
 */
export function GetIseTacacsKeyHelpPanel(_props: PluginConfigPanelProps) {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Looks up each workflow device&apos;s TACACS+ shared secret in Cisco
          ISE and stores it in the device context as{" "}
          <HelpCode>tacacs.shared_secret</HelpCode>. Devices that already carry
          the key (e.g. from Get from ISE) are left untouched.
        </p>
        <p>
          Place this step after an inventory selector (Get from Nautobot, Get
          from List, etc.) and before steps that need the secret on the device
          or in ISE.
        </p>
      </HelpSection>

      <HelpSection title="ISE source">
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Configure Source</span>{" "}
          (or Edit Source) and choose a source created under Settings → Sources
          → Cisco ISE. The step stores that source&apos;s ID as{" "}
          <HelpCode>ise_source_id</HelpCode>.
        </p>
        <HelpExample>
          ise_source_id: prod-ise
        </HelpExample>
        <HelpWarning title="Source required">
          <p>
            Without a valid source the step cannot connect to ISE. A pre-flight
            connection failure emits a step-level <HelpCode>failure</HelpCode>{" "}
            outcome.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Priority tiers">
        <p>
          <HelpCode>priority</HelpCode> is an ordered list of lookup strategies.
          The step tries each <span className="font-medium text-foreground">enabled</span>{" "}
          tier top to bottom until one finds a TACACS+ key for the device.
        </p>
        <p>
          Use the toggle on each tier to enable or disable it. Use the up/down
          arrows to reorder tiers — order matters. At least one tier must stay
          enabled.
        </p>

        <p className="font-medium text-foreground">Available tiers:</p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>name_exact_32</HelpCode> — look up the device by name in
            ISE; only accept the match if its configured netmask is exactly{" "}
            <HelpCode>/32</HelpCode>.
          </li>
          <li>
            <HelpCode>name_any</HelpCode> — look up the device by name in ISE;
            accept any configured netmask.
          </li>
          <li>
            <HelpCode>location_group</HelpCode> — build an ISE Location group
            name from the device&apos;s Nautobot location and look up devices in
            that group (see <HelpCode>location_group_prefix</HelpCode> below).
          </li>
          <li>
            <HelpCode>ip_prefix_scan</HelpCode> — match the device&apos;s primary
            IPv4 against ISE entries, narrowing the netmask from{" "}
            <HelpCode>/32</HelpCode> down to <HelpCode>/8</HelpCode>. Cheap, but
            only finds entries stored as a clean CIDR network address.
          </li>
          <li>
            <HelpCode>ip_range_scan</HelpCode> — fallback for ISE entries stored
            as a range (e.g. <HelpCode>192.168.178.1-254</HelpCode>) or wildcard
            (e.g. <HelpCode>192.168.178.*</HelpCode>). Scans the full device
            inventory client-side.
          </li>
        </ul>

        <HelpExample>
          priority:
          <br />
          {"  "}- type: name_exact_32, enabled: true
          <br />
          {"  "}- type: name_any, enabled: true
          <br />
          {"  "}- type: location_group, enabled: true
          <br />
          {"  "}- type: ip_prefix_scan, enabled: true
          <br />
          {"  "}- type: ip_range_scan, enabled: true
        </HelpExample>

        <HelpWarning title="Keep ip_range_scan last">
          <p>
            <HelpCode>ip_range_scan</HelpCode> fetches every ISE network device
            and checks containment client-side — it is the most expensive tier.
            Leave it enabled as a fallback, but place it after cheaper tiers and
            disable it if your ISE entries are always clean CIDR or /32 names.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Location group prefix">
        <p>
          Shown when the <HelpCode>location_group</HelpCode> tier is enabled.
          <HelpCode>location_group_prefix</HelpCode> is the ISE Location NDG
          segment after the built-in root. Default:{" "}
          <HelpCode>All Locations</HelpCode>.
        </p>
        <p>
          The step builds the full group name as{" "}
          <HelpCode>
            {"Location#{location_group_prefix}#{nautobot location name}"}
          </HelpCode>
          , then looks up TACACS keys from devices in that ISE group.
        </p>
        <HelpExample>
          location_group_prefix: All Locations
          <br />
          <span className="text-muted-foreground">
            → Location#All Locations#Building1 for a device in Nautobot location
            Building1
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            step finished. Devices where a key was found have{" "}
            <HelpCode>tacacs.shared_secret</HelpCode> set. Devices where no
            enabled tier found a key are marked failed on that device, but the
            step itself still succeeds so downstream steps can proceed with
            survivors.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — ISE
            could not be reached or authentication failed (a condition affecting
            every device equally). Per-device misses do{" "}
            <span className="font-medium text-foreground">not</span> cause step
            failure.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Configure a Cisco ISE source.</li>
          <li>
            Order tiers to match how your ISE entries are stored — usually name
            lookups first, then location group, then IP scans.
          </li>
          <li>
            Keep <HelpCode>ip_range_scan</HelpCode> last (or disabled) unless
            you need range/wildcard notation support.
          </li>
          <li>
            Run after an inventory step; route failed devices separately if
            needed.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
