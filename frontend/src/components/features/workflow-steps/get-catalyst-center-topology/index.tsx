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
import { GetCatalystCenterTopologyHelpPanel } from "./help-panel";

const DEFAULT_TOPOLOGIES = ["physical"] as const;
const DEFAULT_OUTPUT_KEY = "catalyst_topology";

// Keep in sync with TOPOLOGIES in backend/workflow_steps/get_catalyst_center_topology/executor.py.
const TOPOLOGY_OPTIONS: readonly FactOption[] = [
  { value: "physical", label: "Physical", hint: "Cabling between devices" },
  { value: "l3_ospf", label: "Layer 3 · OSPF", hint: "OSPF adjacencies" },
  { value: "l3_isis", label: "Layer 3 · IS-IS", hint: "IS-IS adjacencies" },
  { value: "l3_eigrp", label: "Layer 3 · EIGRP", hint: "EIGRP adjacencies" },
  { value: "l3_static", label: "Layer 3 · Static", hint: "Static routing links" },
];

function GetCatalystCenterTopologyConfigPanel({
  config,
  onChange,
}: PluginConfigPanelProps) {
  const topologies = useMemo(
    () => readStringList(config, "topologies", DEFAULT_TOPOLOGIES),
    [config],
  );
  const outputKey = readString(config, "parsed_output_key", DEFAULT_OUTPUT_KEY);

  const handleTopologiesChange = useCallback(
    (next: string[]) => onChange({ ...config, topologies: next }),
    [config, onChange],
  );
  const handleOutputKeyChange = useCallback(
    (next: string) => onChange({ ...config, parsed_output_key: next }),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <FactCheckboxGroup
        name="topologies"
        options={TOPOLOGY_OPTIONS}
        selected={topologies}
        onChange={handleTopologiesChange}
      />
      <ParsedOutputKeyField
        value={outputKey}
        fallback={DEFAULT_OUTPUT_KEY}
        suffix="<topology>"
        onChange={handleOutputKeyChange}
      />
    </div>
  );
}

export const GetCatalystCenterTopologyPlugin: PluginUIComponent = {
  ConfigPanel: GetCatalystCenterTopologyConfigPanel,
  HelpPanel: GetCatalystCenterTopologyHelpPanel,
};
