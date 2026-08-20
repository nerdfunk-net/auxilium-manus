"use client";

import { addEdge, applyEdgeChanges, applyNodeChanges } from "@xyflow/react";
import type {
  Connection,
  EdgeChange,
  NodeChange,
  NodePositionChange,
  Viewport,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useToast } from "@/hooks/use-toast";

import {
  EMPTY_WORKFLOW_EDGES as EMPTY_EDGES,
  EMPTY_WORKFLOW_NODES as EMPTY_NODES,
} from "../constants/empty-canvas";
import type { StaticAttributeDef } from "../types/workflow-persistence";
import {
  BACKGROUND_Z_INDEX,
  DEFAULT_EDGE_STYLE,
  FOREGROUND_Z_INDEX,
  type CanvasGroup,
  type PersistedCanvasNode,
  type ProjectedCanvasNode,
  type WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import { resolveContainment } from "../utils/canvas-containment";
import {
  findGroupContainingNode,
  groupIdFromNodeId,
  projectCanvasView,
  removeRealNodes,
  ungroupNode,
} from "../utils/canvas-group-projection";
import { useWorkflowBuilderStore } from "./use-workflow-builder-store";

const EMPTY_GROUPS: CanvasGroup[] = [];
const EMPTY_STATIC_ATTRIBUTES: StaticAttributeDef[] = [];

export interface LoadedCanvasState {
  nodes: PersistedCanvasNode[];
  edges: WorkflowCanvasEdge[];
  groups: CanvasGroup[];
  staticAttributes: StaticAttributeDef[];
  migrated?: boolean;
}

/**
 * Owns the single authoritative canvas state (allNodes/allEdges/groups/
 * staticAttributes — see doc/FEATURE-GROUPING.md "Canvas state architecture")
 * plus the handlers that mutate it directly from React Flow callbacks.
 * use-canvas-layout.ts, use-canvas-groups.ts, and use-canvas-steps.ts each
 * take this hook's return value as their `core` argument rather than
 * re-deriving state, so nodes/edges/groups stay a single source of truth.
 */
export function useWorkflowCanvasCore() {
  const markDirty = useWorkflowBuilderStore((state) => state.markDirty);
  const markError = useWorkflowBuilderStore((state) => state.markError);
  const selectNode = useWorkflowBuilderStore((state) => state.selectNode);
  const selectedNodeId = useWorkflowBuilderStore((state) => state.selectedNodeId);
  const activeGroupId = useWorkflowBuilderStore((state) => state.activeGroupId);
  const enterGroup = useWorkflowBuilderStore((state) => state.enterGroup);
  const setCanvasDraft = useWorkflowBuilderStore((state) => state.setCanvasDraft);
  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);
  const requestFitView = useWorkflowBuilderStore((state) => state.requestFitView);
  const { toast } = useToast();

  // The canvas (nodes/edges) is local React state scoped to this component,
  // while workflowId survives in the Zustand store across route changes
  // (e.g. navigating to /workflows/runs and back). Captured once at mount so
  // it never re-fires for loads that happen via handleLoadWorkflow within the
  // same mount.
  const [mountWorkflowId] = useState(() => workflowId);
  // On unmount (route navigation away from the editor) the current canvas is
  // snapshotted into the Zustand singleton (see setCanvasDraft below), which
  // — unlike this component's own useState — survives the unmount. If this
  // mount's initial workflowId matches that draft, we are returning to the
  // same in-progress edit and must restore it verbatim rather than re-fetch
  // the last *saved* version from the backend, which would silently discard
  // unsaved edits (including plain node moves).
  const [initialCanvasDraft] = useState(() => {
    const draft = useWorkflowBuilderStore.getState().canvasDraft;
    return draft && draft.workflowId === mountWorkflowId ? draft : null;
  });

  // Canvas state architecture (see doc/FEATURE-GROUPING.md "Canvas state
  // architecture — decision: single authoritative array"). allNodes/allEdges/
  // groups are the only stateful arrays; everything React Flow renders is a
  // pure projection recomputed below and never stored in its own state.
  const [allNodes, setAllNodes] = useState<PersistedCanvasNode[]>(
    () => initialCanvasDraft?.nodes ?? EMPTY_NODES,
  );
  const [allEdges, setAllEdges] = useState<WorkflowCanvasEdge[]>(
    () => initialCanvasDraft?.edges ?? EMPTY_EDGES,
  );
  const [groups, setGroups] = useState<CanvasGroup[]>(
    () => initialCanvasDraft?.groups ?? EMPTY_GROUPS,
  );
  // Workflow-level, not canvas-scoped, but persisted the same way (rides
  // along with the canvas arrays in every save call) — see doc/WORKFLOW-STEPS.md
  // "Static attributes".
  const [staticAttributes, setStaticAttributes] = useState<StaticAttributeDef[]>(
    () => initialCanvasDraft?.staticAttributes ?? EMPTY_STATIC_ATTRIBUTES,
  );

  const projected = useMemo(
    () => projectCanvasView(allNodes, allEdges, groups, activeGroupId),
    [allNodes, allEdges, groups, activeGroupId],
  );

  // Keep a ref mirror of the canvas so the unmount cleanup below (which must
  // run only once, on unmount) can read the latest values without making the
  // effect re-run on every keystroke/drag.
  const canvasSnapshotRef = useRef({ allNodes, allEdges, groups, staticAttributes });
  useEffect(() => {
    canvasSnapshotRef.current = { allNodes, allEdges, groups, staticAttributes };
  }, [allNodes, allEdges, groups, staticAttributes]);

  // Pan/zoom, restored verbatim alongside the canvas draft so returning from
  // another route doesn't re-fit (and visually "zoom in on") the canvas.
  // Updated directly by the WorkflowCanvas onMoveEnd callback (once per
  // gesture, not per frame) rather than through state, since it never needs
  // to trigger a re-render of this component.
  const viewportRef = useRef<Viewport | null>(initialCanvasDraft?.viewport ?? null);
  const handleViewportChange = useCallback((viewport: Viewport) => {
    viewportRef.current = viewport;
  }, []);

  useEffect(() => {
    return () => {
      const currentWorkflowId = useWorkflowBuilderStore.getState().workflowId;
      const snapshot = canvasSnapshotRef.current;
      setCanvasDraft({
        workflowId: currentWorkflowId,
        nodes: snapshot.allNodes,
        edges: snapshot.allEdges,
        groups: snapshot.groups,
        staticAttributes: snapshot.staticAttributes,
        viewport: viewportRef.current,
      });
    };
  }, [setCanvasDraft]);

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

  const applyLoadedCanvas = useCallback((loaded: LoadedCanvasState) => {
    setAllNodes(loaded.nodes);
    setAllEdges(loaded.edges);
    setGroups(loaded.groups);
    setStaticAttributes(loaded.staticAttributes);
  }, []);

  const clearCanvas = useCallback(() => {
    setAllNodes(EMPTY_NODES);
    setAllEdges(EMPTY_EDGES);
    setGroups(EMPTY_GROUPS);
    setStaticAttributes(EMPTY_STATIC_ATTRIBUTES);
  }, []);

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

      // Only a drag-end ("dragging: false") position change should trigger a
      // background attach/detach re-evaluation — not every intermediate
      // mousemove, and not unrelated changes (resize, selection).
      const dragEndNodeIds = new Set(
        changes
          .filter(
            (change): change is NodePositionChange =>
              change.type === "position" && change.dragging === false,
          )
          .map((change) => change.id),
      );

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

        nextAllNodes = nextAllNodes.map((n) => {
          if (n.id !== node.id) return n;
          const updated = node as PersistedCanvasNode;
          if (updated.type === "backgroundNode") {
            const width = Math.round(updated.width ?? updated.measured?.width ?? 0);
            const height = Math.round(
              updated.height ?? updated.measured?.height ?? 0,
            );
            return {
              ...updated,
              zIndex: BACKGROUND_Z_INDEX,
              ...(width > 0 && height > 0
                ? {
                    width,
                    height,
                    data: {
                      ...updated.data,
                      pluginConfig: {
                        ...updated.data.pluginConfig,
                        width,
                        height,
                      },
                    },
                  }
                : {}),
            };
          }
          if (updated.type === "labelNode" || updated.type === "workflowNode") {
            let next = updated;

            if (next.type === "labelNode") {
              const width = Math.round(next.width ?? next.measured?.width ?? 0);
              const height = Math.round(next.height ?? next.measured?.height ?? 0);
              if (width > 0 && height > 0) {
                next = {
                  ...next,
                  width,
                  height,
                  data: {
                    ...next.data,
                    pluginConfig: { ...next.data.pluginConfig, width, height },
                  },
                };
              }
            }

            if (dragEndNodeIds.has(next.id)) {
              const { parentId, position } = resolveContainment(next, nextAllNodes);
              next = { ...next, parentId, position };
            }

            return { ...next, zIndex: next.parentId ? undefined : FOREGROUND_Z_INDEX };
          }
          return updated;
        });
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

  return useMemo(
    () => ({
      allNodes,
      setAllNodes,
      allEdges,
      setAllEdges,
      groups,
      setGroups,
      staticAttributes,
      setStaticAttributes,
      projected,
      initialCanvasDraft,
      mountWorkflowId,
      activeGroupId,
      markDirty,
      markError,
      selectNode,
      enterGroup,
      requestFitView,
      toast,
      applyLoadedCanvas,
      clearCanvas,
      handleViewportChange,
      handleNodesChange,
      handleEdgesChange,
      handleConnect,
    }),
    [
      allNodes,
      allEdges,
      groups,
      staticAttributes,
      projected,
      initialCanvasDraft,
      mountWorkflowId,
      activeGroupId,
      markDirty,
      markError,
      selectNode,
      enterGroup,
      requestFitView,
      toast,
      applyLoadedCanvas,
      clearCanvas,
      handleViewportChange,
      handleNodesChange,
      handleEdgesChange,
      handleConnect,
    ],
  );
}

export type UseWorkflowCanvasCoreResult = ReturnType<typeof useWorkflowCanvasCore>;
