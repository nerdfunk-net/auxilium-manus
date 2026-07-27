"use client";

import { NodeResizer, type NodeProps } from "@xyflow/react";

import { cn } from "@/lib/utils";

import {
  DEFAULT_LABEL_CONFIG,
  LABEL_FONT_STACKS,
  type LabelCanvasNode,
} from "../../types/workflow-canvas";

function readNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function readString(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

export function LabelNode({ data, selected }: NodeProps<LabelCanvasNode>) {
  const config = data.pluginConfig ?? {};
  const text = readString(config.text, DEFAULT_LABEL_CONFIG.text);
  const fontSize = readNumber(config.font_size, DEFAULT_LABEL_CONFIG.font_size);
  const fontFamilyKey = readString(config.font_family, DEFAULT_LABEL_CONFIG.font_family);
  const color = readString(config.color, DEFAULT_LABEL_CONFIG.color);
  const fontFamily = LABEL_FONT_STACKS[fontFamilyKey] ?? LABEL_FONT_STACKS.sans;

  return (
    <div
      className={cn(
        "relative flex h-full w-full items-center justify-center overflow-hidden rounded-md px-2",
        selected && "ring-2 ring-ring/40 ring-offset-1",
      )}
    >
      <NodeResizer
        isVisible={selected}
        minWidth={40}
        minHeight={24}
        lineClassName="!border-teal-400"
        handleClassName="!h-2 !w-2 !rounded-sm !border-teal-500 !bg-white"
      />
      <p
        className="w-full break-words text-center leading-snug"
        style={{
          color,
          fontSize,
          fontFamily,
        }}
      >
        {text || "Label"}
      </p>
    </div>
  );
}
