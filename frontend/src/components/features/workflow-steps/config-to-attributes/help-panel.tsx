"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Config to Attributes.
 * Covers every Configuration control with practical examples.
 */
export function ConfigToAttributesHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads a device&apos;s parsed config and populates its Nautobot attribute
          bag — purely in-memory, no Nautobot connection is made here. A later{" "}
          <span className="font-medium text-foreground">Add to Nautobot</span> or{" "}
          <span className="font-medium text-foreground">Update Device</span> step
          (with <HelpCode>interfaces_source: nautobot_origin</HelpCode>) can then
          create or update those interfaces for real.
        </p>
        <p>
          Currently supports one attribute group:{" "}
          <span className="font-medium text-foreground">Add Interfaces</span> —
          name, status, type, description, IP addresses (including secondaries,
          with an explicit Nautobot IP role), and enabled state. This step does
          not distinguish Layer&nbsp;2 from Layer&nbsp;3 interfaces — an
          interface is an interface, regardless of whether it carries an IP
          address, a switchport VLAN, or is a port-channel/LAG.
        </p>
      </HelpSection>

      <HelpSection title="Source format">
        <p>
          Which parser produced the config at <HelpCode>parsed.{"{parsed_key}"}</HelpCode>:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">Cisco Config Parser</span> —
            output from an upstream <span className="font-medium text-foreground">
            Parse Cisco Config</span> step (a flat, typed interface list).
          </li>
          <li>
            <span className="font-medium text-foreground">Genie (pyATS)</span> —
            output from an upstream <span className="font-medium text-foreground">
            Get &amp; Parse Config</span> step (Genie&apos;s raw parsed{" "}
            <HelpCode>show running-config</HelpCode> tree, keyed by literal config
            lines). Only <HelpCode>config_source: running</HelpCode> is supported
            for this format — Get &amp; Parse Config never captures startup-config.
          </li>
          <li>
            <span className="font-medium text-foreground">Batfish</span> — output
            from an upstream <span className="font-medium text-foreground">
            Extract Facts</span> step (Batfish&apos;s extracted per-node facts,
            keyed by interface name). Only <HelpCode>config_source: running</HelpCode>{" "}
            is supported for this format too — Batfish facts have no
            running/startup distinction.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Config source">
        <p>
          Choose which parsed config to read attribute values from —{" "}
          <HelpCode>running</HelpCode> or <HelpCode>startup</HelpCode> (exactly
          one). Genie and Batfish only ever populate <HelpCode>running</HelpCode>
          — Batfish has no startup-config equivalent at all.
        </p>
        <HelpExample>
          config_source: running
          <br />
          <span className="text-muted-foreground">
            → reads parsed.{"{parsed_key}"}.running (both Parse Cisco Config and
            Get &amp; Parse Config nest their output under running / startup).
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Parsed key">
        <p>
          <HelpCode>parsed_key</HelpCode> must match the matching upstream step&apos;s
          own <HelpCode>output_key</HelpCode> — Parse Cisco Config for
          cisco_config_parser, Get &amp; Parse Config for genie — that is where its
          parsed model was written on each device.
        </p>
        <p>
          Click the search icon next to the field to browse real attribute paths
          from the workflow&apos;s most recent run (requires a saved, previously run
          workflow) and pick the upstream step&apos;s key directly instead of typing
          it — selecting any node under <HelpCode>parsed.*</HelpCode> fills in just
          that key segment.
        </p>
        <HelpWarning title="Add the matching upstream step first">
          <p>
            If no device has parsed data at{" "}
            <HelpCode>parsed.{"{parsed_key}"}</HelpCode>, the step fails with a
            clear error naming the missing key and the expected upstream step — add
            it before this one and make sure <HelpCode>parsed_key</HelpCode> matches
            its <HelpCode>output_key</HelpCode>.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Attributes">
        <p>
          Check <HelpCode>Add Interfaces</HelpCode> to build the interfaces
          list. Per interface, regardless of source format:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">type</span> —{" "}
            <HelpCode>1000base-t</HelpCode> for names starting with{" "}
            <HelpCode>Gigabit</HelpCode>, <HelpCode>100base-tx</HelpCode> for names
            starting with <HelpCode>Ethernet</HelpCode>, <HelpCode>lag</HelpCode>{" "}
            for names containing <HelpCode>port-channel</HelpCode>, else{" "}
            <HelpCode>virtual</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">status</span> — always{" "}
            <HelpCode>Active</HelpCode> for every source format (Nautobot&apos;s{" "}
            <HelpCode>status</HelpCode> is a lifecycle field, not an admin-state
            flag).
          </li>
          <li>
            <span className="font-medium text-foreground">enabled</span> —{" "}
            <HelpCode>true</HelpCode> unless the interface has a{" "}
            <HelpCode>shutdown</HelpCode> line in its config; for Batfish, taken
            directly from the interface&apos;s real{" "}
            <HelpCode>Admin_Up</HelpCode> state.
          </li>
          <li>
            <span className="font-medium text-foreground">mtu</span> — carried
            through when the source reports one (currently only Batfish&apos;s{" "}
            <HelpCode>MTU</HelpCode> fact).
          </li>
          <li>
            <span className="font-medium text-foreground">mode / untagged_vlan</span>{" "}
            — set to <HelpCode>access</HelpCode> with the numeric VLAN ID for a{" "}
            <HelpCode>switchport access vlan</HelpCode> interface (Cisco Config
            Parser&apos;s <HelpCode>l2_access_interfaces</HelpCode>, Genie&apos;s{" "}
            <HelpCode>switchport access vlan</HelpCode> line, or Batfish&apos;s{" "}
            <HelpCode>Access_VLAN</HelpCode> fact).
          </li>
          <li>
            <span className="font-medium text-foreground">mode / tagged_vlans</span>{" "}
            — set to <HelpCode>trunk</HelpCode> with a parsed list of VLAN IDs for
            a Cisco Config Parser trunk interface (
            <HelpCode>l2_trunk_interfaces</HelpCode>, e.g.{" "}
            <HelpCode>switchport trunk allowed vlan 10,20,30-40</HelpCode>). Only
            supported for this source format today — Genie and Batfish don&apos;t
            report trunk/allowed-VLAN data.
          </li>
          <li>
            <span className="font-medium text-foreground">lag</span> — the
            port-channel/bundle interface name (e.g.{" "}
            <HelpCode>Port-channel10</HelpCode>) this interface is a member of, set
            from a <HelpCode>channel-group</HelpCode>/<HelpCode>bundle id</HelpCode>{" "}
            line (Cisco Config Parser&apos;s <HelpCode>port_channels</HelpCode>,
            Genie&apos;s <HelpCode>channel-group</HelpCode> line, or Batfish&apos;s{" "}
            <HelpCode>Channel_Group</HelpCode> fact).
          </li>
          <li>
            <span className="font-medium text-foreground">ip_addresses</span> —
            every IP the interface has. An IOS{" "}
            <HelpCode>ip address ... secondary</HelpCode> line (or, for Cisco
            Config Parser, a parsed secondary IP; or for Batfish, any address in{" "}
            <HelpCode>All_Prefixes</HelpCode> other than{" "}
            <HelpCode>Primary_Address</HelpCode>) is marked with Nautobot IP role{" "}
            <HelpCode>secondary</HelpCode>. Which single address across all
            interfaces is marked <HelpCode>is_primary</HelpCode> (Nautobot&apos;s
            device-level primary IPv4) is controlled separately — see{" "}
            <span className="font-medium text-foreground">
              Update Primary IPv4 address
            </span>{" "}
            below.
          </li>
        </ul>
        <HelpExample>
          attributes: [interfaces]
        </HelpExample>
        <HelpWarning title="Cisco Config Parser: channel-group-only interfaces are invisible to the library">
          <p>
            An interface whose only configuration is{" "}
            <HelpCode>channel-group N mode active</HelpCode> (no IP address, no{" "}
            <HelpCode>switchport</HelpCode> command) is not reported by the Cisco
            Config Parser library in <HelpCode>l3_interfaces</HelpCode>,{" "}
            <HelpCode>l2_access_interfaces</HelpCode>, or{" "}
            <HelpCode>l2_trunk_interfaces</HelpCode> — the only trace of it is as a
            member entry inside <HelpCode>port_channels[].members</HelpCode>. The
            same is true of a port-channel/bundle interface itself (e.g.{" "}
            <HelpCode>interface Port-channel10</HelpCode>) when it carries neither
            an IP address nor a switchport command.
          </p>
          <p>
            This step mitigates that gap: any interface only known via{" "}
            <HelpCode>port_channels</HelpCode> is still added, with{" "}
            <HelpCode>lag</HelpCode> pointing at its port-channel, and the
            port-channel itself is added too if it&apos;s otherwise missing. Its
            description and admin (shutdown) state cannot be recovered in this
            case — the library drops that information along with the rest of the
            interface stanza — so <HelpCode>enabled</HelpCode> defaults to{" "}
            <HelpCode>true</HelpCode> for a synthesized interface.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Update Primary IPv4 address">
        <p>
          A Cisco config has no field that says &quot;this is my primary
          IPv4&quot; — it&apos;s an operational convention, not a config line.
          This control decides how (or whether) this step picks the device&apos;s
          Nautobot primary IPv4 from the parsed interfaces.
        </p>
        <HelpWarning title="Requires Add Interfaces to be checked">
          <p>
            This control only affects the interfaces this step builds — with{" "}
            <HelpCode>Add Interfaces</HelpCode> unchecked, the step is a no-op
            regardless of this setting: no primary IPv4 selection or
            verification happens, and no device is routed to failure.
          </p>
        </HelpWarning>
        <p>
          <span className="font-medium text-foreground">Checked</span> — try each
          strategy in <HelpCode>primary_ipv4_priority</HelpCode>, top to bottom;
          the first interface that matches wins and is marked{" "}
          <HelpCode>is_primary</HelpCode>. A secondary IP address is never
          selected. If no strategy matches, the device is routed to{" "}
          <span className="font-medium text-foreground">failure</span>.
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">
              Use Management Interface
            </span>{" "}
            — first interface whose name starts with{" "}
            <HelpCode>Management</HelpCode> or <HelpCode>Mgmt</HelpCode>
            (case-insensitive).
          </li>
          <li>
            <span className="font-medium text-foreground">
              Use Loopback Interface (highest Loopback first)
            </span>{" "}
            — the Loopback interface with the highest numeric suffix, e.g.{" "}
            <HelpCode>Loopback100</HelpCode> over <HelpCode>Loopback0</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">
              Use Loopback Interface (lowest Loopback first)
            </span>{" "}
            — the lowest numeric suffix, e.g. <HelpCode>Loopback0</HelpCode> over{" "}
            <HelpCode>Loopback100</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">
              Custom Interface Name / Regex
            </span>{" "}
            — first interface whose name matches{" "}
            <HelpCode>primary_ipv4_custom_pattern</HelpCode> (case-insensitive).
            An empty pattern means this strategy never matches.
          </li>
        </ul>
        <p>
          All four strategies always exist in the list — use the arrows to
          reorder them; none can be removed.
        </p>
        <p>
          <span className="font-medium text-foreground">Unchecked (default)</span>{" "}
          — no new primary is selected. Instead, the device&apos;s already-known
          primary IPv4 (its inventory-sourced <HelpCode>primary_ip4</HelpCode>) is
          verified against the parsed interfaces: if still present on any
          interface, it&apos;s re-affirmed (marked <HelpCode>is_primary</HelpCode>{" "}
          so it isn&apos;t silently overwritten downstream); if it has disappeared
          from the config, the device is routed to{" "}
          <span className="font-medium text-foreground">failure</span>. A device
          with no known <HelpCode>primary_ip4</HelpCode> at all is passed through
          unchanged.
        </p>
        <HelpWarning title="Interfaces are always written, even on failure">
          <p>
            Either way, the interfaces list itself is always merged into the
            device&apos;s attribute bag — only the primary-IPv4 decision routes a
            device to <span className="font-medium text-foreground">failure</span>.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            nautobot attribute bag was updated on every device that had usable
            parsed data and, if applicable, a primary IPv4 was resolved or
            verified; devices without parsed data are left unchanged.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — a
            device had parsed interfaces but its primary IPv4 could not be
            resolved (Update Primary IPv4 address checked, no strategy matched)
            or verified (unchecked, its known primary IPv4 is no longer on any
            interface). Its interfaces were still written.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Upstream, add either Get Configs → Parse Cisco Config, Add Testbed →
            Get &amp; Parse Config (pyATS/Genie), or Get from Batfish → Init
            Batfish Snapshot → Extract Facts.
          </li>
          <li>
            Add this step after it; set <HelpCode>source_format</HelpCode> to
            match, set <HelpCode>parsed_key</HelpCode> and{" "}
            <HelpCode>config_source</HelpCode> to match the upstream step&apos;s{" "}
            <HelpCode>output_key</HelpCode>, and check{" "}
            <HelpCode>Add Interfaces</HelpCode>.
          </li>
          <li>
            Decide how the device&apos;s primary IPv4 should be handled: check{" "}
            <HelpCode>Update Primary IPv4 address</HelpCode> and order the
            priority list to select one, or leave it unchecked to verify the
            device&apos;s existing primary IPv4 instead.
          </li>
          <li>
            Add Add to Nautobot or Update Device after it with{" "}
            <HelpCode>interfaces_source: nautobot_origin</HelpCode>.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
