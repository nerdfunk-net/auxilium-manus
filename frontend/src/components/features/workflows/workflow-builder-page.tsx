"use client";

import { useEdgesState, useNodesState } from "@xyflow/react";
import { useCallback, useState } from "react";

import { useWorkflowMutations } from "@/hooks/queries/use-workflow-mutations";
import { useWorkflowStepsQuery } from "@/hooks/queries/use-workflow-steps-query";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { WorkflowCanvas } from "./components/workflow-canvas";
import { WorkflowExecutionsPanel } from "./components/workflow-executions-panel";
import { WorkflowPropertiesPanel } from "./components/workflow-properties-panel";
import { WorkflowRunControls } from "./components/workflow-run-controls";
import { WorkflowSidebar } from "./components/workflow-sidebar";
import { WorkflowTopbar } from "./components/workflow-topbar";
import { WorkflowManageDialog } from "./dialogs/workflow-manage-dialog";
import { WorkflowOpenDialog } from "./dialogs/workflow-open-dialog";
import { WorkflowSaveAsDialog } from "./dialogs/workflow-save-as-dialog";
import { useWorkflowBuilderStore } from "./hooks/use-workflow-builder-store";
import type { PluginDefinition } from "./types/plugin-registry";
import type { WorkflowSummary, WorkflowVisibility } from "./types/workflow-persistence";
import type {
  EdgeStyle,
  WorkflowCanvasEdge,
  WorkflowCanvasNode,
  WorkflowNodeKind,
} from "./types/workflow-canvas";
import { mapCanvasToWorkflowDefinition } from "./utils/workflow-mapper";
import { validateCanvasWorkflow } from "./utils/workflow-validation";

const EMPTY_PLUGINS: PluginDefinition[] = [];
const EMPTY_NODES: WorkflowCanvasNode[] = [];
const EMPTY_EDGES: WorkflowCanvasEdge[] = [];

