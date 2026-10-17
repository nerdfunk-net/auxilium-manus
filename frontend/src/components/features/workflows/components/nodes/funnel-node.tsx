"use client";

import { useEffect } from "react";
import { Handle, Position, useUpdateNodeInternals, type NodeProps } from "@xyflow/react";
import { Merge } from "lucide-react";

import { cn } from "@/lib/utils";

import type { FunnelCanvasNode, HandleSide } from "../../types/workflow-canvas";

const NODE_SIZE_CLASS = "size-10";

const HANDLE_CLASS = "!size-3 !border-2 !bg-muted-foreground/40 !border-muted-foreground";

const HANDLE_SIDE_TO_POSITION: Record<HandleSide, Position> = {
  top: Position.Top,
  bottom: Position.Bottom,
  left: Position.Left,
  right: Position.Right,
};

/** Centers a handle along the axis perpendicular to the side it attaches to. */
function centeringStyle(side: HandleSide) {
  return side === "top" || side === "bottom" ? { left: "50%" } : { top: "50%" };
}

export function FunnelNode({ id, data, selected }: NodeProps<FunnelCanvasNode>) {
  const incomeSide = data.incomeHandleSide ?? "left";
  const outcomeSide = data.outcomeHandleSide ?? "right";

  const updateNodeInternals = useUpdateNodeInternals();
  useEffect(() => {
    updateNodeInternals(id);
  }, [id, updateNodeInternals, incomeSide, outcomeSide]);

  return (
    <div
      className={cn(
        "relative flex items-center justify-center rounded-full border bg-card shadow-sm transition-shadow",
        NODE_SIZE_CLASS,
        selected && "border-ring shadow-lg ring-2 ring-ring/20",
      )}
    >
      <Handle
        className={HANDLE_CLASS}
        id="input"
        position={HANDLE_SIDE_TO_POSITION[incomeSide]}
        style={centeringStyle(incomeSide)}
        type="target"
      />
      <Merge className="size-4 text-muted-foreground" aria-hidden />
      <Handle
        className={HANDLE_CLASS}
        id="output"
        position={HANDLE_SIDE_TO_POSITION[outcomeSide]}
        style={centeringStyle(outcomeSide)}
        type="source"
      />
    </div>
  );
}
