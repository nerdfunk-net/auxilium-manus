"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/** Built-in Help tab content for Get Policy from ACI. */
export function GetAciPolicyHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads the EPGs and contracts that apply to each leaf or spine from the APIC — no SSH
          access needed, nothing is written to ACI. The tenant policy is read once per APIC, then
          each switch gets only the EPGs deployed on it. Place it after{" "}
          <HelpCode>Get from ACI</HelpCode>; devices from any other source fail with{" "}
          <HelpCode>not_aci_device</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Where the data lands">
        <HelpExample>
          parsed.&lt;parsed_output_key&gt;.epgs = {"{"}parsed, error{"}"}
          <br />
          parsed.&lt;parsed_output_key&gt;.contracts = {"{"}parsed, error{"}"}
          <br />
          parsed.&lt;parsed_output_key&gt;.l3outs = {"{"}parsed, error{"}"}
        </HelpExample>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>epgs</HelpCode> — one entry per EPG deployed on the switch: tenant,
            application profile, EPG, class tag, bridge domain, and the contracts it{" "}
            <HelpCode>provided</HelpCode> and <HelpCode>consumed</HelpCode> as{" "}
            <HelpCode>tenant/name</HelpCode>.
          </li>
          <li>
            <HelpCode>contracts</HelpCode> — the contracts those EPGs use: scope, priority,
            subjects with their filters and filter entries (protocol, ports), and the EPGs that
            provide and consume the contract anywhere in the fabric (
            <HelpCode>provider_epgs</HelpCode>, <HelpCode>consumer_epgs</HelpCode>; external
            EPGs show up here as <HelpCode>uni/tn-…/out-…/instP-…</HelpCode>).
          </li>
          <li>
            <HelpCode>l3outs</HelpCode> — the L3Outs whose nodes or interfaces include this
            switch (a vPC path counts for both of its nodes): VRF, protocols
            (<HelpCode>bgp</HelpCode>, <HelpCode>ospf</HelpCode>, <HelpCode>eigrp</HelpCode>),
            nodes with router id, interfaces with address, type, encap and MTU, and the external
            EPGs with class tag, subnets (with the APIC&apos;s scope flags, copied as they are) and
            the contracts they provide and consume.
          </li>
        </ul>
        <p>
          A contract named without a tenant is looked up in the EPG&apos;s tenant first and then in{" "}
          <HelpCode>common</HelpCode>, as the APIC does.
        </p>
      </HelpSection>

      <HelpSection title="Parsed output key">
        <p>
          Default <HelpCode>aci_policy</HelpCode>. The same {"{"}parsed, error{"}"} shape the other
          detail steps use, so Route on Attribute, Jinja templates and Log Attributes read it the
          same way.
        </p>
        <HelpWarning title="Limits">
          <p>
            <HelpCode>vzAny</HelpCode>, contract interfaces and taboo contracts are not read. If the policy cannot be read, every
            device fails with the APIC error. For the rules a switch actually enforces, use the{" "}
            <HelpCode>contracts</HelpCode> fact of Get Details from ACI.
          </p>
        </HelpWarning>
      </HelpSection>
    </div>
  );
}
