"use client";

import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { NodeAlignment } from "../utils/node-alignment";
import type { WorkflowCanvasNode } from "../types/workflow-canvas";

interface MultiStepLayoutPanelProps {
  nodes: WorkflowCanvasNode[];
  onAlign: (alignment: NodeAlignment) => void;
  onDelete: () => void;
}

const ALIGN_ACTIONS: { alignment: NodeAlignment; label: string }[] = [
  { alignment: "align-left", label: "Left" },
  { alignment: "align-center-horizontal", label: "Center" },
  { alignment: "align-right", label: "Right" },
  { alignment: "align-top", label: "Top" },
  { alignment: "align-center-vertical", label: "Middle" },
  { alignment: "align-bottom", label: "Bottom" },
];

const DISTRIBUTE_ACTIONS: { alignment: NodeAlignment; label: string }[] = [
  { alignment: "distribute-horizontal", label: "Horizontal" },
  { alignment: "distribute-vertical", label: "Vertical" },
];

export function MultiStepLayoutPanel({ nodes, onAlign, onDelete }: MultiStepLayoutPanelProps) {
  const canDistribute = nodes.length >= 3;

  return (
    <div>
      <p className="text-[13px] font-semibold">{nodes.length} steps selected</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Align and distribute the selected steps.
      </p>

      <p className="mt-4 text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
        Align
      </p>
      <div className="mt-2.5 grid grid-cols-3 gap-1.5">
        {ALIGN_ACTIONS.map((action) => (
          <Button
            className="text-xs"
            key={action.alignment}
            onClick={() => onAlign(action.alignment)}
            size="sm"
            variant="outline"
          >
            {action.label}
          </Button>
        ))}
      </div>

      <p className="mt-4 text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
        Distribute
      </p>
      <div className="mt-2.5 grid grid-cols-2 gap-1.5">
        {DISTRIBUTE_ACTIONS.map((action) => (
          <Button
            className="text-xs"
            disabled={!canDistribute}
            key={action.alignment}
            onClick={() => onAlign(action.alignment)}
            size="sm"
            variant="outline"
          >
            {action.label}
          </Button>
        ))}
      </div>
      {!canDistribute ? (
        <p className="mt-1.5 text-[11px] leading-4 text-muted-foreground">
          Distribute needs at least three selected steps.
        </p>
      ) : null}

      <Button
        className="mt-4 w-full gap-1.5 border-destructive/30 text-destructive hover:bg-destructive/5 hover:text-destructive"
        onClick={onDelete}
        size="sm"
        variant="outline"
      >
        <Trash2 className="size-3.5" aria-hidden />
        Delete {nodes.length} steps
      </Button>
    </div>
  );
}
