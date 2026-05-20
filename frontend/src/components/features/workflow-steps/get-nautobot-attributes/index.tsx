"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { AttributesDialog } from "./attributes-dialog";
import { ATTRIBUTE_GROUPS, type AttributeGroupKey } from "./types";
import {
  InventorySourceDialog,
  type InventorySource,
} from "../get-nautobot-devices/inventory-source-dialog";

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

function parseAttributes(config: Record<string, unknown>): AttributeGroupKey[] {
  const raw = config.list_of_attributes;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (item): item is AttributeGroupKey =>
      typeof item === "string" && ATTRIBUTE_GROUPS.some((g) => g.key === item),
  );
}

function GetNautobotAttributesConfigPanel({
  config,
  onChange,
}: PluginConfigPanelProps) {
  const source = useMemo(() => sourceFromConfig(config), [config]);
  const selected = useMemo(() => parseAttributes(config), [config]);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleSourceChange = useCallback(
    (newSource: InventorySource) => {
      onChange({ ...config, inventory_source: newSource });
    },
    [config, onChange],
  );

  const handleChange = useCallback(
    (newSelected: AttributeGroupKey[]) => {
      onChange({ ...config, list_of_attributes: newSelected });
    },
    [config, onChange],
  );

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

      {/* Attributes */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">list_of_attributes</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string_list
          </Badge>
        </div>

        {selected.length > 0 ? (
          <p className="text-[11px] text-muted-foreground">
            {selected.length} group{selected.length !== 1 ? "s" : ""} selected
          </p>
        ) : (
          <p className="text-[11px] text-amber-600">No attributes selected</p>
        )}

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setDialogOpen(true)}
        >
          Edit Attributes
        </Button>
      </div>

      <InventorySourceDialog
        open={sourceOpen}
        onClose={() => setSourceOpen(false)}
        value={source}
        onChange={handleSourceChange}
      />

      <AttributesDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        value={selected}
        onChange={handleChange}
      />
    </div>
  );
}

export const GetNautobotAttributesPlugin: PluginUIComponent = {
  ConfigPanel: GetNautobotAttributesConfigPanel,
};
