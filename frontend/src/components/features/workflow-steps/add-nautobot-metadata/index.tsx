"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import type {
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "@/components/features/workflows/types/workflow-canvas";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";

import {
  NAUTOBOT_SOURCE_ID_KEY,
  isNautobotSourceConfigured,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import { AddNautobotMetadataDialog } from "./add-nautobot-metadata-dialog";
import {
  DEFAULT_DEVICE_TYPE,
  DEFAULT_LOCATION,
  DEFAULT_METADATA_TYPE,
  metadataTypeFromConfig,
  missingRequiredFields,
  valuesForType,
} from "./add-nautobot-metadata-config";
import { AddNautobotMetadataHelpPanel } from "./help-panel";
import {
  METADATA_TYPE_OPTIONS,
  type AddNautobotMetadataConfig,
  type MetadataType,
  type MetadataValues,
} from "./types";

const EMPTY_NODES: PersistedCanvasNode[] = [];
const EMPTY_EDGES: WorkflowCanvasEdge[] = [];

function AddNautobotMetadataConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes = EMPTY_NODES,
  workflowEdges = EMPTY_EDGES,
}: PluginConfigPanelProps) {
  const metadataConfig = config as AddNautobotMetadataConfig;
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });
  const metadataType = metadataTypeFromConfig(metadataConfig);

  const [sourceOpen, setSourceOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);

  // Seed a fresh node once so the saved config always carries metadata_type + both sections.
  const initializedForNode = useRef<string | null>(null);
  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!metadataConfig.metadata_type || !metadataConfig.location || !metadataConfig.device_type) {
      onChange({
        ...config,
        metadata_type: metadataConfig.metadata_type ?? DEFAULT_METADATA_TYPE,
        location: metadataConfig.location ?? DEFAULT_LOCATION,
        device_type: metadataConfig.device_type ?? DEFAULT_DEVICE_TYPE,
      });
    }
  }, [nodeId, config, metadataConfig, onChange]);

  const values = useMemo(
    () => valuesForType(metadataConfig, metadataType),
    [metadataConfig, metadataType],
  );
  const missing = useMemo(() => missingRequiredFields(metadataType, values), [metadataType, values]);
  const typeLabel =
    METADATA_TYPE_OPTIONS.find((option) => option.value === metadataType)?.label ?? metadataType;

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => onChange({ ...config, [NAUTOBOT_SOURCE_ID_KEY]: newSourceId }),
    [config, onChange],
  );

  const handleTypeChange = useCallback(
    (next: string) => onChange({ ...config, metadata_type: next as MetadataType }),
    [config, onChange],
  );

  const handleDialogSave = useCallback(
    (next: MetadataValues) => {
      onChange({ ...config, [metadataType]: next });
      setDialogOpen(false);
    },
    [config, metadataType, onChange],
  );

  const handleCloseSource = useCallback(() => setSourceOpen(false), []);
  const handleCloseDialog = useCallback(() => setDialogOpen(false), []);
  const isSourceConfigured = isNautobotSourceConfigured(config);

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{NAUTOBOT_SOURCE_ID_KEY}</span>
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
              <span className="block font-sans text-warning-foreground">
                Source not found in settings
              </span>
            )}
          </p>
        ) : (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
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
          <span className="font-mono text-xs font-medium">metadata_type</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            select
          </Badge>
        </div>
        <Select value={metadataType} onValueChange={handleTypeChange}>
          <SelectTrigger
            className="h-7 w-full text-xs focus:ring-step/40"
            aria-label="Metadata type"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {METADATA_TYPE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value} className="text-xs">
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{metadataType}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            object
          </Badge>
        </div>

        {missing.length === 0 ? (
          <p className="truncate text-[11px] text-muted-foreground">
            {typeLabel}: required fields set
          </p>
        ) : (
          <p className="text-[11px] text-warning-foreground">Missing: {missing.join(", ")}</p>
        )}

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setDialogOpen(true)}
        >
          Edit {typeLabel}
        </Button>
      </div>

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={handleCloseSource}
        onSave={handleSourceIdChange}
      />

      <AddNautobotMetadataDialog
        // Remount per type so the draft always starts from that type's saved values.
        key={metadataType}
        open={dialogOpen}
        metadataType={metadataType}
        value={values}
        sourceId={sourceId}
        nodeId={nodeId}
        workflowNodes={workflowNodes}
        workflowEdges={workflowEdges}
        onClose={handleCloseDialog}
        onSave={handleDialogSave}
      />
    </div>
  );
}

export const AddNautobotMetadataPlugin: PluginUIComponent = {
  ConfigPanel: AddNautobotMetadataConfigPanel,
  HelpPanel: AddNautobotMetadataHelpPanel,
};
