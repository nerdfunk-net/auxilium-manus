"use client";

import { useCallback, useMemo } from "react";

import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import {
  FactCheckboxGroup,
  ParsedOutputKeyField,
  readString,
  readStringList,
  type FactOption,
} from "../shared/catalyst-center-fact-fields";
import { GetAciDetailsHelpPanel } from "./help-panel";

const DEFAULT_FACTS = ["device", "software", "interfaces"] as const;
const DEFAULT_OUTPUT_KEY = "aci_details";

// Keep in sync with FACTS in backend/workflow_steps/get_aci_details/executor.py.
export const FACT_OPTIONS: readonly FactOption[] = [
  { value: "device", label: "Device", hint: "Fabric node record: serial, role, state, uptime" },
  { value: "software", label: "Software", hint: "Switch software version and model" },
  { value: "hardware", label: "Hardware", hint: "Chassis, line cards, power supplies, fans" },
  { value: "interfaces", label: "Interfaces", hint: "Ports, port-channels, SVIs, loopbacks, IPv4" },
  { value: "neighbors", label: "Neighbors", hint: "LLDP and CDP adjacencies" },
  { value: "vlans", label: "VLANs", hint: "Bridge domains and VRFs on the switch" },
  { value: "health", label: "Health", hint: "System and chassis health scores" },
  { value: "faults", label: "Faults", hint: "Active faults of the switch" },
  { value: "routes", label: "Routes", hint: "IPv4 routes with next hops" },
  { value: "protocols", label: "Protocols", hint: "BGP, IS-IS and OSPF adjacencies" },
  { value: "endpoints", label: "Endpoints", hint: "Learned endpoints (MAC and IP)" },
  { value: "vpc", label: "vPC", hint: "vPC domain and vPC interfaces" },
  { value: "epgs", label: "EPGs", hint: "EPGs deployed on the switch with tag, encap, BD and VRF" },
  { value: "contracts", label: "Contracts", hint: "Zoning rules the switch enforces, with filter entries" },
];

function GetAciDetailsConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const facts = useMemo(() => readStringList(config, "facts", DEFAULT_FACTS), [config]);
  const outputKey = readString(config, "parsed_output_key", DEFAULT_OUTPUT_KEY);

  const handleFactsChange = useCallback(
    (next: string[]) => onChange({ ...config, facts: next }),
    [config, onChange],
  );
  const handleOutputKeyChange = useCallback(
    (next: string) => onChange({ ...config, parsed_output_key: next }),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <FactCheckboxGroup
        name="facts"
        options={FACT_OPTIONS}
        selected={facts}
        onChange={handleFactsChange}
      />
      <ParsedOutputKeyField
        value={outputKey}
        fallback={DEFAULT_OUTPUT_KEY}
        suffix="<fact>"
        onChange={handleOutputKeyChange}
      />
    </div>
  );
}

export const GetAciDetailsPlugin: PluginUIComponent = {
  ConfigPanel: GetAciDetailsConfigPanel,
  HelpPanel: GetAciDetailsHelpPanel,
};
