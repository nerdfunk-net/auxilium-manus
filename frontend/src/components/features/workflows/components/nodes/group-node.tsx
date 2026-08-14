"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { FolderOpen } from "lucide-react";

import { cn } from "@/lib/utils";

import { useWorkflowBuilderStore } from "../../hooks/use-workflow-builder-store";
import type { GroupCanvasNode } from "../../types/workflow-canvas";

const NODE_WIDTH_CLASS = "w-80";
const NODE_HEIGHT_CLASS = "h-32";

const TARGET_HANDLE_CLASS = "!size-3 !border-2 !bg-muted-foreground/40 !border-muted-foreground";
const SOURCE_HANDLE_CLASS = "!size-3 !border-2 !bg-step !border-step-hover";

export function GroupNode({ data, selected }: NodeProps<GroupCanvasNode>) {
  const enterGroup = useWorkflowBuilderStore((state) => state.enterGroup);
  const hasTargetHandle = (data.requires?.length ?? 0) > 0 || (data.requiresParsed?.length ?? 0) > 0;

  return (
    <div
      className={cn(
        "group relative rounded-xl border border-l-[3px] border-l-step bg-card shadow-sm transition-shadow",
        NODE_WIDTH_CLASS,
        NODE_HEIGHT_CLASS,
        selected && "border-ring shadow-lg ring-2 ring-ring/20",
      )}
      onDoubleClick={() => enterGroup(data.groupId)}
    >
      {hasTargetHandle ? (
        <Handle
          className={TARGET_HANDLE_CLASS}
          id="input"
          position={Position.Left}
          style={{ top: "50%" }}
          type="target"
        />
      ) : null}
      <div className="flex h-full items-start gap-3 p-4 pr-10">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-step-surface text-step-muted-foreground">
          <FolderOpen className="size-5" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <p className="min-w-0 text-sm font-semibold leading-snug">{data.title}</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {data.memberCount} step{data.memberCount === 1 ? "" : "s"}
          </p>
          <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
            Double-click to open
          </p>
        </div>
      </div>
      <Handle
        className={SOURCE_HANDLE_CLASS}
        id="success"
        position={Position.Right}
        style={{ top: "50%" }}
        type="source"
      />
    </div>
  );
}
