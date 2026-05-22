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
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const selected = useMemo(() => parseAttributes(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });

  const [sourceOpen, setSourceOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { inventory_source, ...rest } = config;
      onChange({ ...rest, [NAUTOBOT_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleChange = useCallback(
    (newSelected: AttributeGroupKey[]) => {
      onChange({ ...config, list_of_attributes: newSelected });
    },
    [config, onChange],
  );

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

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
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
