"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

import { EMPTY_WORKFLOW_NODES } from "@/components/features/workflows/constants/empty-canvas";
import { Badge } from "@/components/ui/badge";
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
import { useCredentialsQuery } from "@/components/features/settings/credentials/hooks/use-credentials-query";
import { listUpstreamSourceSteps } from "@/components/features/workflow-steps/shared/upstream-source-steps";

import { UploadConfigHelpPanel } from "./help-panel";
import {
  CONTENT_SOURCE_OPTIONS,
  MAX_SOCKET_TIMEOUT,
  MIN_SOCKET_TIMEOUT,
  buildUploadConfigConfig,
  needsParsedOutputKey,
  needsSourceStepNodeId,
  sourceStepCopy,
  type ContentSource,
} from "./upload-config-config";

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

  const { data, isLoading } = useCredentialsQuery();
  const sshCredentials = useMemo(
    () =>
      (data?.credentials ?? []).filter(
        (credential) => credential.type === "ssh" && credential.status !== "expired",
      ),
    [data?.credentials],
  );

  const credentialReference =
    typeof config.credential_reference === "string" ? config.credential_reference : "";
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
    () => CONTENT_SOURCE_OPTIONS.find((option) => option.value === contentSource)?.hint,
    [contentSource],
  );

  const handleCredentialChange = useCallback(
    (value: string) => {
      onChange(buildUploadConfigConfig(config, { credential_reference: value }));
    },
    [config, onChange],
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
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">credential_reference</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            credential_ref
          </Badge>
        </div>

        {isLoading ? (
          <p className="text-[11px] text-muted-foreground">Loading credentials…</p>
        ) : sshCredentials.length === 0 && !credentialReference ? (
          <p className="text-[11px] text-warning-foreground">
            No SSH credentials in Settings → Credentials
          </p>
        ) : (
          <Select value={credentialReference} onValueChange={handleCredentialChange}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Select SSH credential" />
            </SelectTrigger>
            <SelectContent>
              {credentialReference &&
                !sshCredentials.some((credential) => credential.name === credentialReference) && (
                  <SelectItem value={credentialReference} disabled>
                    {credentialReference} (not accessible)
                  </SelectItem>
                )}
              {sshCredentials.map((credential) => (
                <SelectItem key={credential.id} value={credential.name}>
                  {credential.name} ({credential.username})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
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
            <Select value={sourceStepNodeId || undefined} onValueChange={handleSourceStepSelect}>
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
            Optional output_key from the source step. Leave empty to use the content
            produced by the selected step.
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

      <div className="space-y-1.5">
        <div className="flex items-start gap-2">
          <input
            id="overwrite"
            type="checkbox"
            checked={overwrite}
            onChange={(event) => handleOverwriteChange(event.target.checked)}
            className="mt-0.5 size-4 rounded border"
          />
          <div className="space-y-0.5">
            <Label htmlFor="overwrite" className="font-mono text-xs font-medium">
              overwrite
            </Label>
            <p className="text-[11px] text-muted-foreground">
              Replace the destination file if it already exists.
            </p>
          </div>
        </div>
        {overwrite ? (
          <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
            This will replace the existing file on the device if one exists at this path.
          </p>
        ) : null}
      </div>

      <div className="flex items-start gap-2">
        <input
          id="inline-transfer"
          type="checkbox"
          checked={inlineTransfer}
          onChange={(event) => handleInlineTransferChange(event.target.checked)}
          className="mt-0.5 size-4 rounded border"
        />
        <div className="space-y-0.5">
          <Label htmlFor="inline-transfer" className="font-mono text-xs font-medium">
            inline_transfer
          </Label>
          <p className="text-[11px] text-muted-foreground">
            Use Netmiko&apos;s inline (non-SCP) transfer for text files instead of SCP/SFTP —
            useful when the device has no SCP server enabled.
          </p>
        </div>
      </div>

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

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">socket_timeout</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            integer
          </Badge>
        </div>
        <Input
          type="number"
          min={MIN_SOCKET_TIMEOUT}
          max={MAX_SOCKET_TIMEOUT}
          value={socketTimeout}
          onChange={(event) => handleSocketTimeoutChange(event.target.value)}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          SCP/SFTP socket timeout in seconds. Raise this for large config files or slow
          links.
        </p>
      </div>
    </div>
  );
}

export const UploadConfigPlugin: PluginUIComponent = {
  ConfigPanel: UploadConfigConfigPanel,
  HelpPanel: UploadConfigHelpPanel,
};
