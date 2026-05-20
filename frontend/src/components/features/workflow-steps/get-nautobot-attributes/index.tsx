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
  const selected = useMemo(() => parseAttributes(config), [config]);
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleChange = useCallback(
    (newSelected: AttributeGroupKey[]) => {
      onChange({ ...config, list_of_attributes: newSelected });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
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
