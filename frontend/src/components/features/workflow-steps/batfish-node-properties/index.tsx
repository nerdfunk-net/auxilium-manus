"use client";

import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { BATFISH_FACT_KEYS } from "../shared/batfish-fact-keys";
import { BatfishPropertiesFields } from "../shared/batfish-properties-fields";
import { BatfishNodePropertiesHelpPanel } from "./help-panel";

function BatfishNodePropertiesConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  return (
    <div className="flex flex-col gap-4">
      <BatfishPropertiesFields
        config={config}
        onChange={onChange}
        suggestionKeys={BATFISH_FACT_KEYS}
        nodesHelpText="Optional. Leave empty to return properties for every node."
        emptyHelpText={
          <>
            When enabled, the <span className="font-mono">devices</span> outcome
            only carries nodes whose requested properties are empty — e.g. an
            unconfigured TACACS server, which Batfish reports as{" "}
            <span className="font-mono">TACACS_Servers: []</span> rather than a
            missing row. Requires <span className="font-mono">properties</span>{" "}
            above to be set.
          </>
        }
        matchModeHelpNoun="device"
        outputKeyDefault="batfish_node_properties"
      />
    </div>
  );
}

export const BatfishNodePropertiesPlugin: PluginUIComponent = {
  ConfigPanel: BatfishNodePropertiesConfigPanel,
  HelpPanel: BatfishNodePropertiesHelpPanel,
};
