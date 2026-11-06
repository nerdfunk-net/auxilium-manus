"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/** Built-in Help tab content for Get Details from ACI. */
export function GetAciDetailsHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads structured facts about each leaf or spine from the APIC REST API — no SSH access
          needed. Place it after <HelpCode>Get from ACI</HelpCode>; devices from any other source
          fail with <HelpCode>not_aci_device</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Facts">
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>device</HelpCode> — fabric node record (serial, role, state, uptime).
          </li>
          <li>
            <HelpCode>software</HelpCode> — switch software version and model.
          </li>
          <li>
            <HelpCode>hardware</HelpCode> — chassis, line cards, power supplies and fans.
          </li>
          <li>
            <HelpCode>interfaces</HelpCode> — physical ports, port-channels, SVIs, loopbacks and
            their IPv4 addresses. A spine can have hundreds of ports, so the stored run result may
            show a &quot;too large&quot; marker; later steps still read the full value.
          </li>
          <li>
            <HelpCode>neighbors</HelpCode> — LLDP and CDP adjacencies.
          </li>
          <li>
            <HelpCode>vlans</HelpCode> — bridge domains and VRFs on the switch.
          </li>
          <li>
            <HelpCode>health</HelpCode> — system and chassis health scores.
          </li>
          <li>
            <HelpCode>faults</HelpCode> — active faults of the switch.
          </li>
          <li>
            <HelpCode>routes</HelpCode> — IPv4 routes with next hops.
          </li>
          <li>
            <HelpCode>protocols</HelpCode> — BGP, IS-IS and OSPF adjacencies.
          </li>
          <li>
            <HelpCode>endpoints</HelpCode> — learned endpoints (MAC and IP).
          </li>
          <li>
            <HelpCode>vpc</HelpCode> — vPC domain and vPC interfaces.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Parsed output key">
        <HelpExample>
          parsed.&lt;parsed_output_key&gt;.&lt;fact&gt; = {"{"}parsed, error{"}"}
        </HelpExample>
        <p>
          Default <HelpCode>aci_details</HelpCode>. The same shape the other detail steps use, so
          Route on Attribute, Jinja templates, Log Attributes and Config to Attributes read it the
          same way.
        </p>
        <HelpWarning title="Partial failures">
          <p>
            A fact the APIC cannot return is recorded as <HelpCode>parsed: null</HelpCode> plus an
            error text and the device still succeeds. The device only fails when every selected
            fact failed.
          </p>
        </HelpWarning>
      </HelpSection>
    </div>
  );
}
