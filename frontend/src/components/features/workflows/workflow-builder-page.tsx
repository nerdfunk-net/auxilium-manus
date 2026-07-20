"use client";

import { addEdge, applyEdgeChanges, applyNodeChanges } from "@xyflow/react";
import type { Connection, EdgeChange, NodeChange } from "@xyflow/react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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

import { CanvasGroupBreadcrumb } from "./components/canvas-group-breadcrumb";
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
import {
  DEFAULT_EDGE_STYLE,
  type CanvasGroup,
  type EdgeStyle,
  type ProjectedCanvasNode,
  type StepPayload,
  type WorkflowCanvasEdge,
  type WorkflowCanvasNode,
} from "./types/workflow-canvas";
import { validateCanvasWorkflow } from "./utils/workflow-validation";
import { validateGroupBoundary } from "./utils/canvas-group-boundary";
import {
  findGroupContainingNode,
  groupIdFromNodeId,
  groupNodeId,
  projectCanvasView,
  removeRealNodes,
  repairOrphanGroups,
  ungroupNode,
} from "./utils/canvas-group-projection";
import { migrateCanvasState } from "./utils/migrate-canvas";
import { alignCanvasNodes, type NodeAlignment } from "./utils/node-alignment";
import { deriveRouteOutcomes } from "@/components/features/workflow-steps/route-on-attribute/route-config";
import {
  DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG,
  deriveProducesParsed,
} from "@/components/features/workflow-steps/render-jinja-template/template-config";
const EMPTY_PLUGINS: PluginDefinition[] = [];
const EMPTY_NODES: WorkflowCanvasNode[] = [];
const EMPTY_EDGES: WorkflowCanvasEdge[] = [];
const EMPTY_GROUPS: CanvasGroup[] = [];

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
  const selectedNodeId = useWorkflowBuilderStore((state) => state.selectedNodeId);
  const activeGroupId = useWorkflowBuilderStore((state) => state.activeGroupId);
  const enterGroup = useWorkflowBuilderStore((state) => state.enterGroup);

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
  const plugins = pluginResponse?.plugins ?? EMPTY_PLUGINS;

  // Canvas state architecture (see doc/FEATURE-GROUPING.md "Canvas state
  // architecture — decision: single authoritative array"). allNodes/allEdges/
  // groups are the only stateful arrays; everything React Flow renders is a
  // pure projection recomputed below and never stored in its own state.
  const [allNodes, setAllNodes] = useState<WorkflowCanvasNode[]>(EMPTY_NODES);
  const [allEdges, setAllEdges] = useState<WorkflowCanvasEdge[]>(EMPTY_EDGES);
  const [groups, setGroups] = useState<CanvasGroup[]>(EMPTY_GROUPS);

  const projected = useMemo(
    () => projectCanvasView(allNodes, allEdges, groups, activeGroupId),
    [allNodes, allEdges, groups, activeGroupId],
  );

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
        const loadedGroups = (full.canvas_groups ?? []) as CanvasGroup[];
        const { nodes: migratedNodes, edges: migratedEdges, migrated } =
          migrateCanvasState(loadedNodes, loadedEdges, plugins);
        const repairedGroups = repairOrphanGroups(migratedNodes, loadedGroups);
        setAllNodes(migratedNodes);
        setAllEdges(migratedEdges);
        setGroups(repairedGroups);
        if (migrated || repairedGroups.length !== loadedGroups.length) markDirty();
      })
      .catch(() => markError("Failed to restore workflow canvas"));
  }, [mountWorkflowId, isPluginsLoading, plugins, markDirty, markError]);

  // Auto-enter a step's group when it is newly focused (e.g. from the
  // executions panel) so the selected node is actually visible on the current
  // view. Gated on selectedNodeId actually *changing* (not just re-evaluated
  // because activeGroupId changed) — otherwise navigating back out via "Go to
  // upper group" while a member step is still selected would immediately
  // re-trigger this effect and drive activeGroupId right back into the group.
  const previousSelectedNodeIdRef = useRef<string | null>(null);
  useEffect(() => {
    const previousSelectedNodeId = previousSelectedNodeIdRef.current;
    previousSelectedNodeIdRef.current = selectedNodeId;
    if (!selectedNodeId || selectedNodeId === previousSelectedNodeId) return;

    const group = findGroupContainingNode(groups, selectedNodeId);
    if (group && activeGroupId !== group.id) {
      enterGroup(group.id);
    }
  }, [selectedNodeId, groups, activeGroupId, enterGroup]);

  const handleNodesChange = useCallback(
    (changes: NodeChange<ProjectedCanvasNode>[]) => {
      const previousVisible = projected.nodes;
      const nextVisible = applyNodeChanges(changes, previousVisible);

      const removedIds = changes
        .filter((change) => change.type === "remove")
        .map((change) => change.id);
      const removedRealIds = removedIds.filter((id) => !groupIdFromNodeId(id));
      const removedGroupIds = removedIds
        .map((id) => groupIdFromNodeId(id))
        .filter((id): id is string => id !== null);

      let nextAllNodes = allNodes;
      let nextAllEdges = allEdges;
      let nextGroups = groups;

      if (removedRealIds.length > 0) {
        const result = removeRealNodes(nextAllNodes, nextAllEdges, nextGroups, removedRealIds);
        nextAllNodes = result.nodes;
        nextAllEdges = result.edges;
        nextGroups = result.groups;
      }
      for (const groupId of removedGroupIds) {
        nextGroups = ungroupNode(nextGroups, groupId);
      }

      const previousById = new Map(previousVisible.map((node) => [node.id, node]));
      for (const node of nextVisible) {
        if (previousById.get(node.id) === node) continue;

        const groupId = groupIdFromNodeId(node.id);
        if (groupId) {
          const currentGroup = nextGroups.find((g) => g.id === groupId);
          if (
            currentGroup &&
            (currentGroup.position.x !== node.position.x ||
              currentGroup.position.y !== node.position.y)
          ) {
            nextGroups = nextGroups.map((g) =>
              g.id === groupId ? { ...g, position: node.position } : g,
            );
          }
          continue;
        }

        nextAllNodes = nextAllNodes.map((n) =>
          n.id === node.id ? (node as WorkflowCanvasNode) : n,
        );
      }

      if (nextAllNodes !== allNodes) setAllNodes(nextAllNodes);
      if (nextAllEdges !== allEdges) setAllEdges(nextAllEdges);
      if (nextGroups !== groups) setGroups(nextGroups);

      const hasContentChange = changes.some((c) => c.type !== "select");
      if (hasContentChange) markDirty();
    },
    [projected.nodes, allNodes, allEdges, groups, markDirty],
  );

  const handleEdgesChange = useCallback(
    (changes: EdgeChange<WorkflowCanvasEdge>[]) => {
      const previousVisible = projected.edges;
      const nextVisible = applyEdgeChanges(changes, previousVisible);

      const removedIds = changes
        .filter((change) => change.type === "remove")
        .map((change) => change.id);

      let nextAllEdges = allEdges;

      for (const id of removedIds) {
        const proxy = previousVisible.find((e) => e.id === id);
        const realId = proxy?.data?.realEdgeId ?? id;
        nextAllEdges = nextAllEdges.filter((e) => e.id !== realId);
      }

      const previousById = new Map(previousVisible.map((edge) => [edge.id, edge]));
      for (const edge of nextVisible) {
        if (previousById.get(edge.id) === edge) continue;

        const realEdgeId = edge.data?.realEdgeId;
        if (realEdgeId) {
          const restData = { ...edge.data };
          delete restData.realEdgeId;
          nextAllEdges = nextAllEdges.map((e) =>
            e.id === realEdgeId ? { ...e, data: { ...e.data, ...restData } } : e,
          );
          continue;
        }

        nextAllEdges = nextAllEdges.map((e) => (e.id === edge.id ? edge : e));
      }

      if (nextAllEdges !== allEdges) setAllEdges(nextAllEdges);

      const hasContentChange = changes.some((c) => c.type !== "select");
      if (hasContentChange) markDirty();
    },
    [projected.edges, allEdges, markDirty],
  );

  const handleConnect = useCallback(
    (connection: Connection) => {
      const sourceGroupId = groupIdFromNodeId(connection.source ?? "");
      const targetGroupId = groupIdFromNodeId(connection.target ?? "");

      const sourceGroup = sourceGroupId ? groups.find((g) => g.id === sourceGroupId) : undefined;
      const targetGroup = targetGroupId ? groups.find((g) => g.id === targetGroupId) : undefined;

      const resolvedConnection: Connection = {
        ...connection,
        source: sourceGroup?.exitNodeId ?? connection.source,
        sourceHandle: sourceGroup ? "success" : connection.sourceHandle,
        target: targetGroup?.entryNodeId ?? connection.target,
        targetHandle: targetGroup ? "input" : connection.targetHandle,
      };

      setAllEdges((current) =>
        addEdge(
          {
            ...resolvedConnection,
            type: "waypoint",
            data: { edgeStyle: DEFAULT_EDGE_STYLE },
          },
          current,
        ),
      );
      markDirty();
    },
    [groups, markDirty],
  );

  const confirmNew = useCallback(() => {
    resetToNew();
    setAllNodes(EMPTY_NODES);
    setAllEdges(EMPTY_EDGES);
    setGroups(EMPTY_GROUPS);
    setIsNewConfirmOpen(false);
  }, [resetToNew]);

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
        const validation = validateCanvasWorkflow(allNodes, allEdges, groups);
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
      allNodes,
      allEdges,
      groups,
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
      const validation = validateCanvasWorkflow(allNodes, allEdges, groups);
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
          canvas_nodes: allNodes as unknown as Record<string, unknown>[],
          canvas_edges: allEdges as unknown as Record<string, unknown>[],
          canvas_groups: groups as unknown as Record<string, unknown>[],
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
    [
      allNodes,
      allEdges,
      groups,
      createWorkflow,
      loadWorkflow,
      markSaved,
      markError,
      openAfterSave,
      runAfterSave,
      executeRun,
    ],
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
      const validation = validateCanvasWorkflow(allNodes, allEdges, groups);
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
            canvas_nodes: allNodes as unknown as Record<string, unknown>[],
            canvas_edges: allEdges as unknown as Record<string, unknown>[],
            canvas_groups: groups as unknown as Record<string, unknown>[],
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
    [allNodes, allEdges, groups, updateWorkflow, loadWorkflow, markSaved, markError],
  );

  const handleSave = useCallback(() => {
    if (!workflowId) {
      setIsSaveAsOpen(true);
      return;
    }
    const validation = validateCanvasWorkflow(allNodes, allEdges, groups);
    if (!validation.isValid) {
      markError(`Cannot save: ${validation.issues[0]}`);
      return;
    }
    updateWorkflow.mutate(
      {
        id: workflowId,
        data: {
          canvas_nodes: allNodes as unknown as Record<string, unknown>[],
          canvas_edges: allEdges as unknown as Record<string, unknown>[],
          canvas_groups: groups as unknown as Record<string, unknown>[],
        },
      },
      {
        onSuccess: () => markSaved(`Saved "${workflowName}"`),
        onError: () => markError("Failed to save workflow"),
      },
    );
  }, [
    workflowId,
    allNodes,
    allEdges,
    groups,
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
    const validation = validateCanvasWorkflow(allNodes, allEdges, groups);
    if (!validation.isValid) {
      markError(`Cannot save: ${validation.issues[0]}`);
      return;
    }
    try {
      await updateWorkflow.mutateAsync({
        id: workflowId,
        data: {
          canvas_nodes: allNodes as unknown as Record<string, unknown>[],
          canvas_edges: allEdges as unknown as Record<string, unknown>[],
          canvas_groups: groups as unknown as Record<string, unknown>[],
        },
      });
      markSaved(`Saved "${workflowName}"`);
      setIsOpenDialogOpen(true);
    } catch {
      markError("Failed to save workflow");
    }
  }, [workflowId, allNodes, allEdges, groups, updateWorkflow, markSaved, markError, workflowName]);

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
          const loadedGroups = (full.canvas_groups ?? []) as CanvasGroup[];
          const { nodes: migratedNodes, edges: migratedEdges, migrated } =
            migrateCanvasState(loadedNodes, loadedEdges, plugins);
          const repairedGroups = repairOrphanGroups(migratedNodes, loadedGroups);
          setAllNodes(migratedNodes);
          setAllEdges(migratedEdges);
          setGroups(repairedGroups);
          loadWorkflow({
            workflowId: full.id,
            workflowUuid: full.uuid ?? null,
            workflowName: full.name,
            workflowDescription: full.description ?? "",
            workflowFolder: full.folder ?? "/",
            workflowVisibility: full.visibility as WorkflowVisibility,
          });
          if (migrated || repairedGroups.length !== loadedGroups.length) {
            markDirty();
          }
        })
        .catch(() => markError("Failed to load workflow"));
    },
    [loadWorkflow, markError, markDirty, plugins],
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
    const validation = validateCanvasWorkflow(allNodes, allEdges, groups);
    if (!validation.isValid) {
      markError(`Cannot save: ${validation.issues[0]}`);
      return;
    }
    try {
      await updateWorkflow.mutateAsync({
        id: workflowId,
        data: {
          canvas_nodes: allNodes as unknown as Record<string, unknown>[],
          canvas_edges: allEdges as unknown as Record<string, unknown>[],
          canvas_groups: groups as unknown as Record<string, unknown>[],
        },
      });
      markSaved(`Saved "${workflowName}"`);
      await executeRun();
    } catch {
      markError("Failed to save workflow");
    }
  }, [
    workflowId,
    allNodes,
    allEdges,
    groups,
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
      const proxy = projected.edges.find((e) => e.id === edgeId);
      const realId = proxy?.data?.realEdgeId ?? edgeId;
      setAllEdges((current) =>
        current.map((e) =>
          e.id !== realId ? e : { ...e, data: { ...e.data, edgeStyle: style } },
        ),
      );
      markDirty();
    },
    [projected.edges, markDirty],
  );

  const handleNodeTitleChange = useCallback(
    (nodeId: string, title: string) => {
      setAllNodes((current) =>
        current.map((n) =>
          n.id !== nodeId ? n : { ...n, data: { ...n.data, title } },
        ),
      );
      markDirty();
    },
    [markDirty],
  );

  const handleAlignNodes = useCallback(
    (nodeIds: string[], alignment: NodeAlignment) => {
      const aligned = alignCanvasNodes(projected.nodes, nodeIds, alignment);
      const positionById = new Map(aligned.map((n) => [n.id, n.position]));

      setAllNodes((current) =>
        current.map((n) =>
          positionById.has(n.id) ? { ...n, position: positionById.get(n.id)! } : n,
        ),
      );
      setGroups((current) =>
        current.map((g) => {
          const syntheticId = groupNodeId(g.id);
          return positionById.has(syntheticId)
            ? { ...g, position: positionById.get(syntheticId)! }
            : g;
        }),
      );
      markDirty();
    },
    [projected.nodes, markDirty],
  );

  const handleNodeConfigChange = useCallback(
    (nodeId: string, config: Record<string, unknown>) => {
      setAllNodes((current) =>
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
    [markDirty],
  );

  const buildStepNode = useCallback(
    (step: StepPayload, id: string, position: { x: number; y: number }): WorkflowCanvasNode => {
      const isRenderJinja = step.kind === "render-jinja-template";
      const isUpdateAttribute = step.kind === "update-attribute";
      const pluginConfig = isRenderJinja
        ? { ...DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG }
        : isUpdateAttribute
          ? { attributes: [] }
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

  const appendToActiveGroup = useCallback(
    (nodeId: string) => {
      if (!activeGroupId) return;
      setGroups((current) =>
        current.map((g) =>
          g.id === activeGroupId ? { ...g, nodeIds: [...g.nodeIds, nodeId] } : g,
        ),
      );
    },
    [activeGroupId],
  );

  const handleAddStep = useCallback(
    (step: StepPayload) => {
      const nextIndex = allNodes.length + 1;
      const id = `${step.kind}-${nextIndex}`;
      const node = buildStepNode(step, id, { x: 160 + nextIndex * 44, y: 460 });
      setAllNodes((currentNodes) => [...currentNodes, node]);
      appendToActiveGroup(id);
      selectNode(id);
      markDirty();
    },
    [allNodes.length, buildStepNode, appendToActiveGroup, selectNode, markDirty],
  );

  const handleAddStepAtPosition = useCallback(
    (step: StepPayload, position: { x: number; y: number }) => {
      const nextIndex = allNodes.length + 1;
      const id = `${step.kind}-${nextIndex}`;
      const node = buildStepNode(step, id, position);
      setAllNodes((currentNodes) => [...currentNodes, node]);
      appendToActiveGroup(id);
      selectNode(id);
      markDirty();
    },
    [allNodes.length, buildStepNode, appendToActiveGroup, selectNode, markDirty],
  );

  const handleDeleteNodes = useCallback(
    (nodeIds: string[]) => {
      const realIds = nodeIds.filter((id) => !groupIdFromNodeId(id));
      const groupIds = nodeIds
        .map((id) => groupIdFromNodeId(id))
        .filter((id): id is string => id !== null);

      let nextAllNodes = allNodes;
      let nextAllEdges = allEdges;
      let nextGroups = groups;

      if (realIds.length > 0) {
        const result = removeRealNodes(nextAllNodes, nextAllEdges, nextGroups, realIds);
        nextAllNodes = result.nodes;
        nextAllEdges = result.edges;
        nextGroups = result.groups;
      }
      for (const groupId of groupIds) {
        nextGroups = ungroupNode(nextGroups, groupId);
      }

      setAllNodes(nextAllNodes);
      setAllEdges(nextAllEdges);
      setGroups(nextGroups);
      selectNode(null);
      markDirty();
    },
    [allNodes, allEdges, groups, selectNode, markDirty],
  );

  const handleDeleteEdge = useCallback(
    (edgeId: string) => {
      const proxy = projected.edges.find((e) => e.id === edgeId);
      const realId = proxy?.data?.realEdgeId ?? edgeId;
      setAllEdges((current) => current.filter((e) => e.id !== realId));
      selectNode(null);
      markDirty();
    },
    [projected.edges, selectNode, markDirty],
  );

  const handleDuplicateNode = useCallback(
    (nodeId: string) => {
      const source = allNodes.find((n) => n.id === nodeId);
      if (!source) return;
      const newId = `${source.data.kind}-${allNodes.length + 1}`;
      setAllNodes((current) => [
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
    [allNodes, selectNode, markDirty],
  );

  const handleGroupSelectedSteps = useCallback(
    (nodeIds: string[]) => {
      const result = validateGroupBoundary(nodeIds, allEdges, groups);
      if (!result.valid || !result.entryNodeId || !result.exitNodeId) {
        markError(result.reason ?? "Cannot group the selected steps.");
        return;
      }

      const memberNodes = allNodes.filter((n) => nodeIds.includes(n.id));
      const avgX =
        memberNodes.reduce((sum, n) => sum + n.position.x, 0) / memberNodes.length;
      const avgY =
        memberNodes.reduce((sum, n) => sum + n.position.y, 0) / memberNodes.length;

      const newGroup: CanvasGroup = {
        id: `group-${crypto.randomUUID()}`,
        title: "New group",
        nodeIds,
        entryNodeId: result.entryNodeId,
        exitNodeId: result.exitNodeId,
        position: { x: avgX, y: avgY },
        parentGroupId: null,
      };
      setGroups((current) => [...current, newGroup]);
      selectNode(groupNodeId(newGroup.id));
      markDirty();
    },
    [allNodes, allEdges, groups, selectNode, markDirty, markError],
  );

  const handleRenameGroup = useCallback(
    (groupId: string, title: string) => {
      setGroups((current) => current.map((g) => (g.id === groupId ? { ...g, title } : g)));
      markDirty();
    },
    [markDirty],
  );

  const handleUngroupGroup = useCallback(
    (groupId: string) => {
      setGroups((current) => ungroupNode(current, groupId));
      selectNode(null);
      markDirty();
    },
    [selectNode, markDirty],
  );

  const handleOpenGroup = useCallback(
    (groupId: string) => {
      enterGroup(groupId);
    },
    [enterGroup],
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
        <section className="flex min-w-0 flex-1 flex-col">
          <CanvasGroupBreadcrumb groups={groups} />
          <div className="min-h-0 flex-1">
            <WorkflowCanvas
              edges={projected.edges}
              nodes={projected.nodes}
              onEdgesChange={handleEdgesChange}
              onNodesChange={handleNodesChange}
              onConnect={handleConnect}
              onAddStepAtPosition={handleAddStepAtPosition}
              plugins={plugins}
            />
          </div>
        </section>
        <WorkflowPropertiesPanel
          edges={projected.edges}
          isPluginsLoading={isPluginsLoading}
          nodes={projected.nodes}
          onAddStep={handleAddStep}
          onAlignNodes={handleAlignNodes}
          onDeleteEdge={handleDeleteEdge}
          onDeleteNodes={handleDeleteNodes}
          onDuplicateNode={handleDuplicateNode}
          onEdgeStyleChange={handleEdgeStyleChange}
          onGroupSelectedSteps={handleGroupSelectedSteps}
          onNodeTitleChange={handleNodeTitleChange}
          onOpenGroup={handleOpenGroup}
          onRenameGroup={handleRenameGroup}
          onUngroupGroup={handleUngroupGroup}
          pluginErrorMessage={pluginError?.message}
          plugins={plugins}
          isInsideGroup={activeGroupId !== null}
        />
        <NodeConfigModal
          nodes={allNodes}
          edges={allEdges}
          plugins={plugins}
          onNodeConfigChange={handleNodeConfigChange}
          onNodeTitleChange={handleNodeTitleChange}
          workflowNodes={allNodes}
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
