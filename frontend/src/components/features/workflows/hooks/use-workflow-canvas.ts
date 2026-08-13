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

import { deriveRouteOutcomes } from "@/components/features/workflow-steps/route-on-attribute/route-config";
import {
  DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG,
  deriveProducesParsed,
} from "@/components/features/workflow-steps/render-jinja-template/template-config";

import {
  EMPTY_WORKFLOW_EDGES as EMPTY_EDGES,
  EMPTY_WORKFLOW_NODES as EMPTY_NODES,
} from "../constants/empty-canvas";
import type { StaticAttributeDef } from "../types/workflow-persistence";
import {
  BACKGROUND_Z_INDEX,
  DEFAULT_BACKGROUND_CONFIG,
  DEFAULT_EDGE_STYLE,
  DEFAULT_LABEL_CONFIG,
  FOREGROUND_Z_INDEX,
  isCanvasDecorationKind,
  reactFlowTypeForKind,
  type CanvasGroup,
  type EdgeStyle,
  type HandleSide,
  type PersistedCanvasNode,
  type ProjectedCanvasNode,
  type StepPayload,
  type WorkflowCanvasEdge,
  type WorkflowEdgeData,
} from "../types/workflow-canvas";
import { validateGroupBoundary } from "../utils/canvas-group-boundary";
import { resolveContainment } from "../utils/canvas-containment";
import {
  findGroupContainingNode,
  groupIdFromNodeId,
  groupNodeId,
  projectCanvasView,
  removeRealNodes,
  ungroupNode,
} from "../utils/canvas-group-projection";
import { alignCanvasNodes, type NodeAlignment } from "../utils/node-alignment";
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

