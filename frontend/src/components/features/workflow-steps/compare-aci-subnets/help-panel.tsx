"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/** Built-in Help tab content for Compare ACI Subnets with Nautobot. */
export function CompareAciSubnetsHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads the gateway subnets of all bridge domains and EPGs from an APIC and the IP prefixes
          of a Nautobot, and reports where they disagree. It is a <strong>report only</strong>:
          nothing is written to ACI or Nautobot, and the devices of the workflow are not used.
        </p>
      </HelpSection>

      <HelpSection title="Settings">
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>aci_source_id</HelpCode>, <HelpCode>nautobot_source_id</HelpCode> — the two
            sources to compare.
          </li>
          <li>
            <HelpCode>namespace</HelpCode> — the Nautobot namespace the ACI subnets are compared
            in, default <HelpCode>Global</HelpCode>. A subnet matches a prefix with the same
            network in that namespace; the prefix&apos;s type and status do not matter.
          </li>
          <li>
            <HelpCode>namespace_from_vrf</HelpCode> — use each subnet&apos;s VRF name as the
            namespace instead. A subnet whose bridge domain has no VRF is skipped and listed under{" "}
            <HelpCode>skipped</HelpCode>. VRFs of different tenants with the same name share one
            namespace. With <HelpCode>scope_prefixes</HelpCode> set, this mode also looks at the
            Nautobot prefixes of unrelated namespaces (ones no VRF maps to), so those inside a
            scope prefix are reported as <HelpCode>missing_in_aci</HelpCode>.
          </li>
          <li>
            <HelpCode>scope_prefixes</HelpCode> — optional, one prefix per line. Nautobot{" "}
            <em>network</em> prefixes inside them that no ACI subnet matches are reported as{" "}
            <HelpCode>missing_in_aci</HelpCode>. Containers, pools and the scope prefixes
            themselves are not. Empty skips this check.
          </li>
          <li>
            <HelpCode>output_key</HelpCode> — name of the run metadata entry, default{" "}
            <HelpCode>aci_subnet_report</HelpCode>.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="The report">
        <HelpExample>
          metadata[&quot;&lt;node id&gt;.&lt;output_key&gt;&quot;] = {"{"}summary, artifact_ref, …{"}"}
        </HelpExample>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>missing_in_nautobot</HelpCode> — ACI subnets with no Nautobot prefix, with
            tenant, VRF, bridge domain, gateway and <HelpCode>covered_by</HelpCode>, the smallest
            Nautobot prefix that contains the subnet.
          </li>
          <li>
            <HelpCode>missing_in_aci</HelpCode> — see <HelpCode>scope_prefixes</HelpCode>; null
            when no scope is set.
          </li>
          <li>
            <HelpCode>overlaps</HelpCode> — the same network used by more than one bridge domain
            in the same namespace, with the owners.
          </li>
          <li>
            <HelpCode>matched</HelpCode> and <HelpCode>skipped</HelpCode>.
          </li>
        </ul>
        <p>
          The metadata holds the counts and the first 50 prefixes of each list; the complete JSON
          report is the artifact in <HelpCode>artifact_ref</HelpCode>. The{" "}
          <HelpCode>success</HelpCode> outcome is always taken; the{" "}
          <HelpCode>differences</HelpCode> outcome as well when the sources disagree, so a workflow
          can branch on drift.
        </p>
        <HelpWarning title="Limits">
          <p>
            External EPG subnets of L3Outs are not gateway subnets and are not read. If either
            system cannot be read the step fails; it never reports a partial answer.
          </p>
        </HelpWarning>
      </HelpSection>
    </div>
  );
}
