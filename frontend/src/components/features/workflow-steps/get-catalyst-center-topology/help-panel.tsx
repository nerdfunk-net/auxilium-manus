"use client";

import { HelpCode, HelpExample, HelpSection } from "../shared/step-help";

/** Built-in Help tab content for Get Network Topology from CC. */
export function GetCatalystCenterTopologyHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads the topology graphs from the Cisco Catalyst Center and gives
          every device its own links and neighbours. The controller-wide graph
          is fetched once per controller, not once per device. Place it after{" "}
          <HelpCode>Get from Catalyst Center</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Topologies">
        <p>
          <HelpCode>physical</HelpCode> is the cabling graph. The{" "}
          <HelpCode>l3_*</HelpCode> options read the layer-3 graph of one
          protocol (OSPF, IS-IS, EIGRP, static). BGP is not offered: the
          controller rejects it.
        </p>
      </HelpSection>

      <HelpSection title="Where the data lands">
        <HelpExample>
          parsed.&lt;parsed_output_key&gt;.&lt;topology&gt;.parsed = {"{"}node,
          links[]{"}"}
        </HelpExample>
        <p>
          Each link is seen from the device&apos;s side:{" "}
          <HelpCode>local_port</HelpCode>, <HelpCode>remote_port</HelpCode>,{" "}
          <HelpCode>remote_name</HelpCode>, <HelpCode>remote_ip</HelpCode>,{" "}
          <HelpCode>remote_id</HelpCode>, speeds and status. A device that is
          not in a graph gets an empty link list, not a failure; a graph the
          controller cannot return is recorded as an error for that topology.
        </p>
      </HelpSection>
    </div>
  );
}
