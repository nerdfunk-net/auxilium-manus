"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  CheckCircle2,
  Combine,
  Database,
  FileArchive,
  FileText,
  GitBranch,
  GitMerge,
  HardDriveDownload,
  Info,
  Router,
  Scale,
  Settings2,
  Split,
  TerminalSquare,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import { useWorkflowBuilderStore } from "../../hooks/use-workflow-builder-store";
import type { WorkflowCanvasNode } from "../../types/workflow-canvas";

const nodeIconsByType: Record<string, LucideIcon> = {
  command_execution: TerminalSquare,
  configuration_retrieval: HardDriveDownload,
  control_flow: GitBranch,
  inventory_selector: Router,
  persistent_artifact: FileArchive,
  template_rendering: FileText,
  trigger: GitBranch,
  result: CheckCircle2,
};

const nodeAccentClassesByType: Record<string, string> = {
  command_execution: "bg-emerald-100 text-emerald-700",
  configuration_retrieval: "bg-indigo-100 text-indigo-700",
  control_flow: "bg-amber-100 text-amber-700",
  inventory_selector: "bg-sky-100 text-sky-700",
  persistent_artifact: "bg-violet-100 text-violet-700",
  template_rendering: "bg-orange-100 text-orange-700",
  trigger: "bg-slate-100 text-slate-700",
  result: "bg-teal-100 text-teal-700",
};

