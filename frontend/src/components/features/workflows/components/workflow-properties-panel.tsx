"use client";

import {
  ChevronsRight,
  Copy,
  FolderOpen,
  Layers,
  MoveRight,
  PanelRightOpen,
  Settings2,
  Sliders,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

import { MultiStepLayoutPanel } from "./multi-step-layout-panel";
import { StepCatalog } from "./step-catalog";
import { WorkflowSchedulePanel } from "./workflow-schedule-panel";
import { WorkflowStaticAttributesPanel } from "./workflow-static-attributes-panel";
import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import type { PluginDefinition } from "../types/plugin-registry";
import type { StaticAttributeDef } from "../types/workflow-persistence";
import {
  DEFAULT_EDGE_LABEL_FONT_SIZE,
  DEFAULT_EDGE_STYLE,
  type EdgeStyle,
  type ProjectedCanvasNode,
  type StepPayload,
  type WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import { groupIdFromNodeId, isGroupCanvasNode } from "../utils/canvas-group-projection";
import type { AutoLayoutDirection } from "../utils/auto-layout";
import type { NodeAlignment } from "../utils/node-alignment";
import {
  CATEGORY_TILE_FALLBACK,
  categoryTileClasses,
  formatArtifactType,
  outcomeDotClasses,
  resolveStepIcon,
} from "../utils/step-visuals";

const EMPTY_EDGES: WorkflowCanvasEdge[] = [];

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

interface WorkflowPropertiesPanelProps {
  nodes: ProjectedCanvasNode[];
  edges?: WorkflowCanvasEdge[];
  plugins: PluginDefinition[];
  isPluginsLoading: boolean;
  pluginErrorMessage?: string;
  isInsideGroup?: boolean;
  onAddStep: (step: StepPayload) => void;
  onEdgeStyleChange?: (edgeId: string, style: EdgeStyle) => void;
  onEdgeLabelChange?: (edgeId: string, label: string) => void;
  onEdgeStartLabelChange?: (edgeId: string, label: string) => void;
  onEdgeEndLabelChange?: (edgeId: string, label: string) => void;
  onEdgeLabelBoldChange?: (edgeId: string, bold: boolean) => void;
  onEdgeLabelFontSizeChange?: (edgeId: string, fontSize: number) => void;
  onAlignNodes?: (nodeIds: string[], alignment: NodeAlignment) => void;
  autoLayoutDirection: AutoLayoutDirection;
  isAutoLayoutRunning?: boolean;
  onAutoLayoutDirectionChange: (direction: AutoLayoutDirection) => void;
  onAutoLayoutNodes?: (nodeIds: string[]) => void;
  onDeleteNodes?: (nodeIds: string[]) => void;
  onDeleteEdge?: (edgeId: string) => void;
  onDuplicateNode?: (nodeId: string) => void;
  onNodeTitleChange?: (nodeId: string, title: string) => void;
  onGroupSelectedSteps?: (nodeIds: string[]) => void;
  onRenameGroup?: (groupId: string, title: string) => void;
  onUngroupGroup?: (groupId: string) => void;
  onOpenGroup?: (groupId: string) => void;
  staticAttributes: StaticAttributeDef[];
  onStaticAttributesChange: (next: StaticAttributeDef[]) => void;
}

function DataContractChips({ capabilities, emptyLabel }: { capabilities: string[]; emptyLabel: string }) {
  if (capabilities.length === 0) {
    return <span className="text-[11.5px] text-muted-foreground">{emptyLabel}</span>;
  }
  return (
    <>
      {capabilities.map((capability) => (
        <span
          key={capability}
          className="rounded-[6px] border bg-muted px-2 py-0.5 font-mono text-[11px] text-muted-foreground"
        >
          {capability}
        </span>
      ))}
    </>
  );
}

export function WorkflowPropertiesPanel({
  nodes,
  edges = EMPTY_EDGES,
  plugins,
  isPluginsLoading,
  pluginErrorMessage,
  isInsideGroup = false,
  onAddStep,
  onEdgeStyleChange,
  onEdgeLabelChange,
  onEdgeStartLabelChange,
  onEdgeEndLabelChange,
  onEdgeLabelBoldChange,
  onEdgeLabelFontSizeChange,
  onAlignNodes,
  autoLayoutDirection,
  isAutoLayoutRunning = false,
  onAutoLayoutDirectionChange,
  onAutoLayoutNodes,
  onDeleteNodes,
  onDeleteEdge,
  onDuplicateNode,
  onNodeTitleChange,
  onGroupSelectedSteps,
  onRenameGroup,
  onUngroupGroup,
  onOpenGroup,
  staticAttributes,
  onStaticAttributesChange,
}: WorkflowPropertiesPanelProps) {
  const rightPanelTab = useWorkflowBuilderStore((state) => state.rightPanelTab);
  const setRightPanelTab = useWorkflowBuilderStore((state) => state.setRightPanelTab);
  const selectedNodeId = useWorkflowBuilderStore((state) => state.selectedNodeId);
  const selectedEdgeId = useWorkflowBuilderStore((state) => state.selectedEdgeId);
  const openConfigModal = useWorkflowBuilderStore((state) => state.openConfigModal);
  const [isCollapsed, setIsCollapsed] = useState(false);

  const selectedCanvasNodes = useMemo(
    () => nodes.filter((node) => node.selected),
    [nodes],
  );
  const isMultiSelect = selectedCanvasNodes.length > 1;

  const singleNode = useMemo(() => {
    if (selectedCanvasNodes.length === 1) return selectedCanvasNodes[0];
    if (selectedCanvasNodes.length === 0 && selectedNodeId) {
      return nodes.find((node) => node.id === selectedNodeId) ?? null;
    }
    return null;
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

  const subtitle =
    rightPanelTab === "steps"
      ? "Drag onto the canvas, or click to add."
      : selectedEdge
        ? "Connection between two steps."
        : isMultiSelect
          ? `${selectedCanvasNodes.length} steps selected on the canvas.`
          : singleNode
            ? "Step settings and configuration."
            : "Schedule this workflow, or select a step, an edge, or multiple steps.";

  if (isCollapsed) {
    return (
      <aside className="flex w-11 shrink-0 flex-col items-center border-l bg-card pt-3.5">
        <Button
          aria-label="Expand panel"
          onClick={() => setIsCollapsed(false)}
          size="icon"
          variant="ghost"
        >
          <PanelRightOpen className="size-4" />
        </Button>
      </aside>
    );
  }

  return (
    <aside className="flex w-[344px] shrink-0 flex-col border-l bg-card">
      <div className="shrink-0 border-b px-3.5 pt-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex gap-1 rounded-[10px] border bg-muted p-[3px]">
            <button
              className={cn(
                "flex items-center gap-1.5 rounded-[7px] px-[14px] py-[6px] text-[13px] font-medium transition-colors",
                rightPanelTab === "steps"
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
              onClick={() => setRightPanelTab("steps")}
              type="button"
            >
              <Layers className="size-3.5" aria-hidden />
              Steps
            </button>
            <button
              className={cn(
                "flex items-center gap-1.5 rounded-[7px] px-[14px] py-[6px] text-[13px] font-medium transition-colors",
                rightPanelTab === "properties"
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
              onClick={() => setRightPanelTab("properties")}
              type="button"
            >
              <Sliders className="size-3.5" aria-hidden />
              Properties
            </button>
          </div>
          <Button
            aria-label="Collapse panel"
            onClick={() => setIsCollapsed(true)}
            size="icon"
            variant="ghost"
          >
            <ChevronsRight className="size-4" />
          </Button>
        </div>
        <p className="p-[11px_2px_12px] text-xs text-muted-foreground">{subtitle}</p>
      </div>

      {rightPanelTab === "steps" ? (
        <StepCatalog
          errorMessage={pluginErrorMessage}
          isLoading={isPluginsLoading}
          onAddStep={onAddStep}
          plugins={plugins}
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto p-[16px_16px_24px]">
          {selectedEdge ? (
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
                Connection
              </span>
              <div className="mt-2 flex items-center gap-2 text-[14px] font-semibold">
                <span className="min-w-0 truncate">
                  {sourceNode?.data.title ?? selectedEdge.source}
                </span>
                <MoveRight className="size-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 truncate">
                  {targetNode?.data.title ?? selectedEdge.target}
                </span>
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
                    onChange={(event) =>
                      onEdgeStartLabelChange?.(selectedEdge.id, event.target.value)
                    }
                    placeholder="Label near the start of the edge"
                    value={selectedEdge.data?.startLabel ?? ""}
                  />
                </div>
                <div>
                  <span className="text-[10.5px] font-medium text-muted-foreground">Middle</span>
                  <Input
                    className="mt-1"
                    onChange={(event) => onEdgeLabelChange?.(selectedEdge.id, event.target.value)}
                    placeholder="Label at the middle of the edge"
                    value={selectedEdge.data?.label ?? ""}
                  />
                </div>
                <div>
                  <span className="text-[10.5px] font-medium text-muted-foreground">End</span>
                  <Input
                    className="mt-1"
                    onChange={(event) =>
                      onEdgeEndLabelChange?.(selectedEdge.id, event.target.value)
                    }
                    placeholder="Label near the end of the edge"
                    value={selectedEdge.data?.endLabel ?? ""}
                  />
                </div>
                <div className="flex items-center justify-between gap-2 pt-1">
                  <span className="text-[10.5px] font-medium text-muted-foreground">Bold</span>
                  <Switch
                    aria-label="Bold edge labels"
                    checked={!!selectedEdge.data?.labelBold}
                    onCheckedChange={(checked) =>
                      onEdgeLabelBoldChange?.(selectedEdge.id, checked)
                    }
                  />
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10.5px] font-medium text-muted-foreground">
                    Font size (px)
                  </span>
                  <Input
                    className="h-8 w-16 text-xs"
                    min={8}
                    max={32}
                    onChange={(event) =>
                      onEdgeLabelFontSizeChange?.(
                        selectedEdge.id,
                        Number(event.target.value) || DEFAULT_EDGE_LABEL_FONT_SIZE,
                      )
                    }
                    type="number"
                    value={selectedEdge.data?.labelFontSize ?? DEFAULT_EDGE_LABEL_FONT_SIZE}
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
                    onClick={() => onEdgeStyleChange?.(selectedEdge.id, option.value)}
                    size="sm"
                    variant={
                      (selectedEdge.data?.edgeStyle ?? DEFAULT_EDGE_STYLE) === option.value
                        ? "default"
                        : "outline"
                    }
                  >
                    {option.label}
                  </Button>
                ))}
              </div>
              <p className="mt-3 text-[11.5px] leading-[1.5] text-muted-foreground">
                {
                  EDGE_STYLE_DESCRIPTIONS[
                    selectedEdge.data?.edgeStyle ?? DEFAULT_EDGE_STYLE
                  ]
                }
              </p>

              <Button
                className="mt-[18px] w-full gap-1.5 border-destructive/30 text-destructive hover:bg-destructive/5 hover:text-destructive"
                onClick={() => onDeleteEdge?.(selectedEdge.id)}
                size="sm"
                variant="outline"
              >
                <Trash2 className="size-3.5" aria-hidden />
                Remove connection
              </Button>
            </div>
          ) : isMultiSelect ? (
            <MultiStepLayoutPanel
              nodes={selectedCanvasNodes}
              canGroup={
                !isInsideGroup &&
                selectedCanvasNodes.every((node) => groupIdFromNodeId(node.id) === null)
              }
              autoLayoutDirection={autoLayoutDirection}
              isAutoLayoutRunning={isAutoLayoutRunning}
              onAlign={(alignment) =>
                onAlignNodes?.(
                  selectedCanvasNodes.map((node) => node.id),
                  alignment,
                )
              }
              onAutoLayoutDirectionChange={onAutoLayoutDirectionChange}
              onAutoLayout={() =>
                onAutoLayoutNodes?.(selectedCanvasNodes.map((node) => node.id))
              }
              onDelete={() =>
                onDeleteNodes?.(selectedCanvasNodes.map((node) => node.id))
              }
              onGroup={() =>
                onGroupSelectedSteps?.(selectedCanvasNodes.map((node) => node.id))
              }
            />
          ) : singleNode && isGroupCanvasNode(singleNode) ? (
            <div>
              <div className="flex items-center gap-3">
                <span className="flex size-[42px] shrink-0 items-center justify-center rounded-lg bg-step-surface text-step-muted-foreground">
                  <FolderOpen className="size-[18px]" aria-hidden />
                </span>
                <span className="min-w-0 flex-1 text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
                  Group
                </span>
              </div>

              <Input
                className="mt-3 h-auto rounded-[9px] p-[9px_11px] text-[15px] font-semibold"
                onChange={(event) =>
                  onRenameGroup?.(singleNode.data.groupId, event.target.value)
                }
                value={singleNode.data.title}
              />
              <p className="mt-3 text-[12.5px] leading-[1.5] text-muted-foreground">
                {singleNode.data.memberCount} step
                {singleNode.data.memberCount === 1 ? "" : "s"} in this group.
              </p>

              <Button
                className="mt-5 w-full gap-2"
                onClick={() => onOpenGroup?.(singleNode.data.groupId)}
              >
                <FolderOpen className="size-4" aria-hidden />
                Open group
              </Button>
              <Button
                className="mt-2 w-full gap-1.5 border-destructive/30 text-destructive hover:bg-destructive/5 hover:text-destructive"
                onClick={() => onUngroupGroup?.(singleNode.data.groupId)}
                variant="outline"
              >
                <Trash2 className="size-3.5" aria-hidden />
                Ungroup
              </Button>
            </div>
          ) : singleNode ? (
            <div>
              <div className="flex items-center gap-3">
                <span
                  className={cn(
                    "flex size-[42px] shrink-0 items-center justify-center rounded-lg",
                    categoryTileClasses[singleNode.data.artifactType ?? singleNode.data.kind] ??
                      CATEGORY_TILE_FALLBACK,
                  )}
                >
                  {(() => {
                    const Icon = resolveStepIcon(
                      singleNode.data.kind,
                      singleNode.data.artifactType ?? singleNode.data.kind,
                    );
                    return <Icon className="size-[18px]" aria-hidden />;
                  })()}
                </span>
                <span className="min-w-0 flex-1 text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
                  {formatArtifactType(singleNode.data.artifactType ?? singleNode.data.kind)}
                </span>
              </div>

              <Input
                className="mt-3 h-auto rounded-[9px] p-[9px_11px] text-[15px] font-semibold"
                onChange={(event) => onNodeTitleChange?.(singleNode.id, event.target.value)}
                value={singleNode.data.title}
              />
              <p className="mt-3 text-[12.5px] leading-[1.5] text-muted-foreground">
                {singleNode.data.description}
              </p>

              <p className="mt-[18px] text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
                Data contract
              </p>
              <div className="mt-2.5 space-y-2.5">
                <div>
                  <p className="mb-1.5 text-[11.5px] text-muted-foreground">Requires (input)</p>
                  <div className="flex flex-wrap gap-1.5">
                    <DataContractChips
                      capabilities={[
                        ...(singleNode.data.requires ?? []),
                        ...(singleNode.data.requiresParsed ?? []),
                      ]}
                      emptyLabel="None — start step"
                    />
                  </div>
                </div>
                <div>
                  <p className="mb-1.5 text-[11.5px] text-muted-foreground">Produces (output)</p>
                  <div className="flex flex-wrap gap-1.5">
                    <DataContractChips
                      capabilities={[
                        ...(singleNode.data.produces ?? []),
                        ...(singleNode.data.producesParsed ?? []),
                      ]}
                      emptyLabel="Passes context through"
                    />
                  </div>
                </div>
              </div>

              {(singleNode.data.outcomes?.length ?? 0) > 0 ? (
                <>
                  <p className="mt-[18px] text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
                    Outcomes
                  </p>
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    {singleNode.data.outcomes?.map((outcome) => (
                      <span
                        key={outcome.name}
                        className="flex items-center gap-1.5 rounded-full border bg-muted/50 px-2.5 py-1 text-[11px] font-medium text-muted-foreground"
                      >
                        <span
                          className={cn("size-1.5 rounded-full", outcomeDotClasses(outcome.name))}
                        />
                        {outcome.name}
                      </span>
                    ))}
                  </div>
                </>
              ) : null}

              <Button
                className="mt-5 w-full gap-2"
                onClick={() => openConfigModal(singleNode.id)}
              >
                <Settings2 className="size-4" aria-hidden />
                Open configuration
              </Button>
              <div className="mt-2 flex gap-2">
                <Button
                  className="flex-1 gap-1.5"
                  onClick={() => onDuplicateNode?.(singleNode.id)}
                  variant="outline"
                >
                  <Copy className="size-3.5" aria-hidden />
                  Duplicate
                </Button>
                <Button
                  className="flex-1 gap-1.5 border-destructive/30 text-destructive hover:bg-destructive/5 hover:text-destructive"
                  onClick={() => onDeleteNodes?.([singleNode.id])}
                  variant="outline"
                >
                  <Trash2 className="size-3.5" aria-hidden />
                  Delete
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              <WorkflowSchedulePanel />
              <WorkflowStaticAttributesPanel
                value={staticAttributes}
                onChange={onStaticAttributesChange}
              />
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
