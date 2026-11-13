"use client";

import { HelpCode, HelpSection, HelpWarning } from "../shared/step-help";

/** Built-in Help tab content for Discover Network. */
export function DiscoverNetworkHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Walks across the network through CDP. Starting at the devices that come into the step
          (the seeds), it logs into each one, reads{" "}
          <HelpCode>show cdp neighbors detail</HelpCode>, logs out, and adds the neighbours to a
          list of known devices. With <HelpCode>follow_neighbors</HelpCode> on, the next known
          device that was not visited yet is visited the same way, until nothing new is left or
          a limit is reached.
        </p>
        <p>
          Supported platforms: Cisco IOS, IOS-XE and NX-OS. Requires devices from an upstream
          step (for example Get from List with one seed) and an SSH credential.
        </p>
      </HelpSection>

      <HelpSection title="Which neighbours are followed">
        <p>
          A neighbour is logged into only if it reports a management IPv4 address, advertises a
          router or switch capability (<HelpCode>follow_only_infrastructure</HelpCode>), lies
          inside one of the <HelpCode>permitted_prefixes</HelpCode>, is a supported platform
          (read from the CDP platform, or from the software line of the same output, so a virtual
          IOS switch that reports &ldquo;Linux&rdquo; is still recognised) and the limits <HelpCode>max_devices</HelpCode> and <HelpCode>max_depth</HelpCode> are
          not reached. Every other neighbour is only listed, with a reason:{" "}
          <HelpCode>follow_disabled</HelpCode>, <HelpCode>no_management_ip</HelpCode>,{" "}
          <HelpCode>not_infrastructure</HelpCode>, <HelpCode>out_of_scope</HelpCode>,{" "}
          <HelpCode>unsupported_platform</HelpCode>, <HelpCode>limit_reached</HelpCode>,{" "}
          <HelpCode>unreachable</HelpCode> or <HelpCode>login_failed</HelpCode>.
        </p>
        <p>
          <HelpCode>resolve_management_ip</HelpCode> (on by default, needs a Nautobot source):
          CDP reports an interface address, which a device may not accept logins on. The
          neighbour is looked up in Nautobot by name and its primary IPv4 is used; if the name
          finds nothing, by the interface address. The address found is the one checked against
          the permitted prefixes and logged into. An unclear or missing answer keeps the CDP
          address. Each link in the result shows the reported address and where the address
          came from.
        </p>
        <HelpWarning title="Scope is your safety net">
          <p>
            What a neighbour reports about itself is not trusted. Permitted prefixes must be /8
            or more specific, and loopback, link-local and multicast addresses are never
            visited. The operator must also switch on{" "}
            <HelpCode>DISCOVER_NETWORK_FOLLOW_ENABLED</HelpCode> (on by default in development
            only), because the devices found are not from the inventory. CDP is not
            authenticated: a device inside your prefixes can claim any management address and
            is then offered the step&apos;s SSH credential, so keep the prefixes narrow and use
            a credential that may only read.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Result">
        <p>
          The <HelpCode>success</HelpCode> exit carries the seeds and every device that was
          logged into. Discovered devices are new devices in the workflow with their management
          IP as <HelpCode>primary_ip4</HelpCode>. Wire an{" "}
          <HelpCode>Exists in Nautobot</HelpCode> step with the{" "}
          <HelpCode>interface_ip</HelpCode> strategy (any interface address; a CDP management address is often a loopback) behind it to find the devices Nautobot does
          not know. Each device has <HelpCode>parsed.&lt;node id&gt;.discovery</HelpCode>. On the
          run page, the step&apos;s result shows a <strong>Network discovery</strong> panel: the
          visited devices, the neighbours that were seen but not visited (with the reason), the
          links and a warning when a limit stopped the walk. The same lists are in the run
          metadata under <HelpCode>&lt;node id&gt;.discovery</HelpCode>.
        </p>
        <p>
          A dead neighbour never fails the step. A seed that cannot be visited, or that has CDP
          switched off, leaves through <HelpCode>failure</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Fan-out">
        <p>
          A walk is one connected crawl. With fan-out on the seeds every child would walk alone
          and visit shared devices again. Use one seed, or no fan-out before this step.
        </p>
      </HelpSection>
    </div>
  );
}
