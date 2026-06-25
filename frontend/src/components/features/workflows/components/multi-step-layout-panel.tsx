"use client";

import {
  AlignCenterHorizontal,
  AlignCenterVertical,
  AlignEndHorizontal,
  AlignEndVertical,
  AlignHorizontalDistributeCenter,
  AlignStartHorizontal,
  AlignStartVertical,
  AlignVerticalDistributeCenter,
} from "lucide-react";

import { Button } from "@/components/ui/button";

import type { NodeAlignment } from "../utils/node-alignment";
import type { WorkflowCanvasNode } from "../types/workflow-canvas";

interface MultiStepLayoutPanelProps {
  nodes: WorkflowCanvasNode[];
  onAlign: (alignment: NodeAlignment) => void;
}

type AlignmentAction = {
  alignment: NodeAlignment;
  label: string;
  icon: typeof AlignStartHorizontal;
  requiresThree?: boolean;
};

const ALIGNMENT_ACTIONS: AlignmentAction[] = [
  { alignment: "align-left", label: "Align left", icon: AlignStartVertical },
  { alignment: "align-center-horizontal", label: "Center horizontally", icon: AlignCenterVertical },
  { alignment: "align-right", label: "Align right", icon: AlignEndVertical },
  { alignment: "align-top", label: "Align top", icon: AlignStartHorizontal },
  { alignment: "align-center-vertical", label: "Center vertically", icon: AlignCenterHorizontal },
  { alignment: "align-bottom", label: "Align bottom", icon: AlignEndHorizontal },
  {
    alignment: "distribute-horizontal",
    label: "Distribute horizontally",
    icon: AlignHorizontalDistributeCenter,
    requiresThree: true,
  },
  {
    alignment: "distribute-vertical",
    label: "Distribute vertically",
    icon: AlignVerticalDistributeCenter,
    requiresThree: true,
  },
];

export function MultiStepLayoutPanel({ nodes, onAlign }: MultiStepLayoutPanelProps) {
  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Selected steps
        </p>
        <ul className="mt-2 space-y-1">
          {nodes.map((node) => (
            <li key={node.id} className="truncate text-sm">
              {node.data.title}
            </li>
          ))}
        </ul>
      </div>

      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Alignment
        </p>
        <div className="grid grid-cols-3 gap-2">
          {ALIGNMENT_ACTIONS.map((action) => {
            const Icon = action.icon;
            const disabled = action.requiresThree === true && nodes.length < 3;
            return (
              <Button
                key={action.alignment}
                type="button"
                variant="outline"
                size="sm"
                className="h-auto flex-col gap-1 px-2 py-2 text-[10px] leading-tight"
                disabled={disabled}
                title={action.label}
                onClick={() => onAlign(action.alignment)}
              >
                <Icon className="size-4 shrink-0" />
                <span>{action.label}</span>
              </Button>
            );
          })}
        </div>
        <p className="text-[11px] leading-4 text-muted-foreground">
          Distribute actions need at least three selected steps. Alignment uses each
          step&apos;s rendered size when available.
        </p>
      </div>
    </div>
  );
}
