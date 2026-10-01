"use client";

import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type EdgeTypes,
  type FinalConnectionState,
  type NodeTypes,
  type OnEdgesChange,
  type OnNodeDrag,
  type OnMoveEnd,
  type OnNodesChange,
  type OnSelectionChangeFunc,
  type Viewport,
} from "@xyflow/react";
import type { DragEvent, MouseEvent } from "react";
import { FolderOutput } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";
import { isCompatible } from "@/lib/capability-types";

import "@xyflow/react/dist/style.css";

import type { GroupConnectionEnds } from "../hooks/use-workflow-canvas-core";
import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import { getOutcomeProvides, type OutcomeProvides } from "../utils/capability-graph";
import { isGroupCanvasNode } from "../utils/canvas-group-projection";
import {
  draggableStepIds,
  findGroupNodeAtPoint,
  isPointInClientRect,
} from "../utils/canvas-group-dnd";
import { findPluginByKind, STEP_DRAG_MIME_TYPE, toStepPayload } from "../utils/step-catalog";
import type { PluginDefinition } from "../types/plugin-registry";
import {
  BACKGROUND_Z_INDEX,
  DEFAULT_EDGE_STYLE,
  EDGE_Z_INDEX,
  FOREGROUND_Z_INDEX,
  FUNNEL_KIND,
  isCanvasDecorationKind,
  isFunnelKind,
  sortNodesForContainment,
  type ProjectedCanvasNode,
  type StepPayload,
  type WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import type { NodeValidationSummary } from "../hooks/use-workflow-validation";
import { WaypointEdge } from "./edges/waypoint-edge";
import { CollapsibleMiniMap } from "./collapsible-minimap";
import { GroupNode } from "./nodes/group-node";
import { BackgroundNode } from "./nodes/background-node";
import { FunnelNode } from "./nodes/funnel-node";
import { LabelNode } from "./nodes/label-node";
import { WorkflowNode } from "./nodes/workflow-node";

const nodeTypes: NodeTypes = {
  workflowNode: WorkflowNode,
  groupNode: GroupNode,
  labelNode: LabelNode,
  backgroundNode: BackgroundNode,
  funnelNode: FunnelNode,
};

const edgeTypes: EdgeTypes = {
  waypoint: WaypointEdge,
};

// Half the fixed node footprint (w-80 h-32), used to center a dropped step on the pointer.
const NODE_DROP_OFFSET = { x: 160, y: 64 };
const LABEL_DROP_OFFSET = { x: 100, y: 20 };
const BACKGROUND_DROP_OFFSET = { x: 240, y: 160 };
// Half the funnel node's footprint (size-10 = 2.5rem = 40px).
const FUNNEL_DROP_OFFSET = { x: 20, y: 20 };

// Kept equal to the <Background> dots' `gap={22}` below, so that when the
// "Show grid" toggle is on a snapped position lands exactly on a grid dot.
const SNAP_GRID: [number, number] = [22, 22];

// xyflow's own default is the single key "Backspace". Add "Delete" so
// forward-delete keys (macOS fn+delete, the German "Entf" key) also work —
// both report KeyboardEvent.key === "Delete" regardless of keyboard layout.
const DELETE_KEY_CODES = ["Backspace", "Delete"];

const EMPTY_VALIDATION_BY_NODE_ID: Record<string, NodeValidationSummary> = {};

interface DragTargetState {
  dropTargetGroupId: string | null;
  overDropZone: boolean;
}

/** Client coordinates of a mouse or touch drag event, or null if unavailable. */
function clientPoint(event: unknown): { x: number; y: number } | null {
  const e = event as {
    clientX?: number;
    clientY?: number;
    changedTouches?: ArrayLike<{ clientX: number; clientY: number }>;
  };
  if (typeof e.clientX === "number" && typeof e.clientY === "number") {
    return { x: e.clientX, y: e.clientY };
  }
  const touch = e.changedTouches?.[0];
  return touch ? { x: touch.clientX, y: touch.clientY } : null;
}

interface WorkflowCanvasProps {
  nodes: ProjectedCanvasNode[];
  edges: WorkflowCanvasEdge[];
  plugins: PluginDefinition[];
  onNodesChange: OnNodesChange<ProjectedCanvasNode>;
  onEdgesChange: OnEdgesChange<WorkflowCanvasEdge>;
  onConnect: (connection: Connection) => void;
  onAddStepAtPosition: (step: StepPayload, position: { x: number; y: number }) => void;
  /** Member steps that can take/provide a connection touching a collapsed group (flat-graph aware). */
  /**
   * Capability guarantees per step outcome, computed on the FLAT graph. The
   * rendered `nodes`/`edges` are a view (an open group shows only its own
   * members), so they can't be used to judge what an upstream step provides.
   */
  outcomeProvides: Map<string, OutcomeProvides>;
  getGroupConnectionEnds: (connection: Connection | WorkflowCanvasEdge) => GroupConnectionEnds;
  /** True while an opened group is shown instead of the root canvas. */
  isInsideGroup?: boolean;
  /** Fired when real steps are dropped onto a collapsed group node. */
  onMoveNodesToGroup?: (nodeIds: string[], groupId: string) => void;
  /** Fired when steps are dropped on the "move out of group" strip. */
  onMoveNodesOutOfGroup?: (nodeIds: string[]) => void;
  /** Pan/zoom to restore on initial mount, e.g. from a pre-navigation draft. Omit (or null) to fit-to-content instead. */
  initialViewport?: Viewport | null;
  /** Fired once per pan/zoom gesture (not per frame) so the caller can remember it for the next mount. */
  onViewportChange?: (viewport: Viewport) => void;
  /** Error/warning counts from the last Validate run, keyed by node id — merged into each node's `data.validation` as a view-only annotation (see WorkflowNodeData). */
  validationByNodeId?: Record<string, NodeValidationSummary>;
}

function isDropTargetGroup(node: ProjectedCanvasNode, groupId: string | null): boolean {
  return groupId !== null && node.type === "groupNode" && node.data.groupId === groupId;
}

function WorkflowCanvasInner({
  nodes,
  edges,
  plugins,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onAddStepAtPosition,
  outcomeProvides,
  getGroupConnectionEnds,
  isInsideGroup = false,
  onMoveNodesToGroup,
  onMoveNodesOutOfGroup,
  initialViewport,
  onViewportChange,
  validationByNodeId = EMPTY_VALIDATION_BY_NODE_ID,
}: WorkflowCanvasProps) {
  const selectNode = useWorkflowBuilderStore((state) => state.selectNode);
  const selectEdge = useWorkflowBuilderStore((state) => state.selectEdge);
  const selectCanvasBackground = useWorkflowBuilderStore((state) => state.selectCanvasBackground);
  const setRightPanelTab = useWorkflowBuilderStore((state) => state.setRightPanelTab);
  const pendingFitViewNodeIds = useWorkflowBuilderStore((state) => state.pendingFitViewNodeIds);
  const clearFitViewRequest = useWorkflowBuilderStore((state) => state.clearFitViewRequest);
  const snapToGrid = useWorkflowBuilderStore((state) => state.snapToGrid);
  const showGrid = useWorkflowBuilderStore((state) => state.showGrid);
  const { toast } = useToast();
  const { screenToFlowPosition, fitView } = useReactFlow();
  const dropZoneRef = useRef<HTMLDivElement>(null);
  // Non-null only while a node drag is in progress; updated only when a value
  // actually changes so a drag doesn't re-render the canvas on every mousemove.
  const [dragTarget, setDragTarget] = useState<DragTargetState | null>(null);

  const resolveDragTarget = useCallback(
    (event: unknown, draggedNodes: ProjectedCanvasNode[]): DragTargetState => {
      const point = clientPoint(event);
      if (!point || draggableStepIds(draggedNodes).length === 0) {
        return { dropTargetGroupId: null, overDropZone: false };
      }
      if (isInsideGroup) {
        const rect = dropZoneRef.current?.getBoundingClientRect();
        return {
          dropTargetGroupId: null,
          overDropZone: rect ? isPointInClientRect(point.x, point.y, rect) : false,
        };
      }
      const flowPoint = screenToFlowPosition(point);
      const draggedIds = new Set(draggedNodes.map((n) => n.id));
      return {
        dropTargetGroupId: findGroupNodeAtPoint(flowPoint, nodes, draggedIds),
        overDropZone: false,
      };
    },
    [isInsideGroup, nodes, screenToFlowPosition],
  );

  const handleNodeDragStart = useCallback<OnNodeDrag<ProjectedCanvasNode>>(() => {
    setDragTarget({ dropTargetGroupId: null, overDropZone: false });
  }, []);

  const handleNodeDrag = useCallback<OnNodeDrag<ProjectedCanvasNode>>(
    (event, _node, draggedNodes) => {
      const next = resolveDragTarget(event, draggedNodes);
      setDragTarget((current) =>
        current &&
        current.dropTargetGroupId === next.dropTargetGroupId &&
        current.overDropZone === next.overDropZone
          ? current
          : next,
      );
    },
    [resolveDragTarget],
  );

  const handleNodeDragStop = useCallback<OnNodeDrag<ProjectedCanvasNode>>(
    (event, _node, draggedNodes) => {
      const target = resolveDragTarget(event, draggedNodes);
      setDragTarget(null);
      const stepIds = draggableStepIds(draggedNodes);
      if (stepIds.length === 0) return;
      if (target.dropTargetGroupId) {
        onMoveNodesToGroup?.(stepIds, target.dropTargetGroupId);
      } else if (target.overDropZone) {
        onMoveNodesOutOfGroup?.(stepIds);
      }
    },
    [resolveDragTarget, onMoveNodesToGroup, onMoveNodesOutOfGroup],
  );

  // Auto-layout is the only canvas operation that deliberately moves the
  // camera (see LAYOUT.md "Viewport after layout") — alignment/drag never do.
  useEffect(() => {
    if (!pendingFitViewNodeIds || pendingFitViewNodeIds.length === 0) return;
    fitView({
      nodes: pendingFitViewNodeIds.map((id) => ({ id })),
      padding: 0.2,
      duration: 300,
    });
    clearFitViewRequest();
  }, [pendingFitViewNodeIds, fitView, clearFitViewRequest]);

  const isValidConnection = useCallback(
    (connection: Connection | WorkflowCanvasEdge): boolean => {
      const sourceNode = nodes.find((n) => n.id === connection.source);
      const targetNode = nodes.find((n) => n.id === connection.target);
      if (!sourceNode || !targetNode) return false;

      // Canvas decorations (label / background) never accept or emit edges.
      if (
        isCanvasDecorationKind(sourceNode.data.kind) ||
        isCanvasDecorationKind(targetNode.data.kind)
      ) {
        return false;
      }

      const sourceIsFunnel = isFunnelKind(sourceNode.data.kind);
      const targetIsFunnel = isFunnelKind(targetNode.data.kind);

      // No chaining — a funnel's one outgoing edge must land on a real step.
      if (sourceIsFunnel && targetIsFunnel) {
        return false;
      }

      // A funnel accepts unlimited incoming edges but requires exactly one
      // outgoing edge — reject a second connection leaving the same funnel.
      if (sourceIsFunnel) {
        const alreadyHasOutgoing = edges.some((edge) => edge.source === connection.source);
        return !alreadyHasOutgoing;
      }

      // Capability compatibility is intentionally not checked for edges into
      // a funnel — it's a pass-through with no requires/produces of its own.
      // Correctness is enforced at run time once StepRunner splices the
      // funnel out and the real source/target guards run against each other.
      if (targetIsFunnel) {
        return true;
      }

      // A collapsed group has no fixed step: the connection is valid when at
      // least one member can take (or provide) it. The group node's own
      // requires/produces only reflect existing boundary ports, so they can't
      // be used here.
      if (isGroupCanvasNode(sourceNode) || isGroupCanvasNode(targetNode)) {
        const ends = getGroupConnectionEnds(connection);
        return (ends.source?.length ?? 1) > 0 && (ends.target?.length ?? 1) > 0;
      }

      const provided = getOutcomeProvides(
        outcomeProvides,
        connection.source ?? "",
        connection.sourceHandle,
      );
      const requiredCapabilities = targetNode.data.requires ?? [];
      const requiredParsed = targetNode.data.requiresParsed ?? [];

      if (requiredCapabilities.length === 0 && requiredParsed.length === 0) {
        return false;
      }

      if (
        requiredCapabilities.length > 0 &&
        connection.targetHandle &&
        connection.targetHandle !== "input"
      ) {
        return false;
      }

      return isCompatible(
        {
          capabilities: provided.capabilities,
          parsedKeys: provided.parsedKeys,
        },
        {
          capabilities: requiredCapabilities,
          parsedKeys: requiredParsed,
        },
      );
    },
    [nodes, edges, outcomeProvides, getGroupConnectionEnds],
  );
  const handleConnectEnd = useCallback(
    (_: unknown, connectionState: FinalConnectionState) => {
      if (connectionState.isValid === false) {
        toast({
          title: "Incompatible step types",
          description:
            "The upstream step does not provide the capabilities required by the target step.",
          variant: "destructive",
        });
      }
    },
    [toast],
  );

  const handleNodeClick = useCallback(
    (_: MouseEvent, node: ProjectedCanvasNode) => {
      selectNode(node.id);
    },
    [selectNode],
  );
  const handleEdgeClick = useCallback(
    (_: MouseEvent, edge: WorkflowCanvasEdge) => {
      selectEdge(edge.id);
    },
    [selectEdge],
  );
  const handlePaneClick = useCallback(() => {
    selectCanvasBackground();
  }, [selectCanvasBackground]);

  // Box-select (drag rubber-band) doesn't fire onNodeClick, so multi-select needs its
  // own hook into the Steps/Properties auto-switch behaviour.
  const handleSelectionChange = useCallback<OnSelectionChangeFunc>(
    ({ nodes: selectedNodes, edges: selectedEdges }) => {
      if (selectedNodes.length > 1) {
        setRightPanelTab("properties");
      } else if (selectedNodes.length === 0 && selectedEdges.length === 0) {
        setRightPanelTab("steps");
      }
    },
    [setRightPanelTab],
  );

  const handleDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (event.dataTransfer.types.includes(STEP_DRAG_MIME_TYPE)) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    }
  }, []);

  const handleDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      const kind = event.dataTransfer.getData(STEP_DRAG_MIME_TYPE);
      if (!kind) return;
      event.preventDefault();

      const plugin = findPluginByKind(plugins, kind);
      if (!plugin) return;

      const flowPosition = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      const offset =
        kind === "label"
          ? LABEL_DROP_OFFSET
          : kind === "background"
            ? BACKGROUND_DROP_OFFSET
            : kind === FUNNEL_KIND
              ? FUNNEL_DROP_OFFSET
              : NODE_DROP_OFFSET;
      onAddStepAtPosition(toStepPayload(plugin), {
        x: flowPosition.x - offset.x,
        y: flowPosition.y - offset.y,
      });
    },
    [plugins, screenToFlowPosition, onAddStepAtPosition],
  );

  // Backgrounds must stay under edges and steps. React Flow renders the edge
  // SVG before the nodes layer, so only a negative node z-index sits behind wires.
  const layeredNodes = useMemo(
    () =>
      sortNodesForContainment(nodes).map((node) => {
        const withFlags: ProjectedCanvasNode = isDropTargetGroup(
          node,
          dragTarget?.dropTargetGroupId ?? null,
        )
          ? ({ ...node, data: { ...node.data, isDropTarget: true } } as ProjectedCanvasNode)
          : node;
        const withValidation: ProjectedCanvasNode =
          withFlags.type === "workflowNode" && validationByNodeId[withFlags.id]
            ? {
                ...withFlags,
                data: { ...withFlags.data, validation: validationByNodeId[withFlags.id] },
              }
            : withFlags;
        if (withValidation.type === "backgroundNode") {
          return withValidation.zIndex === BACKGROUND_Z_INDEX
            ? withValidation
            : { ...withValidation, zIndex: BACKGROUND_Z_INDEX };
        }
        // Step Groups are layered with steps and labels: a group dropped onto
        // a background must never end up beneath it.
        if (
          withValidation.type === "labelNode" ||
          withValidation.type === "workflowNode" ||
          withValidation.type === "groupNode"
        ) {
          return withValidation.zIndex === FOREGROUND_Z_INDEX
            ? withValidation
            : { ...withValidation, zIndex: FOREGROUND_Z_INDEX };
        }
        return withValidation;
      }),
    [nodes, validationByNodeId, dragTarget?.dropTargetGroupId],
  );

  const handleMoveEnd: OnMoveEnd = useCallback(
    (_event, viewport) => onViewportChange?.(viewport),
    [onViewportChange],
  );

  return (
    <div
      className="relative h-full overflow-hidden bg-muted"
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <ReactFlow<ProjectedCanvasNode, WorkflowCanvasEdge>
        nodes={layeredNodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        defaultEdgeOptions={{
          type: "waypoint",
          zIndex: EDGE_Z_INDEX,
          data: { edgeStyle: DEFAULT_EDGE_STYLE },
        }}
        onConnect={onConnect}
        onConnectEnd={handleConnectEnd}
        isValidConnection={isValidConnection}
        onEdgeClick={handleEdgeClick}
        onNodeClick={handleNodeClick}
        onPaneClick={handlePaneClick}
        onSelectionChange={handleSelectionChange}
        onMoveEnd={handleMoveEnd}
        onNodeDragStart={handleNodeDragStart}
        onNodeDrag={handleNodeDrag}
        onNodeDragStop={handleNodeDragStop}
        snapToGrid={snapToGrid}
        snapGrid={SNAP_GRID}
        deleteKeyCode={DELETE_KEY_CODES}
        {...(initialViewport
          ? { defaultViewport: initialViewport }
          : { fitView: true, fitViewOptions: { padding: 0.2 } })}
      >
        {showGrid ? (
          <Background
            color="#94a3b8"
            gap={22}
            size={2}
            variant={BackgroundVariant.Dots}
          />
        ) : null}
        <Controls />
        <CollapsibleMiniMap />
      </ReactFlow>
      {isInsideGroup && dragTarget ? (
        <div
          ref={dropZoneRef}
          className={cn(
            "pointer-events-none absolute left-1/2 top-3 z-10 flex -translate-x-1/2 items-center gap-2 rounded-lg border-2 border-dashed bg-card/95 px-5 py-3 text-sm font-medium text-muted-foreground shadow-sm transition-colors",
            dragTarget.overDropZone && "border-ring bg-accent text-foreground",
          )}
        >
          <FolderOutput className="size-4" aria-hidden />
          Drop here to move out of group
        </div>
      ) : null}
      {nodes.length === 0 ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="max-w-sm rounded-2xl border bg-card/95 p-6 text-center shadow-sm">
            <p className="text-sm font-semibold">Start your workflow</p>
            <p className="mt-2 text-sm text-muted-foreground">
              Use the Steps panel on the right to add device selection, command,
              condition, or artifact steps to the canvas.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function WorkflowCanvas(props: WorkflowCanvasProps) {
  return (
    <ReactFlowProvider>
      <WorkflowCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
