"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { DeviceSelectionPreviewDialog } from "./preview-dialog";

interface FilterRow {
  key: string;
  value: string;
}

const EMPTY_ROWS: FilterRow[] = [];

function filterRowsFromConfig(config: Record<string, unknown>): FilterRow[] {
  const raw = config.device_filter;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return EMPTY_ROWS;
  return Object.entries(raw as Record<string, unknown>).map(([key, value]) => ({
    key,
    value: String(value ?? ""),
  }));
}

function filterRowsToMap(rows: FilterRow[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const row of rows) {
    const k = row.key.trim();
    if (k) result[k] = row.value;
  }
  return result;
}

function DeviceSelectionConfigPanel({
  nodeId,
  config,
  onChange,
}: PluginConfigPanelProps) {
  const inventorySource = typeof config.inventory_source === "string"
    ? config.inventory_source
    : "";

  const [filterRows, setFilterRows] = useState<FilterRow[]>(() =>
    filterRowsFromConfig(config)
  );
  const [previewOpen, setPreviewOpen] = useState(false);

  const handleSourceChange = useCallback(
    (value: string) => {
      onChange({ ...config, inventory_source: value });
    },
    [config, onChange]
  );

  const handleFilterRowChange = useCallback(
    (index: number, field: "key" | "value", value: string) => {
      setFilterRows((prev: FilterRow[]) => {
        const updated = prev.map((row: FilterRow, i: number) =>
          i === index ? { ...row, [field]: value } : row
        );
        onChange({ ...config, device_filter: filterRowsToMap(updated) });
        return updated;
      });
    },
    [config, onChange]
  );

  const handleAddRow = useCallback(() => {
    setFilterRows((prev: FilterRow[]) => [...prev, { key: "", value: "" }]);
  }, []);

  const handleRemoveRow = useCallback(
    (index: number) => {
      setFilterRows((prev: FilterRow[]) => {
        const updated = prev.filter((_: FilterRow, i: number) => i !== index);
        onChange({ ...config, device_filter: filterRowsToMap(updated) });
        return updated;
      });
    },
    [config, onChange]
  );

  const currentConfig = useMemo(
    () => ({
      inventory_source: inventorySource,
      device_filter: filterRowsToMap(filterRows),
    }),
    [inventorySource, filterRows]
  );

  return (
    <div className="flex flex-col gap-4">
      {/* inventory_source */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <label
            className="font-mono text-xs font-medium"
            htmlFor={`${nodeId}-inventory-source`}
          >
            inventory_source
          </label>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
          <span className="ml-auto text-[10px] text-destructive">required</span>
        </div>
        <input
          className="w-full rounded border bg-background px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
          id={`${nodeId}-inventory-source`}
          onChange={(e) => handleSourceChange(e.target.value)}
          placeholder="nautobot"
          type="text"
          value={inventorySource}
        />
        <p className="text-[11px] text-muted-foreground">
          Inventory provider used to resolve target devices.
        </p>
      </div>

      {/* device_filter */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">device_filter</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            object
          </Badge>
          <span className="ml-auto text-[10px] text-destructive">required</span>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Filter expression that selects devices for this workflow.
        </p>
        <div className="space-y-1.5">
          {filterRows.map((row: FilterRow, index: number) => (
            <div className="flex items-center gap-1" key={index}>
              <input
                aria-label="Filter key"
                className="w-2/5 rounded border bg-background px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                onChange={(e) =>
                  handleFilterRowChange(index, "key", e.target.value)
                }
                placeholder="site"
                type="text"
                value={row.key}
              />
              <span className="shrink-0 text-[10px] text-muted-foreground">=</span>
              <input
                aria-label="Filter value"
                className="min-w-0 flex-1 rounded border bg-background px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                onChange={(e) =>
                  handleFilterRowChange(index, "value", e.target.value)
                }
                placeholder="dc1"
                type="text"
                value={row.value}
              />
              <Button
                aria-label="Remove filter row"
                className="h-6 w-6 shrink-0 p-0 text-muted-foreground hover:text-destructive"
                onClick={() => handleRemoveRow(index)}
                size="sm"
                type="button"
                variant="ghost"
              >
                ×
              </Button>
            </div>
          ))}
          <Button
            className="h-6 w-full text-[11px]"
            onClick={handleAddRow}
            size="sm"
            type="button"
            variant="outline"
          >
            + Add filter
          </Button>
        </div>
      </div>

      {/* Preview action */}
      <div className="mt-2 border-t pt-3">
        <Button
          className="w-full"
          onClick={() => setPreviewOpen(true)}
          size="sm"
          type="button"
          variant="secondary"
        >
          Preview Selection
        </Button>
        <p className="mt-1.5 text-center text-[11px] text-muted-foreground">
          Query Nautobot for devices matching the current filter.
        </p>
      </div>

      <DeviceSelectionPreviewDialog
        config={currentConfig}
        onClose={() => setPreviewOpen(false)}
        open={previewOpen}
      />
    </div>
  );
}

export const DeviceSelectionPlugin: PluginUIComponent = {
  ConfigPanel: DeviceSelectionConfigPanel,
};
