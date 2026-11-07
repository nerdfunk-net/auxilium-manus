"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/** Built-in Help tab content for Find Endpoint in ACI. */
export function FindAciEndpointsHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Looks up the IPv4 or MAC address of every device in the APIC&apos;s learned endpoints and
          records which EPG it belongs to and which leaf port (or vPC) it is attached to. It works
          on devices from <strong>any</strong> source, for example Nautobot — they do not have to
          come from <HelpCode>Get from ACI</HelpCode>. Nothing is written to ACI.
        </p>
      </HelpSection>

      <HelpSection title="Settings">
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>aci_source_id</HelpCode> — the Cisco ACI source (APIC) to ask.
          </li>
          <li>
            <HelpCode>address_path</HelpCode> — the device attribute that holds the address,
            default <HelpCode>primary_ip4</HelpCode>. IPv4 and MAC addresses (
            <HelpCode>00:50:56:aa:bb:01</HelpCode>, <HelpCode>0050.56aa.bb01</HelpCode>) are
            understood.
          </li>
          <li>
            <HelpCode>parsed_output_key</HelpCode> — where the result lands, default{" "}
            <HelpCode>aci_endpoint</HelpCode>.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Where the data lands">
        <HelpExample>
          parsed.&lt;parsed_output_key&gt;.endpoints = {"{"}parsed, error{"}"}
        </HelpExample>
        <p>
          <HelpCode>parsed</HelpCode> is a list: MAC, IPs, tenant, application profile and EPG (or{" "}
          <HelpCode>external_epg</HelpCode> as <HelpCode>l3out/epg</HelpCode> for an endpoint behind
          an L3Out), encap, and <HelpCode>attachments</HelpCode> with pod, node ids and interface.
          A vPC lists both nodes. An address the fabric does not know gives an empty list and the
          device still succeeds — route on <HelpCode>count()</HelpCode> to tell found from not
          found.
        </p>
        <HelpWarning title="Limits">
          <p>
            An endpoint behind a hypervisor (VMM) shows no attachment. If the APIC cannot be
            reached the device fails with the APIC error. A device with no value at the address
            path fails with <HelpCode>no_address</HelpCode>.
          </p>
        </HelpWarning>
      </HelpSection>
    </div>
  );
}
