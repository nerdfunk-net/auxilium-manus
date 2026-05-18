"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { InventoryBuilderDialog } from "./inventory-builder-dialog";
import { InventorySourceDialog, type InventorySource } from "./inventory-source-dialog";
import {
  emptyTree,
  countConditions,
  type FilterTree,
} from "./condition-builder/types";

const EMPTY_SOURCE: InventorySource = { url: "", token: "" };

function sourceFromConfig(config: Record<string, unknown>): InventorySource {
  const raw = config.inventory_source;
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const s = raw as Record<string, unknown>;
    return {
      url: typeof s.url === "string" ? s.url : "",
      token: typeof s.token === "string" ? s.token : "",
    };
  }
  return EMPTY_SOURCE;
}

function filterFromConfig(config: Record<string, unknown>): FilterTree {
  const raw = config.device_filter;
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const f = raw as Record<string, unknown>;
    if (Array.isArray(f.items)) {
      return raw as FilterTree;
    }
  }
  return emptyTree();
}

function DeviceSelectionConfigPanel({
  nodeId,
  config,
  onChange,
}: PluginConfigPanelProps) {
  const source = useMemo(() => sourceFromConfig(config), [config]);
  const filterTree = useMemo(() => filterFromConfig(config), [config]);

  const [sourceOpen, setSourceOpen] = useState(false);
  const [builderOpen, setBuilderOpen] = useState(false);

  const handleSourceChange = useCallback(
    (newSource: InventorySource) => {
      onChange({ ...config, inventory_source: newSource });
    },
    [config, onChange],
  );

  const handleFilterApply = useCallback(
    (tree: FilterTree) => {
      onChange({ ...config, device_filter: tree });
    },
    [config, onChange],
  );

  const conditionCount = useMemo(() => countConditions(filterTree), [filterTree]);
  const isSourceConfigured = Boolean(source.url && source.token);

  return (
    <div className="flex flex-col gap-4">
      {/* Inventory Source */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">inventory_source</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            nautobot
          </Badge>
        </div>

        {isSourceConfigured ? (
          <p className="truncate text-[11px] text-muted-foreground">{source.url}</p>
        ) : (
          <p className="text-[11px] text-amber-600">Not configured</p>
        )}

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setSourceOpen(true)}
        >
          {isSourceConfigured ? "Edit Source" : "Configure Source"}
        </Button>
      </div>

      {/* Device Filter */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">device_filter</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            filter tree
          </Badge>
        </div>

        {conditionCount > 0 ? (
          <p className="text-[11px] text-muted-foreground">
            {conditionCount} condition{conditionCount !== 1 ? "s" : ""} configured
          </p>
        ) : (
          <p className="text-[11px] text-muted-foreground">No filter configured — all devices</p>
        )}

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setBuilderOpen(true)}
        >
          {conditionCount > 0 ? "Edit Filter" : "+ Add Filter"}
        </Button>
      </div>

      {/* Dialogs */}
      <InventorySourceDialog
        open={sourceOpen}
        onClose={() => setSourceOpen(false)}
        value={source}
        onChange={handleSourceChange}
      />

      <InventoryBuilderDialog
        open={builderOpen}
        onClose={() => setBuilderOpen(false)}
        nautobot_url={source.url}
        nautobot_token={source.token}
        initialTree={filterTree}
        onApply={handleFilterApply}
      />
    </div>
  );
}

export const DeviceSelectionPlugin: PluginUIComponent = {
  ConfigPanel: DeviceSelectionConfigPanel,
};
