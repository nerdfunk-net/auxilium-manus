"use client";

import { useEdgesState, useNodesState } from "@xyflow/react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { useWorkflowMutations } from "@/hooks/queries/use-workflow-mutations";
import { useWorkflowStepsQuery } from "@/hooks/queries/use-workflow-steps-query";
import { useTriggerRunMutation } from "@/hooks/queries/use-workflow-run-mutations";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { NodeConfigModal } from "./components/node-config-modal";
import { WorkflowCanvas } from "./components/workflow-canvas";
import { WorkflowPropertiesPanel } from "./components/workflow-properties-panel";
import { WorkflowRunControls } from "./components/workflow-run-controls";
import { WorkflowTopbar } from "./components/workflow-topbar";
import { WorkflowManageDialog } from "./dialogs/workflow-manage-dialog";
import { WorkflowOpenDialog } from "./dialogs/workflow-open-dialog";
import { WorkflowSaveAsDialog } from "./dialogs/workflow-save-as-dialog";
import { useWorkflowBuilderStore } from "./hooks/use-workflow-builder-store";
import type { PluginDefinition } from "./types/plugin-registry";
import type { WorkflowSummary, WorkflowVisibility } from "./types/workflow-persistence";
import type {
  EdgeStyle,
  StepPayload,
  WorkflowCanvasEdge,
  WorkflowCanvasNode,
} from "./types/workflow-canvas";
import { validateCanvasWorkflow } from "./utils/workflow-validation";
import { migrateCanvasState } from "./utils/migrate-canvas";
import { alignCanvasNodes, type NodeAlignment } from "./utils/node-alignment";
import { deriveRouteOutcomes } from "@/components/features/workflow-steps/route-on-attribute/route-config";
import {
  DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG,
  deriveProducesParsed,
} from "@/components/features/workflow-steps/render-jinja-template/template-config";
import { DEFAULT_UPDATE_ATTRIBUTE_CONFIG } from "@/components/features/workflow-steps/update-attribute/update-attribute-config";

const EMPTY_PLUGINS: PluginDefinition[] = [];
const EMPTY_NODES: WorkflowCanvasNode[] = [];
const EMPTY_EDGES: WorkflowCanvasEdge[] = [];

