"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

import { EMPTY_WORKFLOW_NODES } from "@/components/features/workflows/constants/empty-canvas";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
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
import { ContentSourcePicker } from "@/components/features/workflow-steps/shared/content-source-picker";
import { listUpstreamSourceSteps } from "@/components/features/workflow-steps/shared/upstream-source-steps";

import { UploadConfigHelpPanel } from "./help-panel";
import {
  UPLOAD_CONFIG_SOURCE_OPTIONS,
  MAX_SOCKET_TIMEOUT,
  MIN_SOCKET_TIMEOUT,
  buildUploadConfigConfig,
  needsParsedOutputKey,
  needsSourceStepNodeId,
  sourceStepCopy,
  type ContentSource,
} from "./upload-config-config";
import { SshCredentialField } from "@/components/features/workflow-steps/shared/ssh-credential-field";
import {
  UploadConfigSocketTimeoutFields,
  UploadConfigTransferFields,
} from "./upload-config-fields";

function UploadConfigConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes = EMPTY_WORKFLOW_NODES,
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (config.content_source === undefined) {
      onChange(buildUploadConfigConfig(config));
    }
  }, [nodeId, config, onChange]);

  const contentSource = (config.content_source as ContentSource) || "updated_content";
  const sourceStepNodeId =
    typeof config.source_step_node_id === "string" ? config.source_step_node_id : "";
  const parsedOutputKey =
    typeof config.parsed_output_key === "string" ? config.parsed_output_key : "";
  const destinationFilename =
    typeof config.destination_filename === "string" ? config.destination_filename : "";
  const fileSystem = typeof config.file_system === "string" ? config.file_system : "";
  const overwrite = config.overwrite === true;
  const inlineTransfer = config.inline_transfer === true;
  const networkDriverOverride =
    typeof config.network_driver_override === "string" ? config.network_driver_override : "";
  const socketTimeout =
    typeof config.socket_timeout === "number" && Number.isFinite(config.socket_timeout)
      ? config.socket_timeout
      : MIN_SOCKET_TIMEOUT;

  const stepNodeIdRequired = needsSourceStepNodeId(contentSource);
  const outputKeyNeeded = needsParsedOutputKey(contentSource);
  const copy = sourceStepCopy(contentSource);

  const sourceSteps = useMemo(
    () => listUpstreamSourceSteps(workflowNodes, contentSource, nodeId),
    [workflowNodes, contentSource, nodeId],
  );
  const selectedSourceStep = useMemo(
    () => sourceSteps.find((step) => step.nodeId === sourceStepNodeId) ?? null,
    [sourceSteps, sourceStepNodeId],
  );

  const contentSourceHint = useMemo(
    () => UPLOAD_CONFIG_SOURCE_OPTIONS.find((option) => option.value === contentSource)?.hint,
    [contentSource],
  );

  const handleContentSourceChange = useCallback(
    (value: string) => {
      onChange(
        buildUploadConfigConfig(config, {
          content_source: value,
          source_step_node_id: "",
          parsed_output_key: "",
        }),
      );
    },
    [config, onChange],
  );

  const handleSourceStepSelect = useCallback(
    (selectedNodeId: string) => {
      const step = sourceSteps.find((candidate) => candidate.nodeId === selectedNodeId);
      const patch: Record<string, unknown> = { source_step_node_id: selectedNodeId };
      if (outputKeyNeeded && step?.outputKey) {
        const currentKey = parsedOutputKey.trim();
        if (!currentKey) {
          patch.parsed_output_key = step.outputKey;
        }
      }
      onChange(buildUploadConfigConfig(config, patch));
    },
    [config, onChange, outputKeyNeeded, parsedOutputKey, sourceSteps],
  );

  useEffect(() => {
    if (!stepNodeIdRequired || sourceSteps.length !== 1 || sourceStepNodeId) {
      return;
    }
    handleSourceStepSelect(sourceSteps[0].nodeId);
  }, [stepNodeIdRequired, sourceStepNodeId, sourceSteps, handleSourceStepSelect]);

  const handleSourceStepNodeIdChange = useCallback(
    (value: string) => {
      onChange(buildUploadConfigConfig(config, { source_step_node_id: value }));
    },
    [config, onChange],
  );

  const handleParsedOutputKeyChange = useCallback(
    (value: string) => {
      onChange(buildUploadConfigConfig(config, { parsed_output_key: value }));
    },
    [config, onChange],
  );

  const handleDestinationFilenameChange = useCallback(
    (value: string) => {
      onChange(buildUploadConfigConfig(config, { destination_filename: value }));
    },
    [config, onChange],
  );

  const handleFileSystemChange = useCallback(
    (value: string) => {
      onChange(buildUploadConfigConfig(config, { file_system: value }));
    },
    [config, onChange],
  );

  const handleOverwriteChange = useCallback(
    (checked: boolean) => {
      onChange(buildUploadConfigConfig(config, { overwrite: checked }));
    },
    [config, onChange],
  );

  const handleInlineTransferChange = useCallback(
    (checked: boolean) => {
      onChange(buildUploadConfigConfig(config, { inline_transfer: checked }));
    },
    [config, onChange],
  );

  const handleDriverOverrideChange = useCallback(
    (value: string) => {
      onChange(buildUploadConfigConfig(config, { network_driver_override: value }));
    },
    [config, onChange],
  );

  const handleSocketTimeoutChange = useCallback(
    (value: string) => {
      const parsed = Number.parseInt(value, 10);
      const clamped = Number.isFinite(parsed)
        ? Math.min(MAX_SOCKET_TIMEOUT, Math.max(MIN_SOCKET_TIMEOUT, parsed))
        : MIN_SOCKET_TIMEOUT;
      onChange(buildUploadConfigConfig(config, { socket_timeout: clamped }));
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <SshCredentialField config={config} onChange={onChange} />

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">content_source</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <ContentSourcePicker
          value={contentSource}
          onChange={handleContentSourceChange}
          options={UPLOAD_CONFIG_SOURCE_OPTIONS}
        />
        {contentSourceHint ? (
          <p className="text-[11px] text-muted-foreground">{contentSourceHint}</p>
        ) : null}
      </div>

      {stepNodeIdRequired ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">source_step_node_id</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              step
            </Badge>
          </div>
          {sourceSteps.length > 0 ? (
            <Select value={sourceStepNodeId || ""} onValueChange={handleSourceStepSelect}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue placeholder={copy.placeholder} />
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
            <p className="text-[11px] text-warning-foreground">{copy.missingStep}</p>
          )}
          {selectedSourceStep ? (
            <p className="text-[11px] text-muted-foreground">
              Selected <span className="font-mono">{selectedSourceStep.nodeId}</span>
              {selectedSourceStep.outputKey ? ` · output_key ${selectedSourceStep.outputKey}` : ""}
            </p>
          ) : sourceStepNodeId && sourceSteps.length > 0 ? (
            <p className="text-[11px] text-warning-foreground">
              Saved node id <span className="font-mono">{sourceStepNodeId}</span> is not on this
              canvas. Pick a step above or enter an id manually.
            </p>
          ) : null}
          <details className="rounded-lg border bg-muted/20 px-3 py-2">
            <summary className="cursor-pointer text-[11px] font-medium text-muted-foreground">
              Advanced: enter node id manually
            </summary>
            <div className="mt-2 space-y-1.5">
              <Input
                value={sourceStepNodeId}
                onChange={(event) => handleSourceStepNodeIdChange(event.target.value)}
                placeholder={copy.manualPlaceholder}
                className="h-8 font-mono text-xs"
              />
              <p className="text-[11px] text-muted-foreground">
                Only needed when reusing an id from an older workflow or run results.
              </p>
            </div>
          </details>
        </div>
      ) : null}

      {outputKeyNeeded ? (
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
            placeholder={contentSource === "pyats_snapshot" ? "pyats_snapshot" : "device_config"}
            className="h-8 font-mono text-xs"
          />
          <p className="text-[11px] text-muted-foreground">
            Optional output_key from the source step. Leave empty to use the content produced by
            the selected step.
          </p>
        </div>
      ) : null}

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">destination_filename</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={destinationFilename}
          onChange={(event) => handleDestinationFilenameChange(event.target.value)}
          placeholder="startup-config-new.cfg"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Target filename on the device filesystem.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">file_system</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={fileSystem}
          onChange={(event) => handleFileSystemChange(event.target.value)}
          placeholder="bootflash:"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Destination filesystem on the device, e.g. bootflash:, flash:, or nvram:.
        </p>
      </div>

      <UploadConfigTransferFields
        overwrite={overwrite}
        inlineTransfer={inlineTransfer}
        onOverwriteChange={handleOverwriteChange}
        onInlineTransferChange={handleInlineTransferChange}
      />

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">network_driver_override</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={networkDriverOverride}
          onChange={(event) => handleDriverOverrideChange(event.target.value)}
          placeholder="cisco_ios (optional)"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Overrides each device&apos;s network driver for Netmiko in this step.
        </p>
      </div>

      <UploadConfigSocketTimeoutFields
        socketTimeout={socketTimeout}
        onSocketTimeoutChange={handleSocketTimeoutChange}
      />
    </div>
  );
}

export const UploadConfigPlugin: PluginUIComponent = {
  ConfigPanel: UploadConfigConfigPanel,
  HelpPanel: UploadConfigHelpPanel,
};
