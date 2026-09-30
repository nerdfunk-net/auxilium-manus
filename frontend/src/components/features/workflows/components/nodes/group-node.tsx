"use client";

import { useEffect } from "react";
import { Handle, Position, useUpdateNodeInternals, type NodeProps } from "@xyflow/react";
import { FolderOpen, Settings2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { useWorkflowBuilderStore } from "../../hooks/use-workflow-builder-store";
import type { GroupCanvasNode, HandleSide } from "../../types/workflow-canvas";

const NODE_WIDTH_CLASS = "w-80";
const NODE_HEIGHT_CLASS = "h-32";

const TARGET_HANDLE_CLASS = "!size-3 !border-2 !bg-muted-foreground/40 !border-muted-foreground";
const SOURCE_HANDLE_CLASS = "!size-3 !border-2 !bg-step !border-step-hover";

const HANDLE_SIDE_TO_POSITION: Record<HandleSide, Position> = {
  top: Position.Top,
  bottom: Position.Bottom,
  left: Position.Left,
  right: Position.Right,
};

/** Places handle `index` of `count` evenly along the axis of the side it attaches to. */
function portStyle(side: HandleSide, index: number, count: number) {
  const pct = `${((index + 1) / (count + 1)) * 100}%`;
  return side === "top" || side === "bottom" ? { left: pct } : { top: pct };
}

export function GroupNode({ id, data, selected }: NodeProps<GroupCanvasNode>) {
  const enterGroup = useWorkflowBuilderStore((state) => state.enterGroup);
  const openConfigModal = useWorkflowBuilderStore((state) => state.openConfigModal);
  const incomeSide = data.incomeHandleSide ?? "left";
  const outcomeSide = data.outcomeHandleSide ?? "right";
  const inputPorts = data.inputPorts;
  const outputPorts = data.outputPorts;

  const updateNodeInternals = useUpdateNodeInternals();
  useEffect(() => {
    updateNodeInternals(id);
  }, [id, updateNodeInternals, incomeSide, outcomeSide, inputPorts.length, outputPorts.length]);

  return (
    <div
      className={cn(
        "group relative rounded-xl border border-l-[3px] border-l-step bg-card shadow-sm transition-shadow",
        NODE_WIDTH_CLASS,
        NODE_HEIGHT_CLASS,
        selected && "border-ring shadow-lg ring-2 ring-ring/20",
        data.isDropTarget && "border-ring bg-accent shadow-lg ring-2 ring-ring",
      )}
      onDoubleClick={() => enterGroup(data.groupId)}
    >
      {inputPorts.length > 0 ? (
        inputPorts.map((port, index) => (
          <Handle
            className={TARGET_HANDLE_CLASS}
            id={port.handleId}
            key={port.handleId}
            position={HANDLE_SIDE_TO_POSITION[incomeSide]}
            style={portStyle(incomeSide, index, inputPorts.length)}
            title={port.label}
            type="target"
          />
        ))
      ) : (
        <Handle
          className={TARGET_HANDLE_CLASS}
          id="input"
          position={HANDLE_SIDE_TO_POSITION[incomeSide]}
          style={portStyle(incomeSide, 0, 1)}
          type="target"
        />
      )}
      <Button
        aria-label="Open configuration"
        className="absolute right-1.5 top-1.5 size-6 opacity-0 transition-opacity group-hover:opacity-100"
        onClick={(event) => {
          event.stopPropagation();
          openConfigModal(id);
        }}
        size="icon"
        variant="ghost"
      >
        <Settings2 className="size-3.5" />
      </Button>
      <div className="flex h-full items-start gap-3 p-4 pr-10">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-step-surface text-step-muted-foreground">
          <FolderOpen className="size-5" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <p className="min-w-0 text-sm font-semibold leading-snug">{data.title}</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {data.memberCount === 0
              ? "Empty group"
              : `${data.memberCount} step${data.memberCount === 1 ? "" : "s"}`}
          </p>
          <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
            {data.isDropTarget ? "Drop to add to group" : "Double-click to open"}
          </p>
        </div>
      </div>
      {outputPorts.length > 0 ? (
        outputPorts.map((port, index) => (
          <Handle
            className={SOURCE_HANDLE_CLASS}
            id={port.handleId}
            key={port.handleId}
            position={HANDLE_SIDE_TO_POSITION[outcomeSide]}
            style={portStyle(outcomeSide, index, outputPorts.length)}
            title={port.label}
            type="source"
          />
        ))
      ) : (
        <Handle
          className={SOURCE_HANDLE_CLASS}
          id="success"
          position={HANDLE_SIDE_TO_POSITION[outcomeSide]}
          style={portStyle(outcomeSide, 0, 1)}
          type="source"
        />
      )}
    </div>
  );
}
