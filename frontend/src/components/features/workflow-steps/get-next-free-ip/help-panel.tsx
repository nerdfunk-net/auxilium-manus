"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/** Built-in Help tab content for Get Next Free IP. */
export function GetNextFreeIpHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Looks up a prefix in a Nautobot namespace, reads its free addresses and writes
          the next ones to an attribute of every device. Devices that get their addresses
          leave through <span className="font-medium text-foreground">success</span>; a
          device that cannot be served (prefix not found, not enough free addresses)
          leaves through <span className="font-medium text-foreground">failure</span>.
        </p>
        <p>
          Devices are served one after another from the same list of free addresses, so
          they never get the same address from one run of this step.
        </p>
      </HelpSection>

      <HelpSection title="nautobot_source_id">
        <p>The Nautobot source (Settings → Sources) to query.</p>
      </HelpSection>

      <HelpSection title="prefix">
        <p>
          The prefix in CIDR form, fixed or a per-device <HelpCode>{"{path}"}</HelpCode>{" "}
          expression. An address with a length (<HelpCode>192.168.178.240/24</HelpCode>) is
          turned into its network (<HelpCode>192.168.178.0/24</HelpCode>).
        </p>
        <p>To use the prefix of the device&apos;s own IP:</p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <HelpCode>{"{device.primary_ip4}"}</HelpCode> (address only, such as{" "}
            <HelpCode>192.168.178.240</HelpCode>): the step asks Nautobot for the most
            specific prefix in the namespace that contains the address.
          </li>
          <li>
            <HelpCode>{"{device.primary_ip4_cidr}"}</HelpCode> gives{" "}
            <HelpCode>192.168.178.240/24</HelpCode>, which becomes{" "}
            <HelpCode>192.168.178.0/24</HelpCode>.
          </li>
          <li>
            <HelpCode>{"{nautobot.primary_ip4.parent.prefix}"}</HelpCode> is the prefix
            Nautobot stored for that IP. It needs Get Nautobot Attributes to have run
            earlier.
          </li>
        </ul>
        <HelpExample>
          192.168.178.0/24
          <br />
          {"{device.primary_ip4_cidr}"}
          <br />
          {"{custom.site_prefix}"}
        </HelpExample>
      </HelpSection>

      <HelpSection title="namespace">
        <p>
          The same prefix can exist in several namespaces, so the step first finds the
          prefix in this namespace and then reads that prefix&apos;s free addresses. A name
          (default <HelpCode>Global</HelpCode>), a UUID or a{" "}
          <HelpCode>{"{path}"}</HelpCode> expression.
        </p>
      </HelpSection>

      <HelpSection title="count">
        <p>
          How many addresses each device needs (1–100). With 1 the attribute holds a single
          address such as <HelpCode>192.168.178.10</HelpCode>; with more it holds a list.
          The prefix length is not stored.
        </p>
      </HelpSection>

      <HelpSection title="start_offset">
        <p>
          Where the search starts, counted from the network address. For{" "}
          <HelpCode>192.168.178.0/24</HelpCode>, 1 starts at .1 and 10 starts at .10;
          free addresses below that are skipped.
        </p>
      </HelpSection>

      <HelpSection title="attribute_path">
        <p>
          The attribute that receives the result. Later steps read it as{" "}
          <HelpCode>{"{custom.new_ip}"}</HelpCode>. The reserved bags{" "}
          <HelpCode>parsed</HelpCode> and <HelpCode>run_input</HelpCode> and read-only{" "}
          <HelpCode>device.*</HelpCode> fields cannot be used.
        </p>
        <HelpExample>
          custom.new_ip
          <br />
          network.management_ip
        </HelpExample>
      </HelpSection>

      <HelpWarning title="Addresses are not reserved">
        <p>
          The step only reads Nautobot. Until an address is created there (for example by
          Add to Nautobot), a parallel run or another fan-out child can receive the same
          address. Place this step before the fan-out, or after a Fan In.
        </p>
      </HelpWarning>
    </div>
  );
}
