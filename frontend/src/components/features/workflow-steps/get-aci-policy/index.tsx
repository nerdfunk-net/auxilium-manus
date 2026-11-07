"use client";

import { useCallback } from "react";

import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { ParsedOutputKeyField, readString } from "../shared/catalyst-center-fact-fields";
import { GetAciPolicyHelpPanel } from "./help-panel";

const DEFAULT_OUTPUT_KEY = "aci_policy";

function GetAciPolicyConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const outputKey = readString(config, "parsed_output_key", DEFAULT_OUTPUT_KEY);

  const handleOutputKeyChange = useCallback(
    (next: string) => onChange({ ...config, parsed_output_key: next }),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <ParsedOutputKeyField
        value={outputKey}
        fallback={DEFAULT_OUTPUT_KEY}
        suffix="<epgs|contracts|l3outs>"
        onChange={handleOutputKeyChange}
      />
    </div>
  );
}

export const GetAciPolicyPlugin: PluginUIComponent = {
  ConfigPanel: GetAciPolicyConfigPanel,
  HelpPanel: GetAciPolicyHelpPanel,
};
