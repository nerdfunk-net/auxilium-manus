"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  CheckCircle2,
  Database,
  FileArchive,
  GitBranch,
  HardDriveDownload,
  Router,
  TerminalSquare,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { WorkflowCanvasNode } from "../../types/workflow-canvas";

const nodeIconsByType: Record<string, LucideIcon> = {
  command_execution: TerminalSquare,
  configuration_retrieval: HardDriveDownload,
  control_flow: GitBranch,
  inventory_selector: Router,
  persistent_artifact: FileArchive,
  trigger: GitBranch,
  result: CheckCircle2,
};

const nodeAccentClassesByType: Record<string, string> = {
  command_execution: "bg-emerald-100 text-emerald-700",
  configuration_retrieval: "bg-indigo-100 text-indigo-700",
  control_flow: "bg-amber-100 text-amber-700",
  inventory_selector: "bg-sky-100 text-sky-700",
  persistent_artifact: "bg-violet-100 text-violet-700",
  trigger: "bg-slate-100 text-slate-700",
  result: "bg-teal-100 text-teal-700",
};

export function WorkflowNode({ data, selected }: NodeProps<WorkflowCanvasNode>) {
  const nodeType = data.artifactType ?? data.kind;
  const Icon = nodeIconsByType[nodeType] ?? Database;
  const inputs = data.mandatoryInputs ?? [];
  const hasCapabilityInput = (data.requires?.length ?? 0) > 0;
  const outcomes = data.outcomes ?? [];
  const hasTargetHandles = hasCapabilityInput || inputs.length > 0;
  const hasSourceHandles = outcomes.length > 0;

  return (
    <div
      className={cn(
        "relative min-w-56 rounded-xl border bg-card p-4 shadow-sm transition-shadow",
        selected && "border-ring shadow-lg ring-2 ring-ring/20",
      )}
    >
      {hasTargetHandles
        ? inputs.map((input, index) => (
            <div key={input.name}>
              {inputs.length > 1 ? (
                <span
                  className="absolute left-4 -translate-y-1/2 rounded-full bg-background px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground shadow-sm"
                  style={{
                    top: `${((index + 1) / (inputs.length + 1)) * 100}%`,
                  }}
                >
                  {input.name}
                </span>
              ) : null}
              <Handle
                className="!size-3 !border-2 !bg-background"
                id={input.name}
                position={Position.Left}
                style={{
                  top: `${((index + 1) / (inputs.length + 1)) * 100}%`,
                }}
                type="target"
              />
            </div>
          ))
        : null}
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "flex size-10 shrink-0 items-center justify-center rounded-lg",
            nodeAccentClassesByType[nodeType] ?? "bg-muted text-muted-foreground",
          )}
        >
          <Icon className="size-5" />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-semibold">{data.title}</p>
            {data.status ? (
              <Badge className="capitalize" variant="outline">
                {data.status}
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
            {data.description}
          </p>
        </div>
      </div>
      {hasSourceHandles
        ? outcomes.map((outcome, index) => (
            <div key={outcome.name}>
              {outcomes.length > 1 ? (
                <span
                  className="absolute right-4 -translate-y-1/2 rounded-full bg-background px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground shadow-sm"
                  style={{
                    top: `${((index + 1) / (outcomes.length + 1)) * 100}%`,
                  }}
                >
                  {outcome.name}
                </span>
              ) : null}
              <Handle
                className="!size-3 !border-2 !bg-background"
                id={outcome.name}
                position={Position.Right}
                style={{
                  top: `${((index + 1) / (outcomes.length + 1)) * 100}%`,
                }}
                type="source"
              />
            </div>
          ))
        : null}
    </div>
  );
}
