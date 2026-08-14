"use client";

import { NodeResizer, type NodeProps } from "@xyflow/react";

import { cn } from "@/lib/utils";

import {
  DEFAULT_BACKGROUND_CONFIG,
  type BackgroundCanvasNode,
} from "../../types/workflow-canvas";

function readString(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

export function BackgroundNode({ data, selected }: NodeProps<BackgroundCanvasNode>) {
  const config = data.pluginConfig ?? {};
  const color = readString(config.color, DEFAULT_BACKGROUND_CONFIG.color);

  return (
    <div
      className={cn(
        "relative h-full w-full rounded-lg border border-input/60",
        selected && "ring-2 ring-ring/30 ring-offset-1",
      )}
      style={{ backgroundColor: color }}
    >
      <NodeResizer
        isVisible={selected}
        minWidth={80}
        minHeight={80}
        lineClassName="!border-step"
        handleClassName="!h-2 !w-2 !rounded-sm !border-step-hover !bg-card"
      />
    </div>
  );
}
