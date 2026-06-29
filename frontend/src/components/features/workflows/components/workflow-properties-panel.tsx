"use client";

import {
  ChevronsRight,
  MoveRight,
  PanelRightOpen,
  Settings2,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";

import { MultiStepLayoutPanel } from "./multi-step-layout-panel";
import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import type {
  EdgeStyle,
  WorkflowCanvasEdge,
  WorkflowCanvasNode,
} from "../types/workflow-canvas";
import type { NodeAlignment } from "../utils/node-alignment";

const EMPTY_EDGES: WorkflowCanvasEdge[] = [];

interface WorkflowPropertiesPanelProps {
  nodes: WorkflowCanvasNode[];
  edges?: WorkflowCanvasEdge[];
  onEdgeStyleChange?: (edgeId: string, style: EdgeStyle) => void;
  onAlignNodes?: (nodeIds: string[], alignment: NodeAlignment) => void;
}

function SectionHeader({
  icon: Icon,
  label,
}: {
  icon: LucideIcon;
  label: string;
}) {
  return (
    <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
      <Icon className="size-3.5" />
      {label}
    </div>
  );
}

export function WorkflowPropertiesPanel({
  nodes,
  edges = EMPTY_EDGES,
  onEdgeStyleChange,
  onAlignNodes,
}: WorkflowPropertiesPanelProps) {
  const selectedNodeId = useWorkflowBuilderStore(
    (state) => state.selectedNodeId,
  );
  const selectedEdgeId = useWorkflowBuilderStore(
    (state) => state.selectedEdgeId,
  );
  const [isMinimized, setIsMinimized] = useState(false);

  const selectedCanvasNodes = useMemo(
    () => nodes.filter((node) => node.selected),
    [nodes],
  );
  const isMultiSelect = selectedCanvasNodes.length > 1;

  const isSingleNodeSelected = useMemo(() => {
    if (selectedCanvasNodes.length === 1) return true;
    if (selectedCanvasNodes.length === 0 && selectedNodeId) {
      return nodes.some((node) => node.id === selectedNodeId);
    }
    return false;
  }, [nodes, selectedCanvasNodes, selectedNodeId]);

  const selectedEdge = useMemo(
    () => edges.find((e) => e.id === selectedEdgeId),
    [edges, selectedEdgeId],
  );

  const sourceNode = useMemo(
    () => nodes.find((n) => n.id === selectedEdge?.source),
    [nodes, selectedEdge],
  );

  const targetNode = useMemo(
    () => nodes.find((n) => n.id === selectedEdge?.target),
    [nodes, selectedEdge],
  );

  if (isMinimized) {
    return (
      <aside className="flex w-8 shrink-0 flex-col items-center border-l bg-card pt-3">
        <Button
          aria-label="Expand step properties"
          onClick={() => setIsMinimized(false)}
          size="icon"
          variant="ghost"
        >
          <PanelRightOpen className="size-4" />
        </Button>
      </aside>
    );
  }

  return (
    <aside className="flex w-80 shrink-0 flex-col border-l bg-card">
      <div className="flex items-center justify-between border-b p-4">
        <div>
          <p className="text-sm font-semibold">
            {isMultiSelect ? "Selection" : "Properties"}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {isMultiSelect
              ? `${selectedCanvasNodes.length} steps selected on the canvas.`
              : "Select an edge or multiple steps."}
          </p>
        </div>
        <Button
          aria-label="Minimize step properties"
          onClick={() => setIsMinimized(true)}
          size="icon"
          variant="ghost"
        >
          <ChevronsRight className="size-4" />
        </Button>
      </div>

      {selectedEdge ? (
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <div className="mb-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Connection
            </p>
            <h2 className="mt-1 flex items-center gap-1.5 text-base font-semibold">
              <span className="truncate">
                {sourceNode?.data.title ?? selectedEdge.source}
              </span>
              <MoveRight className="size-4 shrink-0 text-muted-foreground" />
              <span className="truncate">
                {targetNode?.data.title ?? selectedEdge.target}
              </span>
            </h2>
            {selectedEdge.label ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Label: <span className="font-medium">{String(selectedEdge.label)}</span>
              </p>
            ) : null}
          </div>

          <div className="space-y-3">
            <SectionHeader icon={Settings2} label="Edge style" />
            <div className="flex gap-2">
              <Button
                className="flex-1"
                onClick={() => onEdgeStyleChange?.(selectedEdge.id, "straight")}
                size="sm"
                variant={
                  (selectedEdge.data?.edgeStyle ?? "straight") === "straight"
                    ? "default"
                    : "outline"
                }
              >
                Straight
              </Button>
              <Button
                className="flex-1"
                onClick={() => onEdgeStyleChange?.(selectedEdge.id, "smooth")}
                size="sm"
                variant={
                  selectedEdge.data?.edgeStyle === "smooth" ? "default" : "outline"
                }
              >
                Smooth
              </Button>
            </div>
            <p className="text-[11px] leading-4 text-muted-foreground">
              {(selectedEdge.data?.edgeStyle ?? "straight") === "straight"
                ? "Polyline path with bend points. Double-click the line to add a bend point, drag to reposition, right-click to remove."
                : "Bezier curve managed automatically. Bend points are inactive in smooth mode."}
            </p>
          </div>
        </div>
      ) : isMultiSelect ? (
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <MultiStepLayoutPanel
            nodes={selectedCanvasNodes}
            onAlign={(alignment) =>
              onAlignNodes?.(
                selectedCanvasNodes.map((node) => node.id),
                alignment,
              )
            }
          />
        </div>
      ) : isSingleNodeSelected ? (
        <div className="p-5 text-sm text-muted-foreground">
          Click the <span className="font-medium">Config</span> button on the node to open its settings.
        </div>
      ) : (
        <div className="p-5 text-sm text-muted-foreground">
          Select an edge or multiple nodes on the canvas to see controls here.
        </div>
      )}
    </aside>
  );
}
