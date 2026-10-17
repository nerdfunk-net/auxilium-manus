"use client";

import { MoveRight, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

import {
  DEFAULT_EDGE_LABEL_FONT_SIZE,
  DEFAULT_EDGE_STYLE,
  type EdgeStyle,
  type WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import { CATEGORY_TILE_FALLBACK, categoryTileClasses } from "../utils/step-visuals";

const EDGE_STYLE_OPTIONS: { value: EdgeStyle; label: string }[] = [
  { value: "straight", label: "Straight" },
  { value: "bezier", label: "Bezier" },
  { value: "step", label: "Step" },
  { value: "smoothstep", label: "Smoothstep" },
];

const EDGE_STYLE_DESCRIPTIONS: Record<EdgeStyle, string> = {
  straight:
    "Polyline path with bend points. Double-click the line to add a bend point, drag to reposition, right-click to remove.",
  bezier: "Bezier curve managed automatically. Bend points are inactive in this style.",
  step:
    "Right-angle path with sharp corners, managed automatically. Bend points are inactive in this style.",
  smoothstep:
    "Right-angle path with rounded corners, managed automatically. Bend points are inactive in this style.",
};

interface SelectedEdgePanelProps {
  edge: WorkflowCanvasEdge;
  sourceTitle?: string;
  targetTitle?: string;
  onEdgeStyleChange?: (edgeId: string, style: EdgeStyle) => void;
  onEdgeLabelChange?: (edgeId: string, label: string) => void;
  onEdgeStartLabelChange?: (edgeId: string, label: string) => void;
  onEdgeEndLabelChange?: (edgeId: string, label: string) => void;
  onEdgeLabelBoldChange?: (edgeId: string, bold: boolean) => void;
  onEdgeLabelFontSizeChange?: (edgeId: string, fontSize: number) => void;
  onDeleteEdge?: (edgeId: string) => void;
}

export function SelectedEdgePanel({
  edge,
  sourceTitle,
  targetTitle,
  onEdgeStyleChange,
  onEdgeLabelChange,
  onEdgeStartLabelChange,
  onEdgeEndLabelChange,
  onEdgeLabelBoldChange,
  onEdgeLabelFontSizeChange,
  onDeleteEdge,
}: SelectedEdgePanelProps) {
  return (
    <div>
      <span className="text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
        Connection
      </span>
      <div className="mt-2 flex items-center gap-2 text-[14px] font-semibold">
        <span className="min-w-0 truncate">{sourceTitle ?? edge.source}</span>
        <MoveRight className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 truncate">{targetTitle ?? edge.target}</span>
      </div>

      <div className="mt-5 flex items-center gap-1.5">
        <p className="text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
          Add Edge Label
        </p>
        <span
          className={cn(
            "rounded-full px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[.05em]",
            categoryTileClasses.debug ?? CATEGORY_TILE_FALLBACK,
          )}
        >
          Debug
        </span>
      </div>
      <div className="mt-2.5 space-y-2">
        <div>
          <span className="text-[10.5px] font-medium text-muted-foreground">Start</span>
          <Input
            className="mt-1"
            onChange={(event) => onEdgeStartLabelChange?.(edge.id, event.target.value)}
            placeholder="Label near the start of the edge"
            value={edge.data?.startLabel ?? ""}
          />
        </div>
        <div>
          <span className="text-[10.5px] font-medium text-muted-foreground">Middle</span>
          <Input
            className="mt-1"
            onChange={(event) => onEdgeLabelChange?.(edge.id, event.target.value)}
            placeholder="Label at the middle of the edge"
            value={edge.data?.label ?? ""}
          />
        </div>
        <div>
          <span className="text-[10.5px] font-medium text-muted-foreground">End</span>
          <Input
            className="mt-1"
            onChange={(event) => onEdgeEndLabelChange?.(edge.id, event.target.value)}
            placeholder="Label near the end of the edge"
            value={edge.data?.endLabel ?? ""}
          />
        </div>
        <div className="flex items-center justify-between gap-2 pt-1">
          <span className="text-[10.5px] font-medium text-muted-foreground">Bold</span>
          <Switch
            aria-label="Bold edge labels"
            checked={!!edge.data?.labelBold}
            onCheckedChange={(checked) => onEdgeLabelBoldChange?.(edge.id, checked)}
          />
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10.5px] font-medium text-muted-foreground">Font size (px)</span>
          <Input
            className="h-8 w-16 text-xs"
            min={8}
            max={32}
            onChange={(event) =>
              onEdgeLabelFontSizeChange?.(
                edge.id,
                Number(event.target.value) || DEFAULT_EDGE_LABEL_FONT_SIZE,
              )
            }
            type="number"
            value={edge.data?.labelFontSize ?? DEFAULT_EDGE_LABEL_FONT_SIZE}
          />
        </div>
      </div>

      <p className="mt-5 text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
        Edge style
      </p>
      <div className="mt-2.5 grid grid-cols-2 gap-2">
        {EDGE_STYLE_OPTIONS.map((option) => (
          <Button
            key={option.value}
            onClick={() => onEdgeStyleChange?.(edge.id, option.value)}
            size="sm"
            variant={
              (edge.data?.edgeStyle ?? DEFAULT_EDGE_STYLE) === option.value ? "default" : "outline"
            }
          >
            {option.label}
          </Button>
        ))}
      </div>
      <p className="mt-3 text-[11.5px] leading-[1.5] text-muted-foreground">
        {EDGE_STYLE_DESCRIPTIONS[edge.data?.edgeStyle ?? DEFAULT_EDGE_STYLE]}
      </p>

      <Button
        className="mt-[18px] w-full gap-1.5 border-destructive/30 text-destructive hover:bg-destructive/5 hover:text-destructive"
        onClick={() => onDeleteEdge?.(edge.id)}
        size="sm"
        variant="outline"
      >
        <Trash2 className="size-3.5" aria-hidden />
        Remove connection
      </Button>
    </div>
  );
}
