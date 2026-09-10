"use client";

import { useCallback, useEffect, useRef, useState } from "react";

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
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { GitRepositorySelectDialog } from "@/components/features/workflow-steps/shared/git-repository-select-dialog";
import { GitRepositoryValue } from "@/components/features/workflow-steps/shared/git-repository-value";
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

function OpenChangeRequestConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
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

      <TextField
        label="source_step_node_id"
        value={str(config, "source_step_node_id")}
        onChange={(value) => patch({ source_step_node_id: value })}
        hint="Canvas node id of the upstream render-jinja-template step (optional)."
      />
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
