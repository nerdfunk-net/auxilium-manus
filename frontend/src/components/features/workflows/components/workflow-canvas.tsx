"use client";

import {
  addEdge,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  type Connection,
  type EdgeTypes,
  type FinalConnectionState,
  type NodeTypes,
  type OnEdgesChange,
  type OnNodesChange,
} from "@xyflow/react";
import type { Dispatch, MouseEvent, SetStateAction } from "react";
import { useCallback, useMemo } from "react";

import { useToast } from "@/hooks/use-toast";
import { isCompatible, type Capability } from "@/lib/capability-types";

import "@xyflow/react/dist/style.css";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import {
  computeOutcomeProvides,
  getOutcomeProvides,
} from "../utils/capability-graph";
import type { PluginDefinition } from "../types/plugin-registry";
import type {
  WorkflowCanvasEdge,
  WorkflowCanvasNode,
  WorkflowNodeKind,
  WorkflowOutcomeField,
} from "../types/workflow-canvas";
import { WaypointEdge } from "./edges/waypoint-edge";
import { WorkflowNode } from "./nodes/workflow-node";
import { NodePalette } from "./workflow-node-palette";

const nodeTypes: NodeTypes = {
  workflowNode: WorkflowNode,
};

const edgeTypes: EdgeTypes = {
  waypoint: WaypointEdge,
};

interface WorkflowCanvasProps {
  nodes: WorkflowCanvasNode[];
  edges: WorkflowCanvasEdge[];
  isPluginsLoading: boolean;
  pluginErrorMessage?: string;
  plugins: PluginDefinition[];
  onNodesChange: OnNodesChange<WorkflowCanvasNode>;
  onEdgesChange: OnEdgesChange<WorkflowCanvasEdge>;
  setEdges: Dispatch<SetStateAction<WorkflowCanvasEdge[]>>;
  onAddStep: (step: {
    kind: WorkflowNodeKind;
    title: string;
    description: string;
    artifactType: string;
    requires: Capability[];
    requiresParsed: string[];
    produces: Capability[];
    producesParsed: string[];
    consumes: Capability[];
    outcomes: WorkflowOutcomeField[];
  }) => void;
}

export function WorkflowCanvas({
  nodes,
  edges,
  isPluginsLoading,
  pluginErrorMessage,
  plugins,
  onNodesChange,
  onEdgesChange,
  setEdges,
  onAddStep,
}: WorkflowCanvasProps) {
  const selectNode = useWorkflowBuilderStore((state) => state.selectNode);
  const selectEdge = useWorkflowBuilderStore((state) => state.selectEdge);
  const isActionsPanelVisible = useWorkflowBuilderStore(
    (state) => state.isActionsPanelVisible,
  );
  const { toast } = useToast();

  const outcomeProvides = useMemo(
    () => computeOutcomeProvides(nodes, edges),
    [nodes, edges],
  );

  const handleConnect = useCallback(
    (connection: Connection) => {
      setEdges((currentEdges) => addEdge({ ...connection, type: "waypoint" }, currentEdges));
    },
    [setEdges],
  );

  const isValidConnection = useCallback(
    (connection: Connection | WorkflowCanvasEdge): boolean => {
      const sourceNode = nodes.find((n) => n.id === connection.source);
      const targetNode = nodes.find((n) => n.id === connection.target);
      if (!sourceNode || !targetNode) return false;

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
    [nodes, outcomeProvides],
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
    (_: MouseEvent, node: WorkflowCanvasNode) => {
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
    selectNode(null);
  }, [selectNode]);

  return (
    <div className="relative h-full overflow-hidden bg-slate-50">
      <ReactFlow<WorkflowCanvasNode, WorkflowCanvasEdge>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        defaultEdgeOptions={{ type: "waypoint" }}
        onConnect={handleConnect}
        onConnectEnd={handleConnectEnd}
        isValidConnection={isValidConnection}
        onEdgeClick={handleEdgeClick}
        onNodeClick={handleNodeClick}
        onPaneClick={handlePaneClick}
        fitView
        fitViewOptions={{ padding: 0.2 }}
      >
        <Background
          color="#cbd5e1"
          gap={22}
          size={1}
          variant={BackgroundVariant.Dots}
        />
        <Controls />
        <MiniMap pannable zoomable />
      </ReactFlow>
      {nodes.length === 0 ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="max-w-sm rounded-2xl border bg-card/95 p-6 text-center shadow-sm">
            <p className="text-sm font-semibold">Start your workflow</p>
            <p className="mt-2 text-sm text-muted-foreground">
              Use the step palette to add device selection, command, condition,
              or artifact steps to the canvas.
            </p>
          </div>
        </div>
      ) : null}
      {isActionsPanelVisible ? (
        <NodePalette
          errorMessage={pluginErrorMessage}
          isLoading={isPluginsLoading}
          onAddStep={onAddStep}
          plugins={plugins}
        />
      ) : null}
    </div>
  );
}
