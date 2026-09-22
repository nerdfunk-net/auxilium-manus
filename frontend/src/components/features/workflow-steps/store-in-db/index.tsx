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
import { Label } from "@/components/ui/label";
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
import { AttributePathPicker } from "@/components/features/workflow-steps/shared/attribute-path-picker";
import { listUpstreamSourceSteps } from "@/components/features/workflow-steps/shared/upstream-source-steps";

import { StoreInDbHelpPanel } from "./help-panel";

type ContentSource = "device_data" | "attribute_bags" | "single_attribute" | "rendered_template";

const CONTENT_SOURCE_OPTIONS: { value: ContentSource; label: string; hint: string }[] = [
  {
    value: "device_data",
    label: "Device data",
    hint: "Attribute bags + parsed output (everything the device has accumulated).",
  },
  {
    value: "attribute_bags",
    label: "Attribute bags",
    hint: "All namespaced attribute bags only (e.g. nautobot, git), not parsed output.",
  },
  {
    value: "single_attribute",
    label: "Single attribute",
    hint: "One resolved attribute path.",
  },
  {
    value: "rendered_template",
    label: "Rendered template",
    hint: "Output of an upstream Render Jinja Template step.",
  },
];

export function buildStoreInDbConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  const contentSource = CONTENT_SOURCE_OPTIONS.some((option) => option.value === config.content_source)
    ? (config.content_source as ContentSource)
    : "device_data";
  return {
    storage_key: typeof config.storage_key === "string" ? config.storage_key : "",
    content_source: contentSource,
    attribute_path: typeof config.attribute_path === "string" ? config.attribute_path : "",
    allow_secret_storage: config.allow_secret_storage === true,
    source_step_node_id:
      typeof config.source_step_node_id === "string" ? config.source_step_node_id : "",
    parsed_output_key:
      typeof config.parsed_output_key === "string" ? config.parsed_output_key : "",
    ...patch,
  };
}

function StoreInDbConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes = EMPTY_WORKFLOW_NODES,
  workflowEdges = EMPTY_WORKFLOW_EDGES,
}: PluginConfigPanelProps) {
  const [pickerOpen, setPickerOpen] = useState(false);

  const storageKey = typeof config.storage_key === "string" ? config.storage_key : "";
  const contentSource = CONTENT_SOURCE_OPTIONS.some((option) => option.value === config.content_source)
    ? (config.content_source as ContentSource)
    : "device_data";
  const attributePath = typeof config.attribute_path === "string" ? config.attribute_path : "";
  const sourceStepNodeId =
    typeof config.source_step_node_id === "string" ? config.source_step_node_id : "";
  const parsedOutputKey =
    typeof config.parsed_output_key === "string" ? config.parsed_output_key : "";
  const allowSecretStorage = config.allow_secret_storage === true;

  const selectedHint = CONTENT_SOURCE_OPTIONS.find((option) => option.value === contentSource)?.hint;

  const sourceSteps = listUpstreamSourceSteps(workflowNodes, "rendered_template", nodeId);

  const handleStorageKeyChange = useCallback(
    (value: string) => onChange(buildStoreInDbConfig(config, { storage_key: value })),
    [config, onChange],
  );

  const handleContentSourceChange = useCallback(
    (value: string) => onChange(buildStoreInDbConfig(config, { content_source: value })),
    [config, onChange],
  );

  const handleAttributePathChange = useCallback(
    (value: string) => onChange(buildStoreInDbConfig(config, { attribute_path: value })),
    [config, onChange],
  );

  const handleAllowSecretStorageChange = useCallback(
    (value: boolean) => onChange(buildStoreInDbConfig(config, { allow_secret_storage: value })),
    [config, onChange],
  );

  const handleSourceStepSelect = useCallback(
    (selectedNodeId: string) => {
      const step = sourceSteps.find((candidate) => candidate.nodeId === selectedNodeId);
      const patch: Record<string, unknown> = { source_step_node_id: selectedNodeId };
      if (step?.outputKey && !parsedOutputKey.trim()) {
        patch.parsed_output_key = step.outputKey;
      }
      onChange(buildStoreInDbConfig(config, patch));
    },
    [config, onChange, parsedOutputKey, sourceSteps],
  );

  const handleSourceStepNodeIdChange = useCallback(
    (value: string) => onChange(buildStoreInDbConfig(config, { source_step_node_id: value })),
    [config, onChange],
  );

  const handleParsedOutputKeyChange = useCallback(
    (value: string) => onChange(buildStoreInDbConfig(config, { parsed_output_key: value })),
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
          Key this device&apos;s data is stored under. A later Read from DB step reads
          by this key.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">content_source</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={contentSource} onValueChange={handleContentSourceChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CONTENT_SOURCE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {selectedHint ? (
          <p className="text-[11px] text-muted-foreground">{selectedHint}</p>
        ) : null}
      </div>

      {contentSource === "single_attribute" ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">attribute_path</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <div className="flex items-center gap-1.5">
            <Input
              value={attributePath}
              onChange={(event) => handleAttributePathChange(event.target.value)}
              placeholder="nautobot.role.name"
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
            Dot path to the value to store. A path resolving to a secret-valued
            attribute (e.g. a device password) fails the device unless
            allow_secret_storage is enabled below.
          </p>

          <div className="flex items-start gap-2 rounded-lg border border-warning-border bg-warning px-3 py-2">
            <input
              id="store-in-db-allow-secret-storage"
              type="checkbox"
              checked={allowSecretStorage}
              onChange={(event) => handleAllowSecretStorageChange(event.target.checked)}
              className="mt-0.5 size-4 shrink-0 rounded border"
            />
            <Label
              htmlFor="store-in-db-allow-secret-storage"
              className="text-[11px] font-medium leading-4 text-warning-foreground"
            >
              Write secret-valued attribute to database. I am aware of and accept the
              risk.
            </Label>
          </div>

          <AttributePathPicker
            open={pickerOpen}
            onClose={() => setPickerOpen(false)}
            onSelect={(path) => handleAttributePathChange(path)}
            nodeId={nodeId}
            workflowNodes={workflowNodes}
            workflowEdges={workflowEdges}
          />
        </div>
      ) : null}

      {contentSource === "rendered_template" ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">source_step</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              step
            </Badge>
          </div>
          {sourceSteps.length > 0 ? (
            <Select value={sourceStepNodeId || ""} onValueChange={handleSourceStepSelect}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue placeholder="Choose render step…" />
              </SelectTrigger>
              <SelectContent>
                {sourceSteps.map((step) => (
                  <SelectItem key={step.nodeId} value={step.nodeId}>
                    {step.title} ({step.nodeId})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <p className="text-[11px] text-warning-foreground">
              Add a Render Jinja Template step to this workflow first.
            </p>
          )}
          <details className="rounded-lg border bg-muted/20 px-3 py-2">
            <summary className="cursor-pointer text-[11px] font-medium text-muted-foreground">
              Advanced: enter node id manually
            </summary>
            <div className="mt-2 space-y-1.5">
              <Input
                value={sourceStepNodeId}
                onChange={(event) => handleSourceStepNodeIdChange(event.target.value)}
                placeholder="render-jinja-template-3"
                className="h-8 font-mono text-xs"
              />
              <p className="text-[11px] text-muted-foreground">
                Only needed when reusing an id from an older workflow or run results.
              </p>
            </div>
          </details>

          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">parsed_output_key</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={parsedOutputKey}
              onChange={(event) => handleParsedOutputKeyChange(event.target.value)}
              placeholder="device_config"
              className="h-8 font-mono text-xs"
            />
            <p className="text-[11px] text-muted-foreground">
              Optional output_key from the render step. Leave empty to store all
              templates produced by the selected step, keyed by output_key.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export const StoreInDbPlugin: PluginUIComponent = {
  ConfigPanel: StoreInDbConfigPanel,
  HelpPanel: StoreInDbHelpPanel,
};
