"use client";

import { useCallback } from "react";

import type {
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "@/components/features/workflows/types/workflow-canvas";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { SendMailHelpPanel } from "./help-panel";
import { PlaceholderField } from "./placeholder-field";

const TO_KEY = "to";
const SUBJECT_KEY = "subject";
const BODY_KEY = "body";

const EMPTY_NODES: PersistedCanvasNode[] = [];
const EMPTY_EDGES: WorkflowCanvasEdge[] = [];

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function SendMailConfigPanel({
  nodeId,
  config,
  onChange,
  workflowNodes = EMPTY_NODES,
  workflowEdges = EMPTY_EDGES,
}: PluginConfigPanelProps) {
  const patch = useCallback(
    (key: string, value: unknown) => onChange({ ...config, [key]: value }),
    [config, onChange],
  );

  const fieldProps = { nodeId, workflowNodes, workflowEdges };

  return (
    <div className="flex flex-col gap-4">
      <p className="rounded-lg border bg-muted/40 px-3 py-2 text-[11px] leading-4 text-muted-foreground">
        Sent through the mail server an administrator configured under Settings → Mail. The
        server, login and sender address are not step settings, and the administrator&apos;s
        allowed recipient domains apply.
      </p>
      <PlaceholderField
        {...fieldProps}
        configKey={TO_KEY}
        placeholder="ops@example.com, {custom.owner_email}"
        value={stringFromConfig(config, TO_KEY)}
        onValueChange={(value) => patch(TO_KEY, value)}
      />
      <PlaceholderField
        {...fieldProps}
        configKey={SUBJECT_KEY}
        placeholder="Config changed on {device.name}"
        value={stringFromConfig(config, SUBJECT_KEY)}
        onValueChange={(value) => patch(SUBJECT_KEY, value)}
      />
      <PlaceholderField
        {...fieldProps}
        multiline
        configKey={BODY_KEY}
        placeholder="Workflow finished: {device_count} device(s) ({devices})"
        value={stringFromConfig(config, BODY_KEY)}
        onValueChange={(value) => patch(BODY_KEY, value)}
      >
        <p className="text-[11px] leading-4 text-muted-foreground">
          Use <span className="font-mono">{"{path.to.value}"}</span> for device attributes, e.g{" "}
          <span className="font-mono">{"{device.name}"}</span>.{" "}
          <span className="font-mono">{"{devices}"}</span> and{" "}
          <span className="font-mono">{"{device_count}"}</span> summarize a multi-device run.
        </p>
      </PlaceholderField>
    </div>
  );
}

export const SendMailPlugin: PluginUIComponent = {
  ConfigPanel: SendMailConfigPanel,
  HelpPanel: SendMailHelpPanel,
};
