"use client";

import { useEdgesState, useNodesState } from "@xyflow/react";
import { useCallback } from "react";

import { WorkflowCanvas } from "./components/workflow-canvas";
import { WorkflowExecutionsPanel } from "./components/workflow-executions-panel";
import { WorkflowPropertiesPanel } from "./components/workflow-properties-panel";
import { WorkflowRunControls } from "./components/workflow-run-controls";
import { WorkflowSidebar } from "./components/workflow-sidebar";
import { WorkflowTopbar } from "./components/workflow-topbar";
import {
  initialWorkflowEdges,
  initialWorkflowNodes,
} from "./constants/initial-workflow";
import { useWorkflowBuilderStore } from "./hooks/use-workflow-builder-store";
import type { WorkflowNodeKind } from "./types/workflow-canvas";
import { mapCanvasToWorkflowDefinition } from "./utils/workflow-mapper";
import { validateCanvasWorkflow } from "./utils/workflow-validation";

export function WorkflowBuilderPage() {
  const mode = useWorkflowBuilderStore((state) => state.mode);
  const workflowName = useWorkflowBuilderStore((state) => state.workflowName);
  const markSaved = useWorkflowBuilderStore((state) => state.markSaved);
  const markRunning = useWorkflowBuilderStore((state) => state.markRunning);
  const markError = useWorkflowBuilderStore((state) => state.markError);
  const selectNode = useWorkflowBuilderStore((state) => state.selectNode);
  const [nodes, setNodes, onNodesChange] = useNodesState(initialWorkflowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialWorkflowEdges);

  const handleSave = useCallback(() => {
    const validation = validateCanvasWorkflow(nodes, edges);
    const definition = mapCanvasToWorkflowDefinition(nodes, edges, {
      id: "workflow-network-backup",
      name: workflowName,
    });

    if (!validation.isValid) {
      markError(`Cannot save: ${validation.issues[0]}`);
      return;
    }

    markSaved(`Prepared ${definition.steps.length} executable steps locally`);
  }, [edges, markError, markSaved, nodes, workflowName]);

  const handleRun = useCallback(() => {
    const validation = validateCanvasWorkflow(nodes, edges);

    if (!validation.isValid) {
      markError(`Cannot run: ${validation.issues[0]}`);
      return;
    }

    const definition = mapCanvasToWorkflowDefinition(nodes, edges, {
      id: "workflow-network-backup",
      name: workflowName,
    });

    markRunning(`Mock execution queued for ${definition.steps.length} steps`);
  }, [edges, markError, markRunning, nodes, workflowName]);

  const handleAddStep = useCallback(
    (step: {
      kind: WorkflowNodeKind;
      title: string;
      description: string;
    }) => {
      const nextIndex = nodes.length + 1;
      const id = `${step.kind}-${nextIndex}`;

      setNodes((currentNodes) => [
        ...currentNodes,
        {
          id,
          type: "workflowNode",
          position: { x: 160 + nextIndex * 44, y: 460 },
          data: {
            kind: step.kind,
            title: step.title,
            description: step.description,
            status: "draft",
          },
        },
      ]);
      selectNode(id);
    },
    [nodes.length, selectNode, setNodes],
  );

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <WorkflowSidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <WorkflowTopbar onRun={handleRun} onSave={handleSave} />
        <main className="flex min-h-0 flex-1">
          <section className="min-w-0 flex-1">
            {mode === "editor" ? (
              <WorkflowCanvas
                edges={edges}
                nodes={nodes}
                onEdgesChange={onEdgesChange}
                onNodesChange={onNodesChange}
                onAddStep={handleAddStep}
                setEdges={setEdges}
              />
            ) : (
              <WorkflowExecutionsPanel />
            )}
          </section>
          {mode === "editor" ? <WorkflowPropertiesPanel nodes={nodes} /> : null}
        </main>
        <WorkflowRunControls />
      </div>
    </div>
  );
}
