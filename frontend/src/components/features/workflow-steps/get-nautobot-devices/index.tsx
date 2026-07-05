"use client";

import { useCallback, useMemo, useState } from "react";
import { Eye, FileText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
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
import { savedConditionsToFilterTree } from "./condition-builder/saved-conditions";
import {
  countConditions,
  emptyTree,
  type FilterTree,
} from "./condition-builder/types";
import { LoadInventoryDialog } from "./load-inventory-dialog";
import { DeviceSelectionPreviewDialog } from "./preview-dialog";
import type { SavedInventory } from "./types/saved-inventory";

interface FanOutConfig {
  enabled: boolean;
  mode: "per_device" | "chunked";
  chunk_size: number;
  max_concurrency: number;
}

const DEFAULT_FAN_OUT: FanOutConfig = {
  enabled: false,
  mode: "per_device",
  chunk_size: 1,
  max_concurrency: 0,
};

function fanOutFromConfig(config: Record<string, unknown>): FanOutConfig {
  const raw = config.fan_out;
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const f = raw as Record<string, unknown>;
    return {
      enabled: Boolean(f.enabled),
      mode: f.mode === "chunked" ? "chunked" : "per_device",
      chunk_size: typeof f.chunk_size === "number" ? Math.max(1, f.chunk_size) : 1,
      max_concurrency:
        typeof f.max_concurrency === "number" ? Math.max(0, f.max_concurrency) : 0,
    };
  }
  return DEFAULT_FAN_OUT;
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

function inventoryMetaFromConfig(config: Record<string, unknown>) {
  const id = typeof config.inventory_id === "number" ? config.inventory_id : null;
  const name =
    typeof config.inventory_name === "string" && config.inventory_name.trim()
      ? config.inventory_name.trim()
      : null;
  return { id, name };
}

function DeviceSelectionConfigPanel({
  config,
  onChange,
}: PluginConfigPanelProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const filterTree = useMemo(() => filterFromConfig(config), [config]);
  const fanOut = useMemo(() => fanOutFromConfig(config), [config]);
  const inventoryMeta = useMemo(() => inventoryMetaFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });

  const [sourceOpen, setSourceOpen] = useState(false);
  const [selectOpen, setSelectOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { inventory_source, ...rest } = config;
      onChange({ ...rest, [NAUTOBOT_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleInventorySelect = useCallback(
    (inventory: SavedInventory) => {
      onChange({
        ...config,
        inventory_id: inventory.id,
        inventory_name: inventory.name,
        device_filter: savedConditionsToFilterTree(inventory.conditions),
      });
    },
    [config, onChange],
  );

  const handleClearInventory = useCallback(() => {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { inventory_id, inventory_name, ...rest } = config;
    onChange({
      ...rest,
      device_filter: emptyTree(),
    });
  }, [config, onChange]);

  const handleFanOutChange = useCallback(
    (patch: Partial<FanOutConfig>) => {
      onChange({ ...config, fan_out: { ...fanOut, ...patch } });
    },
    [config, fanOut, onChange],
  );

  const conditionCount = useMemo(() => countConditions(filterTree), [filterTree]);
  const isSourceConfigured = isNautobotSourceConfigured(config);
  const hasInventory = inventoryMeta.id !== null || conditionCount > 0;
  const canPreview =
    hasInventory && credentials.isReady && Boolean(credentials.url && credentials.token);

  const inventoryLabel = inventoryMeta.name
    ? inventoryMeta.name
    : conditionCount > 0
      ? `${conditionCount} condition${conditionCount !== 1 ? "s" : ""} (legacy filter)`
      : null;

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
          <span className="font-mono text-xs font-medium">inventory</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            saved
          </Badge>
        </div>

        {inventoryLabel ? (
          <div className="flex items-start gap-2 rounded-md border border-teal-200 bg-teal-50/50 px-2.5 py-2">
            <FileText className="mt-0.5 size-3.5 shrink-0 text-teal-600" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-teal-900">{inventoryLabel}</p>
              {inventoryMeta.id !== null ? (
                <p className="text-[10px] text-teal-700/80">ID {inventoryMeta.id}</p>
              ) : null}
            </div>
          </div>
        ) : (
          <p className="text-[11px] text-muted-foreground">No inventory selected</p>
        )}

        <div className="flex gap-2">
          <Button
            className="h-7 flex-1 text-xs"
            size="sm"
            type="button"
            variant="outline"
            onClick={() => setSelectOpen(true)}
          >
            {inventoryLabel ? "Change inventory" : "Select inventory"}
          </Button>
          {inventoryLabel ? (
            <Button
              className="h-7 text-xs"
              size="sm"
              type="button"
              variant="ghost"
              onClick={handleClearInventory}
            >
              Clear
            </Button>
          ) : null}
        </div>

        <Button
          className="h-7 w-full text-xs"
          disabled={!canPreview}
          size="sm"
          type="button"
          variant="secondary"
          onClick={() => setPreviewOpen(true)}
        >
          <Eye className="mr-1.5 size-3.5" aria-hidden />
          Preview devices
        </Button>
        {!canPreview && hasInventory && !credentials.isReady ? (
          <p className="text-[11px] text-amber-600">Configure a Nautobot source to preview.</p>
        ) : null}
      </div>

      <div className="space-y-2 border-t pt-3">
        <div className="flex items-center justify-between">
          <span className="font-mono text-xs font-medium">fan_out</span>
          <Switch
            checked={fanOut.enabled}
            onCheckedChange={(checked) => handleFanOutChange({ enabled: checked })}
          />
        </div>
        <p className="text-[11px] text-muted-foreground">
          Process each device (or chunk) as an independent Hatchet child workflow.
        </p>

        {fanOut.enabled && (
          <div className="space-y-2 pl-1">
            <div className="space-y-1">
              <Label className="text-[11px] text-muted-foreground">Mode</Label>
              <Select
                value={fanOut.mode}
                onValueChange={(v) =>
                  handleFanOutChange({ mode: v as "per_device" | "chunked" })
                }
              >
                <SelectTrigger className="h-7 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="per_device">Per device (1 child per device)</SelectItem>
                  <SelectItem value="chunked">Chunked (N devices per child)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {fanOut.mode === "chunked" && (
              <div className="space-y-1">
                <Label className="text-[11px] text-muted-foreground">
                  Chunk size (devices per child)
                </Label>
                <Input
                  type="number"
                  min={1}
                  className="h-7 font-mono text-xs"
                  value={fanOut.chunk_size}
                  onChange={(e) =>
                    handleFanOutChange({ chunk_size: Math.max(1, Number(e.target.value)) })
                  }
                />
              </div>
            )}

            <div className="space-y-1">
              <Label className="text-[11px] text-muted-foreground">
                Max concurrency (0 = unlimited, 1 = sequential)
              </Label>
              <Input
                type="number"
                min={0}
                className="h-7 font-mono text-xs"
                value={fanOut.max_concurrency}
                onChange={(e) =>
                  handleFanOutChange({ max_concurrency: Math.max(0, Number(e.target.value)) })
                }
              />
            </div>
          </div>
        )}
      </div>

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />

      <LoadInventoryDialog
        open={selectOpen}
        onClose={() => setSelectOpen(false)}
        onLoad={handleInventorySelect}
      />

      <DeviceSelectionPreviewDialog
        open={previewOpen}
        config={{
          nautobot_url: credentials.url,
          nautobot_token: credentials.token,
          device_filter: filterTree,
        }}
        inventoryName={inventoryMeta.name}
        onClose={() => setPreviewOpen(false)}
      />
    </div>
  );
}

export const GetNautobotDevicesPlugin: PluginUIComponent = {
  ConfigPanel: DeviceSelectionConfigPanel,
};
