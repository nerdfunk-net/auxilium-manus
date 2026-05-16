"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  CheckCircle2,
  Database,
  FileArchive,
  GitBranch,
  Network,
  Router,
  TerminalSquare,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { WorkflowCanvasNode, WorkflowNodeKind } from "../../types/workflow-canvas";

const nodeIcons: Record<WorkflowNodeKind, typeof Network> = {
  trigger: GitBranch,
  "device-selection": Router,
  "ssh-login": Network,
  "run-command": TerminalSquare,
  condition: GitBranch,
  "store-artifact": FileArchive,
  result: CheckCircle2,
};

const nodeAccentClasses: Record<WorkflowNodeKind, string> = {
  trigger: "bg-slate-100 text-slate-700",
  "device-selection": "bg-sky-100 text-sky-700",
  "ssh-login": "bg-indigo-100 text-indigo-700",
  "run-command": "bg-emerald-100 text-emerald-700",
  condition: "bg-amber-100 text-amber-700",
  "store-artifact": "bg-violet-100 text-violet-700",
  result: "bg-teal-100 text-teal-700",
};

export function WorkflowNode({ data, selected }: NodeProps<WorkflowCanvasNode>) {
  const Icon = nodeIcons[data.kind] ?? Database;
  const hasTargetHandle = data.kind !== "trigger" && data.kind !== "device-selection";
  const hasSourceHandle = data.kind !== "result";

  return (
    <div
      className={cn(
        "min-w-56 rounded-xl border bg-card p-4 shadow-sm transition-shadow",
        selected && "border-ring shadow-lg ring-2 ring-ring/20",
      )}
    >
      {hasTargetHandle ? (
        <Handle
          className="!size-3 !border-2 !bg-background"
          position={Position.Left}
          type="target"
        />
      ) : null}
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "flex size-10 shrink-0 items-center justify-center rounded-lg",
            nodeAccentClasses[data.kind],
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
      {hasSourceHandle ? (
        <Handle
          className="!size-3 !border-2 !bg-background"
          position={Position.Right}
          type="source"
        />
      ) : null}
    </div>
  );
}
