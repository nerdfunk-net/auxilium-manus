"use client";

import { Search } from "lucide-react";
import { useCallback, useState } from "react";

import {
  EMPTY_WORKFLOW_EDGES,
  EMPTY_WORKFLOW_NODES,
} from "@/components/features/workflows/constants/empty-canvas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { AttributePathPicker } from "@/components/features/workflow-steps/shared/attribute-path-picker";

import { GetFromDbHelpPanel } from "./help-panel";

export function buildGetFromDbConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    storage_key: typeof config.storage_key === "string" ? config.storage_key : "",
    destination_path:
      typeof config.destination_path === "string" ? config.destination_path : "",
    ...patch,
  };
}

function GetFromDbConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes = EMPTY_WORKFLOW_NODES,
  workflowEdges = EMPTY_WORKFLOW_EDGES,
}: PluginConfigPanelProps) {
  const [pickerOpen, setPickerOpen] = useState(false);

  const storageKey = typeof config.storage_key === "string" ? config.storage_key : "";
  const destinationPath =
    typeof config.destination_path === "string" ? config.destination_path : "";

  const handleStorageKeyChange = useCallback(
    (value: string) => onChange(buildGetFromDbConfig(config, { storage_key: value })),
    [config, onChange],
  );

  const handleDestinationPathChange = useCallback(
    (value: string) => onChange(buildGetFromDbConfig(config, { destination_path: value })),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">storage_key</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={storageKey}
          onChange={(event) => handleStorageKeyChange(event.target.value)}
          placeholder="site_backup"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Key the data was stored under by the Store in DB step. Looked up per
          device name; a device with no record under this key fails.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">destination_path</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <div className="flex items-center gap-1.5">
          <Input
            value={destinationPath}
            onChange={(event) => handleDestinationPathChange(event.target.value)}
            placeholder="stored.site_backup"
            className="h-8 font-mono text-xs"
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8 shrink-0"
            onClick={() => setPickerOpen(true)}
            title="Browse attributes"
          >
            <Search className="size-3.5" />
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Attribute the stored data is written to (bag.field). Existing values at
          this path are overwritten. Cannot target parsed.* or run_input.*.
        </p>

        <AttributePathPicker
          open={pickerOpen}
          onClose={() => setPickerOpen(false)}
          onSelect={(path) => handleDestinationPathChange(path)}
          nodeId={nodeId}
          workflowNodes={workflowNodes}
          workflowEdges={workflowEdges}
        />
      </div>
    </div>
  );
}

export const GetFromDbPlugin: PluginUIComponent = {
  ConfigPanel: GetFromDbConfigPanel,
  HelpPanel: GetFromDbHelpPanel,
};
