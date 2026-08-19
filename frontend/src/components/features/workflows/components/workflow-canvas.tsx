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
  type OnMoveEnd,
  type OnNodesChange,
  type OnSelectionChangeFunc,
  type Viewport,
} from "@xyflow/react";
import type { DragEvent, MouseEvent } from "react";
import { useCallback, useMemo } from "react";

import { useToast } from "@/hooks/use-toast";
import { isCompatible } from "@/lib/capability-types";

import "@xyflow/react/dist/style.css";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import {
  computeOutcomeProvides,
  getOutcomeProvides,
} from "../utils/capability-graph";
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

interface WorkflowCanvasProps {
  nodes: ProjectedCanvasNode[];
  edges: WorkflowCanvasEdge[];
  plugins: PluginDefinition[];
  onNodesChange: OnNodesChange<ProjectedCanvasNode>;
  onEdgesChange: OnEdgesChange<WorkflowCanvasEdge>;
  onConnect: (connection: Connection) => void;
  onAddStepAtPosition: (step: StepPayload, position: { x: number; y: number }) => void;
  /** Pan/zoom to restore on initial mount, e.g. from a pre-navigation draft. Omit (or null) to fit-to-content instead. */
  initialViewport?: Viewport | null;
  /** Fired once per pan/zoom gesture (not per frame) so the caller can remember it for the next mount. */
  onViewportChange?: (viewport: Viewport) => void;
}

function WorkflowCanvasInner({
  nodes,
  edges,
  plugins,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onAddStepAtPosition,
  initialViewport,
  onViewportChange,
}: WorkflowCanvasProps) {
  const selectNode = useWorkflowBuilderStore((state) => state.selectNode);
  const selectEdge = useWorkflowBuilderStore((state) => state.selectEdge);
  const selectCanvasBackground = useWorkflowBuilderStore((state) => state.selectCanvasBackground);
  const setRightPanelTab = useWorkflowBuilderStore((state) => state.setRightPanelTab);
  const { toast } = useToast();
  const { screenToFlowPosition } = useReactFlow();

  const outcomeProvides = useMemo(
    () => computeOutcomeProvides(nodes, edges),
    [nodes, edges],
  );

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
    [nodes, edges, outcomeProvides],
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
        if (node.type === "backgroundNode") {
          return node.zIndex === BACKGROUND_Z_INDEX
            ? node
            : { ...node, zIndex: BACKGROUND_Z_INDEX };
        }
        if (node.type === "labelNode" || node.type === "workflowNode") {
          return node.zIndex === FOREGROUND_Z_INDEX
            ? node
            : { ...node, zIndex: FOREGROUND_Z_INDEX };
        }
        return node;
      }),
    [nodes],
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
        {...(initialViewport
          ? { defaultViewport: initialViewport }
          : { fitView: true, fitViewOptions: { padding: 0.2 } })}
      >
        <Background
          color="#cbd5e1"
          gap={22}
          size={1}
          variant={BackgroundVariant.Dots}
        />
        <Controls />
        <CollapsibleMiniMap />
      </ReactFlow>
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
