"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EMPTY_WORKFLOW_NODES } from "@/components/features/workflows/constants/empty-canvas";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { GitRepositorySelectDialog } from "@/components/features/workflow-steps/shared/git-repository-select-dialog";
import { GitRepositoryValue } from "@/components/features/workflow-steps/shared/git-repository-value";
import { listUpstreamSourceSteps } from "@/components/features/workflow-steps/shared/upstream-source-steps";
import { useWorkflowsQuery } from "@/hooks/queries/use-workflows-query";

const DEFAULTS = {
  git_repository_id: null as number | null,
  content_source: "rendered_template",
  source_step_node_id: "",
  filename_template: "{device.name}.cfg",
  branch_template: "manus/cr-{run.id}",
  commit_message_template: "Change request: run {run.id}",
  title_template: "Change request for run {run.id}",
  deploy_workflow_id: null as number | null,
  expires_after_hours: 168,
};

function repoId(config: Record<string, unknown>): number | null {
  return typeof config.git_repository_id === "number" ? config.git_repository_id : null;
}

function str(config: Record<string, unknown>, key: keyof typeof DEFAULTS): string {
  const value = config[key];
  return typeof value === "string" ? value : String(DEFAULTS[key] ?? "");
}

function buildConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    ...DEFAULTS,
    ...config,
    git_repository_id: repoId(config),
    ...patch,
  };
}

function TextField({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
}) {
  return (
    <div className="space-y-1.5">
      <span className="font-mono text-xs font-medium">{label}</span>
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 font-mono text-xs"
      />
      {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function OpenChangeRequestConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes = EMPTY_WORKFLOW_NODES,
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const [repositoryOpen, setRepositoryOpen] = useState(false);
  const repositoryId = repoId(config);
  const { data: workflowsData } = useWorkflowsQuery();

  useEffect(() => {
    if (initializedForNode.current === nodeId) return;
    initializedForNode.current = nodeId;
    if (config.branch_template === undefined) {
      onChange(buildConfig(config));
    }
  }, [nodeId, config, onChange]);

  const patch = useCallback(
    (next: Record<string, unknown>) => onChange(buildConfig(config, next)),
    [config, onChange],
  );

  const deployWorkflowId =
    typeof config.deploy_workflow_id === "number" ? String(config.deploy_workflow_id) : "";

  // Render Jinja Template steps whose output this step can commit — same helper
  // deploy-rendered-template uses. When there is exactly one, it is auto-selected
  // so source_step_node_id needs no manual entry.
  const sourceStepNodeId = str(config, "source_step_node_id");
  const sourceSteps = useMemo(
    () => listUpstreamSourceSteps(workflowNodes, "rendered_template", nodeId),
    [workflowNodes, nodeId],
  );
  const selectedSourceStep = useMemo(
    () => sourceSteps.find((step) => step.nodeId === sourceStepNodeId) ?? null,
    [sourceSteps, sourceStepNodeId],
  );

  useEffect(() => {
    if (sourceSteps.length !== 1 || sourceStepNodeId) return;
    patch({ source_step_node_id: sourceSteps[0].nodeId });
  }, [sourceStepNodeId, sourceSteps, patch]);

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">git_repository_id</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            git
          </Badge>
        </div>
        <GitRepositoryValue repositoryId={repositoryId} />
        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setRepositoryOpen(true)}
        >
          {repositoryId !== null ? "Change repository" : "Choose repository"}
        </Button>
        <p className="text-[11px] text-muted-foreground">
          The staged branch is pushed here. Not fan-out-safe — place after any Fan In node.
        </p>
      </div>

      <GitRepositorySelectDialog
        open={repositoryOpen}
        selectedRepositoryId={repositoryId}
        onClose={() => setRepositoryOpen(false)}
        onSave={(id) => patch({ git_repository_id: id })}
      />

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">source_step_node_id</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            step
          </Badge>
        </div>
        {sourceSteps.length > 0 ? (
          <Select
            value={sourceStepNodeId || ""}
            onValueChange={(value) => patch({ source_step_node_id: value })}
          >
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
        {selectedSourceStep ? (
          <p className="text-[11px] text-muted-foreground">
            Committing the rendered output of{" "}
            <span className="font-mono">{selectedSourceStep.nodeId}</span>.
          </p>
        ) : sourceStepNodeId && sourceSteps.length > 0 ? (
          <p className="text-[11px] text-warning-foreground">
            Saved node id <span className="font-mono">{sourceStepNodeId}</span> is not on
            this canvas. Pick a step above or enter an id manually.
          </p>
        ) : null}
        <details className="rounded-lg border bg-muted/20 px-3 py-2">
          <summary className="cursor-pointer text-[11px] font-medium text-muted-foreground">
            Advanced: enter node id manually
          </summary>
          <div className="mt-2 space-y-1.5">
            <Input
              value={sourceStepNodeId}
              onChange={(event) => patch({ source_step_node_id: event.target.value })}
              placeholder="render-jinja-template-3"
              className="h-8 font-mono text-xs"
            />
            <p className="text-[11px] text-muted-foreground">
              Only needed when reusing an id from an older workflow or run results.
            </p>
          </div>
        </details>
      </div>
      <TextField
        label="filename_template"
        value={str(config, "filename_template")}
        onChange={(value) => patch({ filename_template: value })}
        hint="Per-device file path. Placeholders: {device.name}, {nautobot.*}."
      />
      <TextField
        label="branch_template"
        value={str(config, "branch_template")}
        onChange={(value) => patch({ branch_template: value })}
        hint="Placeholders: {run.id}, {workflow.id}."
      />
      <TextField
        label="commit_message_template"
        value={str(config, "commit_message_template")}
        onChange={(value) => patch({ commit_message_template: value })}
      />
      <TextField
        label="title_template"
        value={str(config, "title_template")}
        onChange={(value) => patch({ title_template: value })}
      />

      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">deploy_workflow_id</span>
        <Select
          value={deployWorkflowId}
          onValueChange={(value) =>
            patch({ deploy_workflow_id: value ? Number(value) : null })
          }
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="Choose at approval time" />
          </SelectTrigger>
          <SelectContent>
            {(workflowsData?.workflows ?? []).map((workflow) => (
              <SelectItem key={workflow.id} value={String(workflow.id)}>
                {workflow.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[11px] text-muted-foreground">
          Workflow that deploys an approved change request.
        </p>
      </div>

      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">expires_after_hours</span>
        <Input
          type="number"
          min={0}
          value={
            typeof config.expires_after_hours === "number"
              ? config.expires_after_hours
              : DEFAULTS.expires_after_hours
          }
          onChange={(event) =>
            patch({ expires_after_hours: Number(event.target.value) || 0 })
          }
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">0 disables expiry.</p>
      </div>
    </div>
  );
}

export const OpenChangeRequestPlugin: PluginUIComponent = {
  ConfigPanel: OpenChangeRequestConfigPanel,
};
