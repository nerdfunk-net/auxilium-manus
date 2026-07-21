"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

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
import { listUpstreamSourceSteps } from "@/components/features/workflow-steps/store-artifact/upstream-source-steps";

import { DeployRenderedTemplateHelpPanel } from "./help-panel";

const EXECUTION_MODE_OPTIONS = [
  {
    value: "config_mode",
    label: "Configuration mode",
    hint: "Enters configuration mode once, sends every rendered line, then exits.",
  },
  {
    value: "exec_mode",
    label: "Exec mode",
    hint: "Sends each rendered line individually as an exec-level command, like Run Command.",
  },
] as const;

type ExecutionMode = (typeof EXECUTION_MODE_OPTIONS)[number]["value"];

function buildDeployRenderedTemplateConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    credential_reference:
      typeof config.credential_reference === "string" ? config.credential_reference : "",
    source_step_node_id:
      typeof config.source_step_node_id === "string" ? config.source_step_node_id : "",
    parsed_output_key:
      typeof config.parsed_output_key === "string" ? config.parsed_output_key : "",
    execution_mode:
      config.execution_mode === "config_mode" || config.execution_mode === "exec_mode"
        ? config.execution_mode
        : "config_mode",
    network_driver_override:
      typeof config.network_driver_override === "string" ? config.network_driver_override : "",
    write_config_after_execution: config.write_config_after_execution === true,
    ...patch,
  };
}

function DeployRenderedTemplateConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes = [],
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (config.execution_mode === undefined) {
      onChange(buildDeployRenderedTemplateConfig(config));
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
  const sourceStepNodeId =
    typeof config.source_step_node_id === "string" ? config.source_step_node_id : "";
  const parsedOutputKey =
    typeof config.parsed_output_key === "string" ? config.parsed_output_key : "";
  const executionMode = (config.execution_mode as ExecutionMode) || "config_mode";
  const networkDriverOverride =
    typeof config.network_driver_override === "string" ? config.network_driver_override : "";
  const writeConfigAfterExecution = config.write_config_after_execution === true;

  const sourceSteps = useMemo(
    () => listUpstreamSourceSteps(workflowNodes, "rendered_template", nodeId),
    [workflowNodes, nodeId],
  );
  const selectedSourceStep = useMemo(
    () => sourceSteps.find((step) => step.nodeId === sourceStepNodeId) ?? null,
    [sourceSteps, sourceStepNodeId],
  );

  const handleCredentialChange = useCallback(
    (value: string) => {
      onChange(buildDeployRenderedTemplateConfig(config, { credential_reference: value }));
    },
    [config, onChange],
  );

  const handleSourceStepSelect = useCallback(
    (selectedNodeId: string) => {
      const step = sourceSteps.find((candidate) => candidate.nodeId === selectedNodeId);
      const patch: Record<string, unknown> = { source_step_node_id: selectedNodeId };
      if (step?.outputKey) {
        const currentKey = parsedOutputKey.trim();
        if (!currentKey) {
          patch.parsed_output_key = step.outputKey;
        }
      }
      onChange(buildDeployRenderedTemplateConfig(config, patch));
    },
    [config, onChange, parsedOutputKey, sourceSteps],
  );

  useEffect(() => {
    if (sourceSteps.length !== 1 || sourceStepNodeId) {
      return;
    }
    handleSourceStepSelect(sourceSteps[0].nodeId);
  }, [sourceStepNodeId, sourceSteps, handleSourceStepSelect]);

  const handleSourceStepNodeIdChange = useCallback(
    (value: string) => {
      onChange(buildDeployRenderedTemplateConfig(config, { source_step_node_id: value }));
    },
    [config, onChange],
  );

  const handleParsedOutputKeyChange = useCallback(
    (value: string) => {
      onChange(buildDeployRenderedTemplateConfig(config, { parsed_output_key: value }));
    },
    [config, onChange],
  );

  const handleExecutionModeChange = useCallback(
    (value: string) => {
      onChange(buildDeployRenderedTemplateConfig(config, { execution_mode: value }));
    },
    [config, onChange],
  );

  const handleDriverOverrideChange = useCallback(
    (value: string) => {
      onChange(buildDeployRenderedTemplateConfig(config, { network_driver_override: value }));
    },
    [config, onChange],
  );

  const handleWriteConfigChange = useCallback(
    (checked: boolean) => {
      onChange(
        buildDeployRenderedTemplateConfig(config, { write_config_after_execution: checked }),
      );
    },
    [config, onChange],
  );

  const executionModeHint = useMemo(
    () => EXECUTION_MODE_OPTIONS.find((option) => option.value === executionMode)?.hint,
    [executionMode],
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
        ) : sshCredentials.length === 0 ? (
          <p className="text-[11px] text-amber-600">
            No SSH credentials in Settings → Credentials
          </p>
        ) : (
          <Select value={credentialReference} onValueChange={handleCredentialChange}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Select SSH credential" />
            </SelectTrigger>
            <SelectContent>
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
          <span className="font-mono text-xs font-medium">source_step</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            step
          </Badge>
        </div>
        {sourceSteps.length > 0 ? (
          <Select value={sourceStepNodeId || undefined} onValueChange={handleSourceStepSelect}>
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
          <p className="text-[11px] text-amber-600">
            Add a Render Jinja Template step to this workflow first.
          </p>
        )}
        {selectedSourceStep ? (
          <p className="text-[11px] text-muted-foreground">
            Selected <span className="font-mono">{selectedSourceStep.nodeId}</span>
            {selectedSourceStep.outputKey ? ` · output_key ${selectedSourceStep.outputKey}` : ""}
          </p>
        ) : sourceStepNodeId && sourceSteps.length > 0 ? (
          <p className="text-[11px] text-amber-600">
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
              placeholder="render-jinja-template-3"
              className="h-8 font-mono text-xs"
            />
            <p className="text-[11px] text-muted-foreground">
              Only needed when reusing an id from an older workflow or run results.
            </p>
          </div>
        </details>
      </div>

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
          Optional output_key from the render step. Leave empty to use the template
          produced by the selected step.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">execution_mode</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={executionMode} onValueChange={handleExecutionModeChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {EXECUTION_MODE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {executionModeHint ? (
          <p className="text-[11px] text-muted-foreground">{executionModeHint}</p>
        ) : null}
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

      <div className="flex items-start gap-2">
        <input
          id="write-config-after-execution"
          type="checkbox"
          checked={writeConfigAfterExecution}
          onChange={(event) => handleWriteConfigChange(event.target.checked)}
          className="mt-0.5 size-4 rounded border"
        />
        <div className="space-y-0.5">
          <Label
            htmlFor="write-config-after-execution"
            className="font-mono text-xs font-medium"
          >
            write_config_after_execution
          </Label>
          <p className="text-[11px] text-muted-foreground">
            After a successful deployment, run &ldquo;copy running-config
            startup-config&rdquo; and confirm the prompt automatically. Skipped when the
            deployment itself fails.
          </p>
        </div>
      </div>
    </div>
  );
}

export const DeployRenderedTemplatePlugin: PluginUIComponent = {
  ConfigPanel: DeployRenderedTemplateConfigPanel,
  HelpPanel: DeployRenderedTemplateHelpPanel,
};
