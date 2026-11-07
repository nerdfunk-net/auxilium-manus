"use client";

import { HelpCode, HelpSection, HelpWarning } from "../shared/step-help";

/** Built-in Help tab content for Collect Client Data. */
export function CollectClientDataHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Connects to each device over SSH, reads its ARP table and MAC address table and
          stores what it finds, so you can later ask &ldquo;where is this MAC or IP
          address?&rdquo;. Each entry records the device, the interface or port, the VLAN and
          the VRF; with <HelpCode>collect_hostname</HelpCode> the DNS name of each IP address
          is stored too.
        </p>
        <p>
          Supported platforms: Cisco IOS, IOS-XE and NX-OS. Requires devices from an upstream
          inventory step and an SSH credential.
        </p>
      </HelpSection>

      <HelpSection title="What is read">
        <p>
          <HelpCode>show ip arp</HelpCode> gives IP, MAC and interface. For an SVI such as{" "}
          <HelpCode>Vlan10</HelpCode> the VLAN is taken from the name.{" "}
          <HelpCode>show mac address-table</HelpCode> gives MAC, VLAN and the port the MAC was
          learned on. With <HelpCode>collect_vrfs</HelpCode> the step asks the device for its
          VRFs (<HelpCode>show vrf</HelpCode>) and reads the ARP table of each one, so you do
          not need to know them.
        </p>
      </HelpSection>

      <HelpSection title="Commands a device does not support">
        <p>
          Each command is judged on its own. A router has no MAC address table: the refusal is
          recorded as <HelpCode>not_supported</HelpCode> and the device still succeeds. A
          device fails only when it cannot be reached, when a table&apos;s output is not a table (a
          banner or dropped session is never stored as &ldquo;no rows&rdquo;), or when every table
          you asked for was refused.
        </p>
        <p>
          A summary is added to each device under{" "}
          <HelpCode>parsed.&lt;node id&gt;.client_data</HelpCode>: <HelpCode>arp_status</HelpCode>
          , <HelpCode>mac_status</HelpCode>, <HelpCode>vrf_status</HelpCode>,{" "}
          <HelpCode>arp_entries</HelpCode>, <HelpCode>mac_entries</HelpCode>,{" "}
          <HelpCode>hostnames</HelpCode> and <HelpCode>vrfs</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Reverse DNS">
        <p>
          Off by default. Each IP address is looked up once per run, with a timeout, so a slow
          resolver does not stall the step. Only DNS queries are sent; nothing connects to the
          client addresses.
        </p>
      </HelpSection>

      <HelpSection title="Retention">
        <p>
          Each device keeps its newest collections (<HelpCode>CLIENT_DATA_KEEP_SESSIONS</HelpCode>
          , default 5); older ones are purged by age (
          <HelpCode>CLIENT_DATA_RETENTION_DAYS</HelpCode>, default 90). A device&apos;s newest
          collection is always kept. Running the step again in the same run replaces that run&apos;s
          data for the device.
        </p>
        <HelpWarning title="Device names must be unique">
          <p>
            Data is stored per device name. A second device with the same name in one step
            fails with <HelpCode>duplicate_key</HelpCode>.
          </p>
        </HelpWarning>
      </HelpSection>
    </div>
  );
}