export function WorkflowNode({ id, data, selected }: NodeProps<WorkflowCanvasNode>) {
  const openConfigModal = useWorkflowBuilderStore((state) => state.openConfigModal);
  const nodeType = data.artifactType ?? data.kind;
  const Icon = nodeIconsByType[nodeType] ?? Database;
  const hasTargetHandles = (data.requires?.length ?? 0) > 0;
  const outcomes = data.outcomes ?? [];
  const hasSourceHandles = outcomes.length > 0;
  const fanOut = data.pluginConfig?.fan_out;
  const fanOutEnabled =
    !!fanOut &&
    typeof fanOut === "object" &&
    (fanOut as Record<string, unknown>).enabled === true;

  if (data.kind === "compare-data") {
    return (
      <div
        className={cn(
          "group relative w-64 min-h-28 rounded-xl border bg-card p-3 pr-16 shadow-sm transition-shadow",
          selected && "border-ring shadow-lg ring-2 ring-ring/20",
        )}
      >
        <Handle
          className="!size-3 !border-2 !bg-background"
          id="input"
          position={Position.Left}
          style={{ top: "50%" }}
          type="target"
        />
        <Button
          aria-label="Configure step"
          className="absolute right-1.5 top-1.5 size-6 opacity-0 transition-opacity group-hover:opacity-100"
          onClick={(e) => { e.stopPropagation(); openConfigModal(id); }}
          size="icon"
          variant="ghost"
        >
          <Settings2 className="size-3.5" />
        </Button>
        <div className="flex items-start gap-2.5">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-amber-100 text-amber-700">
            <Scale className="size-4" aria-hidden />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-foreground">{data.title}</p>
            <p className="mt-0.5 text-[10px] leading-4 text-muted-foreground">
              Compare to reference file
            </p>
          </div>
        </div>
        {hasSourceHandles
          ? outcomes.map((outcome, index) => (
              <div key={outcome.name}>
                <span
                  className="absolute right-5 -translate-y-1/2 whitespace-nowrap rounded-full bg-background px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground shadow-sm"
                  style={{
                    top: `${((index + 1) / (outcomes.length + 1)) * 100}%`,
                  }}
                >
                  {outcome.name}
                </span>
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

  if (data.kind === "merge-content") {
    return (
      <div
        className={cn(
          "group relative w-52 rounded-xl border bg-card shadow-sm transition-shadow",
          selected && "border-ring shadow-lg ring-2 ring-ring/20",
        )}
      >
        <Handle
          className="!size-3 !border-2 !bg-background"
          id="input"
          position={Position.Left}
          style={{ top: "50%" }}
          type="target"
        />
        <Button
          aria-label="Configure step"
          className="absolute right-1.5 top-1.5 size-6 opacity-0 transition-opacity group-hover:opacity-100"
          onClick={(e) => { e.stopPropagation(); openConfigModal(id); }}
          size="icon"
          variant="ghost"
        >
          <Settings2 className="size-3.5" />
        </Button>
        <div className="flex items-center gap-2 p-2.5">
          <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-amber-100 text-amber-700">
            <Combine className="size-3.5" aria-hidden />
          </div>
          <div className="min-w-0">
            <p className="truncate text-xs font-semibold text-foreground">{data.title}</p>
            <p className="truncate text-[10px] leading-4 text-muted-foreground">
              Merge command outputs
            </p>
          </div>
        </div>
        {hasSourceHandles
          ? outcomes.map((outcome, index) => (
              <Handle
                key={outcome.name}
                className="!size-3 !border-2 !bg-background"
                id={outcome.name}
                position={Position.Right}
                style={{
                  top: `${((index + 1) / (outcomes.length + 1)) * 100}%`,
                }}
                type="source"
              />
            ))
          : null}
      </div>
    );
  }

  if (data.kind === "fan-in") {
    return (
      <div
        className={cn(
          "group relative w-80 rounded-xl border bg-card shadow-sm transition-shadow",
          selected && "border-ring shadow-lg ring-2 ring-ring/20",
        )}
      >
        <Handle
          className="!size-3 !border-2 !bg-background"
          id="input"
          position={Position.Left}
          style={{ top: "50%" }}
          type="target"
        />
        <Button
          aria-label="Configure step"
          className="absolute right-1.5 top-1.5 size-6 opacity-0 transition-opacity group-hover:opacity-100"
          onClick={(e) => { e.stopPropagation(); openConfigModal(id); }}
          size="icon"
          variant="ghost"
        >
          <Settings2 className="size-3.5" />
        </Button>
        <div className="flex items-start gap-3 p-3">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-amber-100 text-amber-700">
            <GitMerge className="size-4" aria-hidden />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1">
              <span className="text-xs font-semibold text-foreground">Fan In</span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Info className="size-3 shrink-0 cursor-help text-muted-foreground" aria-label="About Fan In" />
                </TooltipTrigger>
                <TooltipContent side="top">
                  {data.description}
                </TooltipContent>
              </Tooltip>
            </div>
            <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
              Rejoin a fanned-out workflow into a single path.
            </p>
          </div>
        </div>
        {hasSourceHandles
          ? outcomes.map((outcome, index) => (
              <Handle
                key={outcome.name}
                className="!size-3 !border-2 !bg-background"
                id={outcome.name}
                position={Position.Right}
                style={{
                  top: `${((index + 1) / (outcomes.length + 1)) * 100}%`,
                }}
                type="source"
              />
            ))
          : null}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group relative min-w-56 rounded-xl border bg-card p-4 shadow-sm transition-shadow",
        selected && "border-ring shadow-lg ring-2 ring-ring/20",
      )}
    >
      {hasTargetHandles ? (
        <Handle
          className="!size-3 !border-2 !bg-background"
          id="input"
          position={Position.Left}
          style={{ top: "50%" }}
          type="target"
        />
      ) : null}
      <Button
        aria-label="Configure step"
        className="absolute right-1.5 top-1.5 size-6 opacity-0 transition-opacity group-hover:opacity-100"
        onClick={(e) => { e.stopPropagation(); openConfigModal(id); }}
        size="icon"
        variant="ghost"
      >
        <Settings2 className="size-3.5" />
      </Button>
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
            {fanOutEnabled ? (
              <Badge
                className="gap-1 border-teal-300 bg-teal-50 text-teal-700"
                variant="outline"
              >
                <Split className="size-3" aria-hidden />
                Fan out
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