export function useWorkflowCanvas() {
  const markDirty = useWorkflowBuilderStore((state) => state.markDirty);
  const markError = useWorkflowBuilderStore((state) => state.markError);
  const selectNode = useWorkflowBuilderStore((state) => state.selectNode);
  const selectedNodeId = useWorkflowBuilderStore((state) => state.selectedNodeId);
  const activeGroupId = useWorkflowBuilderStore((state) => state.activeGroupId);
  const enterGroup = useWorkflowBuilderStore((state) => state.enterGroup);
  const setCanvasDraft = useWorkflowBuilderStore((state) => state.setCanvasDraft);
  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);

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

  const updateEdgeData = useCallback(
    (edgeId: string, patch: Partial<WorkflowEdgeData>) => {
      const proxy = projected.edges.find((e) => e.id === edgeId);
      const realId = proxy?.data?.realEdgeId ?? edgeId;
      setAllEdges((current) =>
        current.map((e) => (e.id !== realId ? e : { ...e, data: { ...e.data, ...patch } })),
      );
      markDirty();
    },
    [projected.edges, markDirty],
  );

  const handleEdgeLabelChange = useCallback(
    (edgeId: string, label: string) => updateEdgeData(edgeId, { label }),
    [updateEdgeData],
  );

  const handleEdgeStartLabelChange = useCallback(
    (edgeId: string, startLabel: string) => updateEdgeData(edgeId, { startLabel }),
    [updateEdgeData],
  );

  const handleEdgeEndLabelChange = useCallback(
    (edgeId: string, endLabel: string) => updateEdgeData(edgeId, { endLabel }),
    [updateEdgeData],
  );

  const handleEdgeLabelBoldChange = useCallback(
    (edgeId: string, labelBold: boolean) => updateEdgeData(edgeId, { labelBold }),
    [updateEdgeData],
  );

  const handleEdgeLabelFontSizeChange = useCallback(
    (edgeId: string, labelFontSize: number) => updateEdgeData(edgeId, { labelFontSize }),
    [updateEdgeData],
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

  const handleIncomeHandleSideChange = useCallback(
    (nodeId: string, side: HandleSide) => {
      setAllNodes((current) =>
        current.map((n) => {
          if (n.id !== nodeId) return n;
          const previousIncomeSide = n.data.incomeHandleSide ?? "left";
          const outcomeSide = n.data.outcomeHandleSide ?? "right";
          return {
            ...n,
            data: {
              ...n.data,
              incomeHandleSide: side,
              outcomeHandleSide: outcomeSide === side ? previousIncomeSide : outcomeSide,
            },
          };
        }),
      );
      markDirty();
    },
    [markDirty],
  );

  const handleOutcomeHandleSideChange = useCallback(
    (nodeId: string, side: HandleSide) => {
      setAllNodes((current) =>
        current.map((n) =>
          n.id !== nodeId ? n : { ...n, data: { ...n.data, outcomeHandleSide: side } },
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
          if (isCanvasDecorationKind(n.data.kind)) {
            const width =
              typeof config.width === "number" ? config.width : (n.width ?? 0);
            const height =
              typeof config.height === "number" ? config.height : (n.height ?? 0);
            return {
              ...n,
              width,
              height,
              zIndex:
                n.data.kind === "background"
                  ? BACKGROUND_Z_INDEX
                  : FOREGROUND_Z_INDEX,
              style: { ...n.style, width, height },
              data: nextData,
            };
          }
          return { ...n, data: nextData };
        }),
      );
      markDirty();
    },
    [markDirty],
  );

  const buildStepNode = useCallback(
    (step: StepPayload, id: string, position: { x: number; y: number }): PersistedCanvasNode => {
      const isRenderJinja = step.kind === "render-jinja-template";
      const isUpdateAttribute = step.kind === "update-attribute";
      const isLabel = step.kind === "label";
      const isBackground = step.kind === "background";

      let pluginConfig: Record<string, unknown> | undefined;
      if (isRenderJinja) {
        pluginConfig = { ...DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG };
      } else if (isUpdateAttribute) {
        pluginConfig = { attributes: [] };
      } else if (isLabel) {
        pluginConfig = { ...DEFAULT_LABEL_CONFIG };
      } else if (isBackground) {
        pluginConfig = { ...DEFAULT_BACKGROUND_CONFIG };
      }

      const producesParsed = isRenderJinja
        ? deriveProducesParsed(DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG)
        : step.producesParsed;

      const nodeType = reactFlowTypeForKind(step.kind);
      const width =
        typeof pluginConfig?.width === "number" ? pluginConfig.width : undefined;
      const height =
        typeof pluginConfig?.height === "number" ? pluginConfig.height : undefined;

      return {
        id,
        type: nodeType,
        position,
        zIndex: isBackground ? BACKGROUND_Z_INDEX : FOREGROUND_Z_INDEX,
        ...(width != null && height != null
          ? { width, height, style: { width, height } }
          : {}),
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
      } as PersistedCanvasNode;
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
      // Insertion order doesn't need to special-case backgrounds anymore:
      // sortNodesForContainment (applied downstream at projection/layering time)
      // guarantees backgrounds paint behind and precede their children.
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
      // Insertion order doesn't need to special-case backgrounds anymore:
      // sortNodesForContainment (applied downstream at projection/layering time)
      // guarantees backgrounds paint behind and precede their children.
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
      const result = validateGroupBoundary(nodeIds, allEdges, groups, allNodes);
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

  const handleStaticAttributesChange = useCallback(
    (next: StaticAttributeDef[]) => {
      setStaticAttributes(next);
      markDirty();
    },
    [markDirty],
  );

  return useMemo(
    () => ({
      allNodes,
      allEdges,
      groups,
      staticAttributes,
      projected,
      initialCanvasDraft,
      mountWorkflowId,
      activeGroupId,
      applyLoadedCanvas,
      clearCanvas,
      handleViewportChange,
      handleNodesChange,
      handleEdgesChange,
      handleConnect,
      handleEdgeStyleChange,
      handleEdgeLabelChange,
      handleEdgeStartLabelChange,
      handleEdgeEndLabelChange,
      handleEdgeLabelBoldChange,
      handleEdgeLabelFontSizeChange,
      handleNodeTitleChange,
      handleIncomeHandleSideChange,
      handleOutcomeHandleSideChange,
      handleAlignNodes,
      handleNodeConfigChange,
      handleAddStep,
      handleAddStepAtPosition,
      handleDeleteNodes,
      handleDeleteEdge,
      handleDuplicateNode,
      handleGroupSelectedSteps,
      handleRenameGroup,
      handleUngroupGroup,
      handleOpenGroup,
      handleStaticAttributesChange,
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
      applyLoadedCanvas,
      clearCanvas,
      handleViewportChange,
      handleNodesChange,
      handleEdgesChange,
      handleConnect,
      handleEdgeStyleChange,
      handleEdgeLabelChange,
      handleEdgeStartLabelChange,
      handleEdgeEndLabelChange,
      handleEdgeLabelBoldChange,
      handleEdgeLabelFontSizeChange,
      handleNodeTitleChange,
      handleIncomeHandleSideChange,
      handleOutcomeHandleSideChange,
      handleAlignNodes,
      handleNodeConfigChange,
      handleAddStep,
      handleAddStepAtPosition,
      handleDeleteNodes,
      handleDeleteEdge,
      handleDuplicateNode,
      handleGroupSelectedSteps,
      handleRenameGroup,
      handleUngroupGroup,
      handleOpenGroup,
      handleStaticAttributesChange,
    ],
  );
}

export type UseWorkflowCanvasResult = ReturnType<typeof useWorkflowCanvas>;