export function WorkflowBuilderPage() {
  const mode = useWorkflowBuilderStore((state) => state.mode);
  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);
  const workflowName = useWorkflowBuilderStore((state) => state.workflowName);
  const workflowDescription = useWorkflowBuilderStore(
    (state) => state.workflowDescription,
  );
  const workflowFolder = useWorkflowBuilderStore(
    (state) => state.workflowFolder,
  );
  const workflowVisibility = useWorkflowBuilderStore(
    (state) => state.workflowVisibility,
  );
  const isDirty = useWorkflowBuilderStore((state) => state.isDirty);
  const markSaved = useWorkflowBuilderStore((state) => state.markSaved);
  const markDirty = useWorkflowBuilderStore((state) => state.markDirty);
  const markRunning = useWorkflowBuilderStore((state) => state.markRunning);
  const markError = useWorkflowBuilderStore((state) => state.markError);
  const loadWorkflow = useWorkflowBuilderStore((state) => state.loadWorkflow);
  const resetToNew = useWorkflowBuilderStore((state) => state.resetToNew);
  const selectNode = useWorkflowBuilderStore((state) => state.selectNode);

  const [isSaveAsOpen, setIsSaveAsOpen] = useState(false);
  const [isOpenDialogOpen, setIsOpenDialogOpen] = useState(false);
  const [isOpenConfirmOpen, setIsOpenConfirmOpen] = useState(false);
  const [isManageOpen, setIsManageOpen] = useState(false);
  const [isNewConfirmOpen, setIsNewConfirmOpen] = useState(false);
  // When the user chooses "Save & Open" but has no workflowId, Save As runs first.
  // This flag tells handleSaveAs to open the Open dialog once saving completes.
  const [openAfterSave, setOpenAfterSave] = useState(false);

  const { createWorkflow, updateWorkflow } = useWorkflowMutations();
  const {
    data: pluginResponse,
    error: pluginError,
    isLoading: isPluginsLoading,
  } = useWorkflowStepsQuery();
  const [nodes, setNodes, onNodesChange] = useNodesState(EMPTY_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState(EMPTY_EDGES);
  const plugins = pluginResponse?.plugins ?? EMPTY_PLUGINS;

  const handleNodesChange = useCallback(
    (changes: Parameters<typeof onNodesChange>[0]) => {
      onNodesChange(changes);
      const hasContentChange = changes.some((c) => c.type !== "select");
      if (hasContentChange) markDirty();
    },
    [onNodesChange, markDirty],
  );

  const handleEdgesChange = useCallback(
    (changes: Parameters<typeof onEdgesChange>[0]) => {
      onEdgesChange(changes);
      const hasContentChange = changes.some((c) => c.type !== "select");
      if (hasContentChange) markDirty();
    },
    [onEdgesChange, markDirty],
  );

  const confirmNew = useCallback(() => {
    resetToNew();
    setNodes(EMPTY_NODES);
    setEdges(EMPTY_EDGES);
    setIsNewConfirmOpen(false);
  }, [resetToNew, setNodes, setEdges]);

  const handleNew = useCallback(() => {
    if (isDirty) {
      setIsNewConfirmOpen(true);
    } else {
      confirmNew();
    }
  }, [isDirty, confirmNew]);

  const handleSaveAs = useCallback(
    async (values: {
      name: string;
      description?: string;
      folder?: string;
      visibility: WorkflowVisibility;
    }) => {
      const validation = validateCanvasWorkflow(nodes, edges);
      if (!validation.isValid) {
        markError(`Cannot save: ${validation.issues[0]}`);
        return;
      }
      try {
        const saved = await createWorkflow.mutateAsync({
          name: values.name,
          description: values.description,
          folder: values.folder,
          visibility: values.visibility,
          canvas_nodes: nodes as unknown as Record<string, unknown>[],
          canvas_edges: edges as unknown as Record<string, unknown>[],
        });
        loadWorkflow({
          workflowId: saved.id,
          workflowUuid: saved.uuid ?? null,
          workflowName: saved.name,
          workflowDescription: saved.description ?? "",
          workflowFolder: saved.folder ?? "/",
          workflowVisibility: saved.visibility as WorkflowVisibility,
        });
        setIsSaveAsOpen(false);
        markSaved(`Saved as "${saved.name}"`);
        if (openAfterSave) {
          setOpenAfterSave(false);
          setIsOpenDialogOpen(true);
        }
      } catch {
        markError("Failed to save workflow");
      }
    },
    [nodes, edges, createWorkflow, loadWorkflow, markSaved, markError, openAfterSave],
  );

  const handleSave = useCallback(() => {
    if (!workflowId) {
      setIsSaveAsOpen(true);
      return;
    }
    const validation = validateCanvasWorkflow(nodes, edges);
    if (!validation.isValid) {
      markError(`Cannot save: ${validation.issues[0]}`);
      return;
    }
    updateWorkflow.mutate(
      {
        id: workflowId,
        data: {
          canvas_nodes: nodes as unknown as Record<string, unknown>[],
          canvas_edges: edges as unknown as Record<string, unknown>[],
        },
      },
      {
        onSuccess: () => markSaved(`Saved "${workflowName}"`),
        onError: () => markError("Failed to save workflow"),
      },
    );
  }, [
    workflowId,
    nodes,
    edges,
    updateWorkflow,
    markSaved,
    markError,
    workflowName,
  ]);

  const handleOpen = useCallback(() => {
    if (isDirty) {
      setIsOpenConfirmOpen(true);
    } else {
      setIsOpenDialogOpen(true);
    }
  }, [isDirty]);

  const handleSaveAndOpen = useCallback(async () => {
    setIsOpenConfirmOpen(false);
    if (!workflowId) {
      // No saved ID yet — delegate naming to Save As, then open when done.
      setOpenAfterSave(true);
      setIsSaveAsOpen(true);
      return;
    }
    const validation = validateCanvasWorkflow(nodes, edges);
    if (!validation.isValid) {
      markError(`Cannot save: ${validation.issues[0]}`);
      return;
    }
    try {
      await updateWorkflow.mutateAsync({
        id: workflowId,
        data: {
          canvas_nodes: nodes as unknown as Record<string, unknown>[],
          canvas_edges: edges as unknown as Record<string, unknown>[],
        },
      });
      markSaved(`Saved "${workflowName}"`);
      setIsOpenDialogOpen(true);
    } catch {
      markError("Failed to save workflow");
    }
  }, [workflowId, nodes, edges, updateWorkflow, markSaved, markError, workflowName]);

  const handleDiscardAndOpen = useCallback(() => {
    setIsOpenConfirmOpen(false);
    setIsOpenDialogOpen(true);
  }, []);

  const handleLoadWorkflow = useCallback(
    (summary: WorkflowSummary) => {
      fetch(`/api/proxy/workflows/${summary.id}`, { credentials: "include" })
        .then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return res.json();
        })
        .then((full) => {
          const loadedNodes = (full.canvas_nodes ?? []) as WorkflowCanvasNode[];
          const loadedEdges = (full.canvas_edges ?? []) as WorkflowCanvasEdge[];
          setNodes(loadedNodes);
          setEdges(loadedEdges);
          loadWorkflow({
            workflowId: full.id,
            workflowUuid: full.uuid ?? null,
            workflowName: full.name,
            workflowDescription: full.description ?? "",
            workflowFolder: full.folder ?? "/",
            workflowVisibility: full.visibility as WorkflowVisibility,
          });
        })
        .catch(() => markError("Failed to load workflow"));
    },
    [setNodes, setEdges, loadWorkflow, markError],
  );

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

  const handleEdgeStyleChange = useCallback(
    (edgeId: string, style: EdgeStyle) => {
      setEdges((current) =>
        current.map((e) =>
          e.id !== edgeId ? e : { ...e, data: { ...e.data, edgeStyle: style } },
        ),
      );
      markDirty();
    },
    [setEdges, markDirty],
  );

  const handleNodeConfigChange = useCallback(
    (nodeId: string, config: Record<string, unknown>) => {
      setNodes((current) =>
        current.map((n) =>
          n.id !== nodeId
            ? n
            : { ...n, data: { ...n.data, pluginConfig: config } },
        ),
      );
      markDirty();
    },
    [setNodes, markDirty],
  );

  const handleAddStep = useCallback(
    (step: {
      kind: WorkflowNodeKind;
      title: string;
      description: string;
      artifactType: string;
      mandatoryInputs: string[];
      supportedOutputs: string[];
      outcomes: string[];
    }) => {
      const nextIndex = nodes.length + 1;
      const id = `${step.kind}-${nextIndex}`;
      const stepUuid = crypto.randomUUID();

      setNodes((currentNodes) => [
        ...currentNodes,
        {
          id,
          type: "workflowNode",
          position: { x: 160 + nextIndex * 44, y: 460 },
          data: {
            kind: step.kind,
            stepUuid,
            title: step.title,
            description: step.description,
            artifactType: step.artifactType,
            mandatoryInputs: step.mandatoryInputs,
            supportedOutputs: step.supportedOutputs,
            outcomes: step.outcomes,
            status: "draft",
          },
        },
      ]);
      selectNode(id);
      markDirty();
    },
    [nodes.length, selectNode, setNodes, markDirty],
  );

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <WorkflowSidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <WorkflowTopbar
          onNew={handleNew}
          onOpen={handleOpen}
          onManage={() => setIsManageOpen(true)}
          onRun={handleRun}
          onSave={handleSave}
          onSaveAs={() => setIsSaveAsOpen(true)}
        />
        <main className="flex min-h-0 flex-1">
          <section className="min-w-0 flex-1">
            {mode === "editor" ? (
              <WorkflowCanvas
                edges={edges}
                isPluginsLoading={isPluginsLoading}
                nodes={nodes}
                onEdgesChange={handleEdgesChange}
                onNodesChange={handleNodesChange}
                onAddStep={handleAddStep}
                pluginErrorMessage={pluginError?.message}
                plugins={plugins}
                setEdges={setEdges}
              />
            ) : (
              <WorkflowExecutionsPanel />
            )}
          </section>
          {mode === "editor" ? (
            <WorkflowPropertiesPanel
              edges={edges}
              nodes={nodes}
              onEdgeStyleChange={handleEdgeStyleChange}
              onNodeConfigChange={handleNodeConfigChange}
              plugins={plugins}
            />
          ) : null}
        </main>
        <WorkflowRunControls />
      </div>

      <WorkflowSaveAsDialog
        open={isSaveAsOpen}
        defaultName={workflowName}
        defaultDescription={workflowDescription}
        defaultFolder={workflowFolder}
        defaultVisibility={workflowVisibility}
        isSaving={createWorkflow.isPending}
        onSave={handleSaveAs}
        onClose={() => { setIsSaveAsOpen(false); setOpenAfterSave(false); }}
      />

      <WorkflowOpenDialog
        open={isOpenDialogOpen}
        onOpen={handleLoadWorkflow}
        onClose={() => setIsOpenDialogOpen(false)}
      />

      <WorkflowManageDialog
        open={isManageOpen}
        onClose={() => setIsManageOpen(false)}
      />

      <Dialog
        open={isNewConfirmOpen}
        onOpenChange={(open) => !open && setIsNewConfirmOpen(false)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Discard unsaved changes?</DialogTitle>
            <DialogDescription>
              The current workflow has unsaved changes. Creating a new workflow
              will discard them permanently.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsNewConfirmOpen(false)}
            >
              Keep editing
            </Button>
            <Button variant="destructive" onClick={confirmNew}>
              Discard &amp; create new
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={isOpenConfirmOpen}
        onOpenChange={(open) => !open && setIsOpenConfirmOpen(false)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Unsaved changes</DialogTitle>
            <DialogDescription>
              The current workflow has unsaved changes. Save before opening
              another workflow?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            <Button
              variant="outline"
              onClick={() => setIsOpenConfirmOpen(false)}
            >
              Cancel
            </Button>
            <Button variant="outline" onClick={handleDiscardAndOpen}>
              Discard &amp; open
            </Button>
            <Button onClick={handleSaveAndOpen} disabled={updateWorkflow.isPending}>
              {updateWorkflow.isPending ? "Saving…" : "Save & open"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
