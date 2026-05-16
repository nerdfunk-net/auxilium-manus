"use client";

import {
  addEdge,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  type Connection,
  type NodeTypes,
  type OnEdgesChange,
  type OnNodesChange,
} from "@xyflow/react";
import type { Dispatch, MouseEvent, SetStateAction } from "react";
import { useCallback } from "react";

import "@xyflow/react/dist/style.css";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import type {
  WorkflowCanvasEdge,
  WorkflowCanvasNode,
  WorkflowNodeKind,
} from "../types/workflow-canvas";
import { WorkflowNode } from "./nodes/workflow-node";
import { NodePalette } from "./workflow-node-palette";

const nodeTypes: NodeTypes = {
  workflowNode: WorkflowNode,
};

interface WorkflowCanvasProps {
  nodes: WorkflowCanvasNode[];
  edges: WorkflowCanvasEdge[];
  onNodesChange: OnNodesChange<WorkflowCanvasNode>;
  onEdgesChange: OnEdgesChange<WorkflowCanvasEdge>;
  setEdges: Dispatch<SetStateAction<WorkflowCanvasEdge[]>>;
  onAddStep: (step: {
    kind: WorkflowNodeKind;
    title: string;
    description: string;
  }) => void;
}

export function WorkflowCanvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  setEdges,
  onAddStep,
}: WorkflowCanvasProps) {
  const selectNode = useWorkflowBuilderStore((state) => state.selectNode);

  const handleConnect = useCallback(
    (connection: Connection) => {
      setEdges((currentEdges) => addEdge(connection, currentEdges));
    },
    [setEdges],
  );
  const handleNodeClick = useCallback(
    (_: MouseEvent, node: WorkflowCanvasNode) => {
      selectNode(node.id);
    },
    [selectNode],
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
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={handleConnect}
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
      <NodePalette onAddStep={onAddStep} />
    </div>
  );
}
