"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { BATFISH_INTERFACE_PROPERTY_KEYS } from "../shared/batfish-interface-property-keys";
import { BatfishPropertiesFields, stringFromConfig } from "../shared/batfish-properties-fields";
import { BatfishInterfacePropertiesHelpPanel } from "./help-panel";

function BatfishInterfacePropertiesConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const interfaces = stringFromConfig(config, "interfaces");

  const handleInterfacesChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, interfaces: event.target.value });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <BatfishPropertiesFields
        config={config}
        onChange={onChange}
        suggestionKeys={BATFISH_INTERFACE_PROPERTY_KEYS}
        nodesHelpText="Optional. Leave empty to return interfaces on every node."
        extraFields={
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">interfaces</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={interfaces}
              onChange={handleInterfacesChange}
              placeholder="e.g. GigabitEthernet0/1"
              className="h-8 font-mono text-xs"
            />
            <p className="text-[11px] leading-4 text-muted-foreground">
              Optional. Leave empty to return every interface on the matched
              nodes.
            </p>
          </div>
        }
        emptyHelpText={
          <>
            When enabled, the <span className="font-mono">devices</span> outcome
            only carries nodes with at least one matching interface whose
            requested properties are empty — e.g. no description set. Requires{" "}
            <span className="font-mono">properties</span> above to be set.
          </>
        }
        matchModeHelpNoun="interface"
        outputKeyDefault="batfish_interface_properties"
      />
    </div>
  );
}

export const BatfishInterfacePropertiesPlugin: PluginUIComponent = {
  ConfigPanel: BatfishInterfacePropertiesConfigPanel,
  HelpPanel: BatfishInterfacePropertiesHelpPanel,
};
