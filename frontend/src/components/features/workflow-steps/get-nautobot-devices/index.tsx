"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";

import {
  NAUTOBOT_SOURCE_ID_KEY,
  isNautobotSourceConfigured,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import { InventoryBuilderDialog } from "./inventory-builder-dialog";
import {
  emptyTree,
  countConditions,
  type FilterTree,
} from "./condition-builder/types";

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
  config,
  onChange,
}: PluginConfigPanelProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const filterTree = useMemo(() => filterFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });

  const [sourceOpen, setSourceOpen] = useState(false);
  const [builderOpen, setBuilderOpen] = useState(false);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { inventory_source, ...rest } = config;
      onChange({ ...rest, [NAUTOBOT_SOURCE_ID_KEY]: newSourceId });
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
  const isSourceConfigured = isNautobotSourceConfigured(config);

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">
            {NAUTOBOT_SOURCE_ID_KEY}
          </span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            nautobot
          </Badge>
        </div>

        {isSourceConfigured ? (
          <p className="font-mono text-[11px] text-muted-foreground">
            {sourceId}
            {credentials.isReady ? (
              <span className="block truncate font-sans text-muted-foreground">
                {credentials.url}
              </span>
            ) : credentials.isLoading ? (
              <span className="block font-sans">Loading credentials…</span>
            ) : (
              <span className="block font-sans text-amber-600">
                Source not found in settings
              </span>
            )}
          </p>
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
          <p className="text-[11px] text-muted-foreground">
            No filter configured — all devices
          </p>
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

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />

      <InventoryBuilderDialog
        open={builderOpen}
        onClose={() => setBuilderOpen(false)}
        nautobot_url={credentials.url}
        nautobot_token={credentials.token}
        initialTree={filterTree}
        onApply={handleFilterApply}
      />
    </div>
  );
}

export const GetNautobotDevicesPlugin: PluginUIComponent = {
  ConfigPanel: DeviceSelectionConfigPanel,
};