export function WorkflowBuilderPage() {
  const router = useRouter();
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
  const runMode = useWorkflowBuilderStore((state) => state.runMode);
  const setActiveRunId = useWorkflowBuilderStore((state) => state.setActiveRunId);
  const loadWorkflow = useWorkflowBuilderStore((state) => state.loadWorkflow);
  const resetToNew = useWorkflowBuilderStore((state) => state.resetToNew);
  const selectNode = useWorkflowBuilderStore((state) => state.selectNode);

  const [isSaveAsOpen, setIsSaveAsOpen] = useState(false);
  const [isOpenDialogOpen, setIsOpenDialogOpen] = useState(false);
  const [isOpenConfirmOpen, setIsOpenConfirmOpen] = useState(false);
  const [isManageOpen, setIsManageOpen] = useState(false);
  const [isNewConfirmOpen, setIsNewConfirmOpen] = useState(false);
  const [isRunConfirmOpen, setIsRunConfirmOpen] = useState(false);
  // When the user chooses "Save & Open" but has no workflowId, Save As runs first.
  // This flag tells handleSaveAs to open the Open dialog once saving completes.
  const [openAfterSave, setOpenAfterSave] = useState(false);
  // When the user chooses "Save & Run" but has no workflowId, Save As runs first.
  const [runAfterSave, setRunAfterSave] = useState(false);

  const { createWorkflow, updateWorkflow } = useWorkflowMutations();
  const triggerRun = useTriggerRunMutation(workflowId);
  const {
    data: pluginResponse,
    error: pluginError,
    isLoading: isPluginsLoading,
  } = useWorkflowStepsQuery();
  const [nodes, setNodes, onNodesChange] = useNodesState(EMPTY_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState(EMPTY_EDGES);
  const plugins = pluginResponse?.plugins ?? EMPTY_PLUGINS;

  // The canvas (nodes/edges) is local React state scoped to this component,
  // while workflowId survives in the Zustand store across route changes
  // (e.g. navigating to /workflows/runs and back). On a fresh mount with a
  // workflow already recorded in the store, re-fetch its canvas so it isn't
  // shown blank. Captured once at mount so it never re-fires for loads that
  // happen via handleLoadWorkflow within the same mount.
  const [mountWorkflowId] = useState(() => workflowId);
  const hasRehydratedCanvasRef = useRef(false);

  useEffect(() => {
    if (hasRehydratedCanvasRef.current) return;
    if (!mountWorkflowId || isPluginsLoading) return;
    hasRehydratedCanvasRef.current = true;
    fetch(`/api/proxy/workflows/${mountWorkflowId}`, { credentials: "include" })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((full) => {
        const loadedNodes = (full.canvas_nodes ?? []) as WorkflowCanvasNode[];
        const loadedEdges = (full.canvas_edges ?? []) as WorkflowCanvasEdge[];
        const { nodes: migratedNodes, edges: migratedEdges, migrated } =
          migrateCanvasState(loadedNodes, loadedEdges, plugins);
        setNodes(migratedNodes);
        setEdges(migratedEdges);
        if (migrated) markDirty();
      })
      .catch(() => markError("Failed to restore workflow canvas"));
  }, [mountWorkflowId, isPluginsLoading, plugins, setNodes, setEdges, markDirty, markError]);

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

  const executeRun = useCallback(
    async (
      overrideWorkflowId?: number,
      options?: { skipValidation?: boolean },
    ) => {
      const targetId = overrideWorkflowId ?? workflowId;
      if (!targetId) {
        markError("Save the workflow before running");
        return;
      }
      if (!options?.skipValidation) {
        const validation = validateCanvasWorkflow(nodes, edges);
        if (!validation.isValid) {
          markError(`Cannot run: ${validation.issues[0]}`);
          return;
        }
      }
      try {
        const run = await triggerRun.mutateAsync({
          device_ids: [],
          trigger_type: "manual",
          run_mode: runMode,
          workflowId: targetId,
        });
        setActiveRunId(run.id);
        markRunning(runMode === "debug" ? "Debug run queued" : "Run queued");
        // Debug mode keeps the canvas visible so the paused-node highlight is
        // visible; normal runs jump straight to the executions list as before.
        if (runMode !== "debug") {
          router.push("/workflows/runs");
        }
      } catch {
        markError("Failed to trigger run");
      }
    },
    [
      workflowId,
      nodes,
      edges,
      triggerRun,
      runMode,
      setActiveRunId,
      markRunning,
      markError,
      router,
    ],
  );

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
        if (runAfterSave) {
          setRunAfterSave(false);
          void executeRun(saved.id);
        }
      } catch {
        markError("Failed to save workflow");
      }
    },
    [nodes, edges, createWorkflow, loadWorkflow, markSaved, markError, openAfterSave, runAfterSave, executeRun],
  );

  const handleOverwrite = useCallback(
    async (
      values: {
        name: string;
        description?: string;
        folder?: string;
        visibility: WorkflowVisibility;
      },
      existingId: number,
    ) => {
      const validation = validateCanvasWorkflow(nodes, edges);
      if (!validation.isValid) {
        markError(`Cannot save: ${validation.issues[0]}`);
        return;
      }
      try {
        const saved = await updateWorkflow.mutateAsync({
          id: existingId,
          data: {
            name: values.name,
            description: values.description,
            folder: values.folder,
            visibility: values.visibility,
            canvas_nodes: nodes as unknown as Record<string, unknown>[],
            canvas_edges: edges as unknown as Record<string, unknown>[],
          },
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
      } catch {
        markError("Failed to overwrite workflow");
      }
    },
    [nodes, edges, updateWorkflow, loadWorkflow, markSaved, markError],
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
          const { nodes: migratedNodes, edges: migratedEdges, migrated } =
            migrateCanvasState(loadedNodes, loadedEdges, plugins);
          setNodes(migratedNodes);
          setEdges(migratedEdges);
          loadWorkflow({
            workflowId: full.id,
            workflowUuid: full.uuid ?? null,
            workflowName: full.name,
            workflowDescription: full.description ?? "",
            workflowFolder: full.folder ?? "/",
            workflowVisibility: full.visibility as WorkflowVisibility,
          });
          if (migrated) {
            markDirty();
          }
        })
        .catch(() => markError("Failed to load workflow"));
    },
    [setNodes, setEdges, loadWorkflow, markError, markDirty, plugins],
  );

  const handleRun = useCallback(() => {
    if (!workflowId || isDirty) {
      setIsRunConfirmOpen(true);
      return;
    }
    void executeRun();
  }, [workflowId, isDirty, executeRun]);

  const handleSaveAndRun = useCallback(async () => {
    setIsRunConfirmOpen(false);
    if (!workflowId) {
      setRunAfterSave(true);
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
      await executeRun();
    } catch {
      markError("Failed to save workflow");
    }
  }, [
    workflowId,
    nodes,
    edges,
    updateWorkflow,
    markSaved,
    markError,
    workflowName,
    executeRun,
  ]);

  const handleRunSavedVersion = useCallback(() => {
    setIsRunConfirmOpen(false);
    void executeRun(workflowId ?? undefined, { skipValidation: true });
  }, [executeRun, workflowId]);

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

  const handleNodeTitleChange = useCallback(
    (nodeId: string, title: string) => {
      setNodes((current) =>
        current.map((n) =>
          n.id !== nodeId ? n : { ...n, data: { ...n.data, title } },
        ),
      );
      markDirty();
    },
    [setNodes, markDirty],
  );

  const handleAlignNodes = useCallback(
    (nodeIds: string[], alignment: NodeAlignment) => {
      setNodes((current) => alignCanvasNodes(current, nodeIds, alignment));
      markDirty();
    },
    [setNodes, markDirty],
  );

  const handleNodeConfigChange = useCallback(
    (nodeId: string, config: Record<string, unknown>) => {
      setNodes((current) =>
        current.map((n) => {
          if (n.id !== nodeId) {
            return n;
          }
          const nextData = { ...n.data, pluginConfig: config };
          if (n.data.kind === "route-on-attribute") {
            nextData.outcomes = deriveRouteOutcomes(config);
          }
          if (n.data.kind === "render-jinja-template") {
            nextData.producesParsed = deriveProducesParsed(config);
          }
          return { ...n, data: nextData };
        }),
      );
      markDirty();
    },
    [setNodes, markDirty],
  );

  const buildStepNode = useCallback(
    (step: StepPayload, id: string, position: { x: number; y: number }): WorkflowCanvasNode => {
      const isRenderJinja = step.kind === "render-jinja-template";
      const isUpdateAttribute = step.kind === "update-attribute";
      const pluginConfig = isRenderJinja
        ? { ...DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG }
        : isUpdateAttribute
          ? { ...DEFAULT_UPDATE_ATTRIBUTE_CONFIG }
          : undefined;
      const producesParsed = isRenderJinja
        ? deriveProducesParsed(DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG)
        : step.producesParsed;

      return {
        id,
        type: "workflowNode",
        position,
        data: {
          kind: step.kind,
          stepUuid: crypto.randomUUID(),
          title: step.title,
          overview: step.overview,
          description: step.description,
          artifactType: step.artifactType,
          requires: step.requires,
          requiresParsed: step.requiresParsed,
          produces: step.produces,
          producesParsed,
          consumes: step.consumes,
          outcomes: step.outcomes,
          ...(pluginConfig ? { pluginConfig } : {}),
        },
      };
    },
    [],
  );

  const handleAddStep = useCallback(
    (step: StepPayload) => {
      const nextIndex = nodes.length + 1;
      const id = `${step.kind}-${nextIndex}`;
      const node = buildStepNode(step, id, { x: 160 + nextIndex * 44, y: 460 });
      setNodes((currentNodes) => [...currentNodes, node]);
      selectNode(id);
      markDirty();
    },
    [nodes.length, buildStepNode, selectNode, setNodes, markDirty],
  );

  const handleAddStepAtPosition = useCallback(
    (step: StepPayload, position: { x: number; y: number }) => {
      const nextIndex = nodes.length + 1;
      const id = `${step.kind}-${nextIndex}`;
      const node = buildStepNode(step, id, position);
      setNodes((currentNodes) => [...currentNodes, node]);
      selectNode(id);
      markDirty();
    },
    [nodes.length, buildStepNode, selectNode, setNodes, markDirty],
  );

  const handleDeleteNodes = useCallback(
    (nodeIds: string[]) => {
      const idSet = new Set(nodeIds);
      setNodes((current) => current.filter((n) => !idSet.has(n.id)));
      setEdges((current) =>
        current.filter((e) => !idSet.has(e.source) && !idSet.has(e.target)),
      );
      selectNode(null);
      markDirty();
    },
    [setNodes, setEdges, selectNode, markDirty],
  );

  const handleDeleteEdge = useCallback(
    (edgeId: string) => {
      setEdges((current) => current.filter((e) => e.id !== edgeId));
      selectNode(null);
      markDirty();
    },
    [setEdges, selectNode, markDirty],
  );

  const handleDuplicateNode = useCallback(
    (nodeId: string) => {
      const source = nodes.find((n) => n.id === nodeId);
      if (!source) return;
      const newId = `${source.data.kind}-${nodes.length + 1}`;
      setNodes((current) => [
        ...current.map((n) => (n.id === nodeId ? { ...n, selected: false } : n)),
        {
          ...source,
          id: newId,
          position: { x: source.position.x + 32, y: source.position.y + 32 },
          selected: true,
          data: { ...source.data, stepUuid: crypto.randomUUID() },
        },
      ]);
      selectNode(newId);
      markDirty();
    },
    [nodes, setNodes, selectNode, markDirty],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
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
          <WorkflowCanvas
            edges={edges}
            nodes={nodes}
            onEdgesChange={handleEdgesChange}
            onNodesChange={handleNodesChange}
            onAddStepAtPosition={handleAddStepAtPosition}
            plugins={plugins}
            setEdges={setEdges}
          />
        </section>
        <WorkflowPropertiesPanel
          edges={edges}
          isPluginsLoading={isPluginsLoading}
          nodes={nodes}
          onAddStep={handleAddStep}
          onAlignNodes={handleAlignNodes}
          onDeleteEdge={handleDeleteEdge}
          onDeleteNodes={handleDeleteNodes}
          onDuplicateNode={handleDuplicateNode}
          onEdgeStyleChange={handleEdgeStyleChange}
          onNodeTitleChange={handleNodeTitleChange}
          pluginErrorMessage={pluginError?.message}
          plugins={plugins}
        />
        <NodeConfigModal
          nodes={nodes}
          edges={edges}
          plugins={plugins}
          onNodeConfigChange={handleNodeConfigChange}
          onNodeTitleChange={handleNodeTitleChange}
          workflowNodes={nodes}
        />
      </main>
      <WorkflowRunControls />

      <WorkflowSaveAsDialog
        open={isSaveAsOpen}
        defaultName={workflowName}
        defaultDescription={workflowDescription}
        defaultFolder={workflowFolder}
        defaultVisibility={workflowVisibility}
        isSaving={createWorkflow.isPending || updateWorkflow.isPending}
        onSave={handleSaveAs}
        onOverwrite={handleOverwrite}
        onClose={() => {
          setIsSaveAsOpen(false);
          setOpenAfterSave(false);
          setRunAfterSave(false);
        }}
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

      <Dialog
        open={isRunConfirmOpen}
        onOpenChange={(open) => !open && setIsRunConfirmOpen(false)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Unsaved changes</DialogTitle>
            <DialogDescription>
              {workflowId
                ? "The current workflow has unsaved changes. Save before running?"
                : "This workflow has not been saved yet. Save before running?"}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            <Button
              variant="outline"
              onClick={() => setIsRunConfirmOpen(false)}
            >
              Cancel
            </Button>
            {workflowId ? (
              <Button variant="outline" onClick={handleRunSavedVersion}>
                Run saved version
              </Button>
            ) : null}
            <Button
              onClick={handleSaveAndRun}
              disabled={updateWorkflow.isPending || createWorkflow.isPending}
            >
              {updateWorkflow.isPending || createWorkflow.isPending
                ? "Saving…"
                : "Save & run"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
