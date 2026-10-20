"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/** Built-in Help tab content for Add IP to Nautobot. */
export function AddIpToNautobotHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Creates an IP address in a Nautobot namespace with the status you choose. A device
          whose address was created, or already existed, leaves through{" "}
          <span className="font-medium text-foreground">success</span>; a device that could
          not be served leaves through{" "}
          <span className="font-medium text-foreground">failure</span>.
        </p>
        <p>
          Running the step again is safe: an address that already exists is reused, not
          created twice. A reused address is left as it is: its status, description and DNS
          name are not changed, and its prefix length is not corrected.
        </p>
        <p>
          Checks that do not write (address, namespace, status, device and interface) run
          before anything is created in Nautobot.
        </p>
      </HelpSection>

      <HelpSection title="nautobot_source_id">
        <p>The Nautobot source (Settings → Sources) to write to.</p>
      </HelpSection>

      <HelpSection title="ip_address">
        <p>
          A fixed address or a per-device <HelpCode>{"{path}"}</HelpCode> expression, for
          example the address found by Get Next Free IP.
        </p>
        <p>
          With a prefix length (<HelpCode>192.168.178.10/24</HelpCode>) the address is created
          as written. Without one (<HelpCode>192.168.178.10</HelpCode>) the step asks Nautobot
          for the most specific prefix in the namespace that contains it and uses that
          prefix&apos;s length.
        </p>
        <HelpExample>
          {"{custom.new_ip}"}
          <br />
          192.168.178.10/24
        </HelpExample>
      </HelpSection>

      <HelpSection title="namespace">
        <p>
          The Nautobot namespace (default <HelpCode>Global</HelpCode>), its UUID, or a{" "}
          <HelpCode>{"{path}"}</HelpCode> expression.
        </p>
      </HelpSection>

      <HelpSection title="status">
        <p>
          The status of the new address. The list shows the statuses your Nautobot defines for
          IP addresses (for example Active, Deprecated and Reserved). You can also type a name
          or a <HelpCode>{"{path}"}</HelpCode> expression.
        </p>
      </HelpSection>

      <HelpSection title="create_prefix and default_mask_length">
        <p>
          Nautobot refuses an address without a parent prefix. With{" "}
          <HelpCode>create_prefix</HelpCode> on, the missing prefix (the network of the
          address, status Active) is created first. After Get Next Free IP this is not needed.
        </p>
        <p>
          <HelpCode>default_mask_length</HelpCode> gives the length for an address without one
          when no prefix contains it (1–32 for IPv4, 1–128 for IPv6). Empty uses 24 for IPv4
          and 64 for IPv6. It is only read when <HelpCode>create_prefix</HelpCode> is on.
        </p>
      </HelpSection>

      <HelpSection title="description and dns_name">
        <p>
          Optional text for the address, fixed or a <HelpCode>{"{path}"}</HelpCode>{" "}
          expression. An expression that resolves to nothing fails the device. A value taken
          from a secret is refused.
        </p>
      </HelpSection>

      <HelpSection title="result_attribute">
        <p>
          Optional attribute that receives the Nautobot ID (UUID) of the address, for example{" "}
          <HelpCode>custom.ip_id</HelpCode>. It must be a bag path: the reserved bags{" "}
          <HelpCode>parsed</HelpCode> and <HelpCode>run_input</HelpCode> and device fields such
          as <HelpCode>device.hostname</HelpCode> cannot be used. It is written only when the
          device succeeds.
        </p>
      </HelpSection>

      <HelpSection title="interface_name and set_primary">
        <p>
          Optional. Assigns the address to this interface of the device, which must exist in
          Nautobot together with the interface; a missing device or interface fails the device
          before the address is created. An address that is already assigned to another
          interface is not attached (<HelpCode>ip_assigned_elsewhere</HelpCode>).{" "}
          <HelpCode>set_primary</HelpCode> also makes it the device&apos;s primary IPv4, needs
          an interface name and is refused for an IPv6 address.
        </p>
      </HelpSection>

      <HelpWarning title="Missing prefix">
        <p>
          Without <HelpCode>create_prefix</HelpCode>, an address with no containing prefix
          fails with <HelpCode>prefix_not_found</HelpCode>.
        </p>
      </HelpWarning>
    </div>
  );
}
