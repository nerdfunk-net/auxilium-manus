"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/** Built-in Help tab content for Update IP. */
export function UpdateNautobotIpHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Changes an existing IP address in Nautobot. The address is identified
          by its Nautobot ID (UUID), for example the one Add IP to Nautobot
          wrote to an attribute with <HelpCode>result_attribute</HelpCode>. A
          device whose address was updated, or already had every value, leaves
          through <span className="font-medium text-foreground">success</span>;
          a device that could not be served leaves through{" "}
          <span className="font-medium text-foreground">failure</span>.
        </p>
        <p>
          Only the fields you fill in are changed. An empty field is left as it
          is, and there is no way to clear a value with this step. Running the
          step again is safe: nothing is written when the address already has
          the values.
        </p>
      </HelpSection>

      <HelpSection title="nautobot_source_id">
        <p>The Nautobot source (Settings → Sources) to write to.</p>
      </HelpSection>

      <HelpSection title="ip_id">
        <p>
          The Nautobot ID of the address: a fixed UUID or a per-device{" "}
          <HelpCode>{"{path}"}</HelpCode> expression. An address (
          <HelpCode>10.0.0.1/24</HelpCode>) is not accepted; the device fails
          with <HelpCode>ip_id_invalid</HelpCode>.
        </p>
        <HelpExample>{"{custom.ip_id}"}</HelpExample>
      </HelpSection>

      <HelpSection title="status">
        <p>
          The new status. The list shows the statuses your Nautobot defines for
          IP addresses (for example Active, Deprecated and Reserved). You can
          also type a name or a <HelpCode>{"{path}"}</HelpCode> expression.
        </p>
      </HelpSection>

      <HelpSection title="type">
        <p>
          <HelpCode>host</HelpCode>, <HelpCode>dhcp</HelpCode> or{" "}
          <HelpCode>slaac</HelpCode>, or a <HelpCode>{"{path}"}</HelpCode>{" "}
          expression that resolves to one of them. Any other value fails the
          device with <HelpCode>type_invalid</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="role">
        <p>
          The name or UUID of a Nautobot role that applies to IP addresses, or a{" "}
          <HelpCode>{"{path}"}</HelpCode> expression. An unknown role fails the
          device with <HelpCode>role_not_found</HelpCode>.
        </p>
        <HelpExample>Secondary</HelpExample>
      </HelpSection>

      <HelpSection title="dns_name and description">
        <p>
          Fixed text or a <HelpCode>{"{path}"}</HelpCode> expression. An
          expression that resolves to nothing fails the device. A value taken
          from a secret is refused.
        </p>
      </HelpSection>

      <HelpSection title="namespace">
        <p>
          The name or UUID of the namespace to move the address to, or a{" "}
          <HelpCode>{"{path}"}</HelpCode> expression. The address is attached to
          the most specific prefix of that namespace that contains it.
        </p>
      </HelpSection>

      <HelpSection title="IP addresses from interfaces, ip_version and dry_run">
        <p>
          Switch on <HelpCode>ips_from_interfaces</HelpCode> to update every IP
          address on the device&apos;s interfaces instead of one chosen address.
          The step reads the Nautobot attributes of each device (run{" "}
          <span className="font-medium text-foreground">
            Get Nautobot Attributes
          </span>{" "}
          with interfaces first) and applies the values you configure to all of
          those addresses. The interfaces decide <em>which</em> addresses are
          changed; the values (status, type, role, namespace, DNS name,
          description) cannot be derived from them, so you set them here.{" "}
          <HelpCode>ip_id</HelpCode> must be empty in this mode, and at least
          one value is still required.
        </p>
        <p>
          <HelpCode>ip_version</HelpCode> limits the update to IPv4 or IPv6
          addresses. An address that is on several interfaces is updated once.
        </p>
        <p>
          <HelpCode>dns_name</HelpCode> and <HelpCode>description</HelpCode> may
          differ per address. Besides <HelpCode>{"{path}"}</HelpCode>{" "}
          expressions they accept <HelpCode>{"{ip.address}"}</HelpCode>{" "}
          (10.1.2.3/24), <HelpCode>{"{ip.host}"}</HelpCode> (10.1.2.3),{" "}
          <HelpCode>{"{interface.name}"}</HelpCode> (Gi0/0.100, the first
          interface that lists the address) and{" "}
          <HelpCode>{"{interface.slug}"}</HelpCode> (gi0-0-100, safe in a DNS
          name). A placeholder that resolves to nothing, or to a secret, fails
          the device before anything is written.
        </p>
        <HelpExample>
          {"{interface.slug}.{device.name}.example.org"}
        </HelpExample>
        <p>
          <HelpCode>dry_run</HelpCode> writes nothing. Nautobot is read and each
          device gets a preview (<HelpCode>would_change</HelpCode>: address and
          the names of the fields that would change,{" "}
          <HelpCode>unchanged</HelpCode>, <HelpCode>skipped_shared</HelpCode>,{" "}
          <HelpCode>skipped_empty</HelpCode>); the counts are in{" "}
          <HelpCode>update_ip_counts</HelpCode>. Run it first.{" "}
          <HelpCode>dry_run</HelpCode> only works together with{" "}
          <HelpCode>ips_from_interfaces</HelpCode>; on its own the step refuses
          to run instead of writing.
        </p>
        <p>
          A value that renders empty for one address, for example{" "}
          <HelpCode>{"{interface.slug}"}</HelpCode> of an interface named
          &quot;///&quot;, skips only that address. It is counted in{" "}
          <HelpCode>skipped_empty</HelpCode>; the other addresses of the device
          are still updated.
        </p>
      </HelpSection>

      <HelpWarning title="Addresses that are assigned elsewhere are skipped">
        <p>
          An address that is also assigned to another device&apos;s interface or
          to a VM interface (HSRP / VRRP virtual IPs, anycast) is not changed,
          because the change would apply to every holder. It is counted in{" "}
          <HelpCode>skipped_shared</HelpCode> and listed in the dry-run preview.
          An address whose assignment cannot be confirmed is skipped too. Only
          the interface assignments are checked: an address that is exclusive
          there but also used as a NAT or service address elsewhere is still
          updated.
        </p>
      </HelpWarning>

      <HelpWarning title="Moving to another namespace needs a prefix there">
        <p>
          Nautobot derives an address&apos;s namespace from its parent prefix.
          If the target namespace has no prefix that contains the address, the
          device fails with <HelpCode>prefix_not_found</HelpCode> and nothing is
          changed; create the prefix first. Moving was verified on Nautobot 3.2;
          other versions may reject it, and the device then fails with
          Nautobot&apos;s refusal.
        </p>
      </HelpWarning>

      <HelpWarning title="Several devices, one address">
        <p>
          If devices share the same <HelpCode>ip_id</HelpCode> but resolve
          different values, the last write wins. Use one address per device.
        </p>
      </HelpWarning>
    </div>
  );
}
