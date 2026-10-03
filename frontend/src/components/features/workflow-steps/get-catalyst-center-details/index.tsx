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
import { GetCatalystCenterDetailsHelpPanel } from "./help-panel";

const DEFAULT_FACTS = ["device", "interfaces"] as const;
const DEFAULT_OUTPUT_KEY = "catalyst_details";

// Keep in sync with FACTS in backend/workflow_steps/get_catalyst_center_details/executor.py.
const FACT_OPTIONS: readonly FactOption[] = [
  {
    value: "device",
    label: "Device",
    hint: "Inventory record: serial, role, reachability, uptime",
  },
  {
    value: "software",
    label: "Software",
    hint: "Software type and version, platform, series",
  },
  {
    value: "interfaces",
    label: "Interfaces",
    hint: "Status, speed, duplex, MTU, MAC, IPv4, VLANs",
  },
  {
    value: "vlans",
    label: "VLANs",
    hint: "VLAN interfaces with number, IP and prefix",
  },
  {
    value: "compliance",
    label: "Compliance",
    hint: "Overall status plus one entry per compliance type",
  },
];

function GetCatalystCenterDetailsConfigPanel({
  config,
  onChange,
}: PluginConfigPanelProps) {
  const facts = useMemo(
    () => readStringList(config, "facts", DEFAULT_FACTS),
    [config],
  );
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

export const GetCatalystCenterDetailsPlugin: PluginUIComponent = {
  ConfigPanel: GetCatalystCenterDetailsConfigPanel,
  HelpPanel: GetCatalystCenterDetailsHelpPanel,
};
