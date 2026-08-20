"use client";

import { useCallback, useMemo } from "react";

import { deriveRouteOutcomes } from "@/components/features/workflow-steps/route-on-attribute/route-config";
import {
  DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG,
  deriveProducesParsed,
} from "@/components/features/workflow-steps/render-jinja-template/template-config";

import type { StaticAttributeDef } from "../types/workflow-persistence";
import {
  BACKGROUND_Z_INDEX,
  DEFAULT_BACKGROUND_CONFIG,
  DEFAULT_LABEL_CONFIG,
  FOREGROUND_Z_INDEX,
  isCanvasDecorationKind,
  reactFlowTypeForKind,
  type PersistedCanvasNode,
  type StepPayload,
} from "../types/workflow-canvas";
import { groupIdFromNodeId, removeRealNodes, ungroupNode } from "../utils/canvas-group-projection";
import type { UseWorkflowCanvasCoreResult } from "./use-workflow-canvas-core";
import type { UseCanvasGroupsResult } from "./use-canvas-groups";

/** Step-node construction, add/delete/duplicate, node config edits, and
 * workflow-level static attributes — everything that changes which nodes
 * exist or how a single node's own config/content is set. */
export function useCanvasSteps(
  core: UseWorkflowCanvasCoreResult,
  groups: UseCanvasGroupsResult,
) {
  const {
    allNodes,
    allEdges,
    groups: allGroups,
    setAllNodes,
    setAllEdges,
    setGroups,
    setStaticAttributes,
    projected,
    selectNode,
    markDirty,
  } = core;
  const { appendToActiveGroup } = groups;

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
    [setAllNodes, markDirty],
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
    [allNodes.length, buildStepNode, setAllNodes, appendToActiveGroup, selectNode, markDirty],
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
    [allNodes.length, buildStepNode, setAllNodes, appendToActiveGroup, selectNode, markDirty],
  );

  const handleDeleteNodes = useCallback(
    (nodeIds: string[]) => {
      const realIds = nodeIds.filter((id) => !groupIdFromNodeId(id));
      const groupIds = nodeIds
        .map((id) => groupIdFromNodeId(id))
        .filter((id): id is string => id !== null);

      let nextAllNodes = allNodes;
      let nextAllEdges = allEdges;
      let nextGroups = allGroups;

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
    [allNodes, allEdges, allGroups, setAllNodes, setAllEdges, setGroups, selectNode, markDirty],
  );

  const handleDeleteEdge = useCallback(
    (edgeId: string) => {
      const proxy = projected.edges.find((e) => e.id === edgeId);
      const realId = proxy?.data?.realEdgeId ?? edgeId;
      setAllEdges((current) => current.filter((e) => e.id !== realId));
      selectNode(null);
      markDirty();
    },
    [projected.edges, setAllEdges, selectNode, markDirty],
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
    [allNodes, setAllNodes, selectNode, markDirty],
  );

  const handleStaticAttributesChange = useCallback(
    (next: StaticAttributeDef[]) => {
      setStaticAttributes(next);
      markDirty();
    },
    [setStaticAttributes, markDirty],
  );

  return useMemo(
    () => ({
      buildStepNode,
      handleNodeConfigChange,
      handleAddStep,
      handleAddStepAtPosition,
      handleDeleteNodes,
      handleDeleteEdge,
      handleDuplicateNode,
      handleStaticAttributesChange,
    }),
    [
      buildStepNode,
      handleNodeConfigChange,
      handleAddStep,
      handleAddStepAtPosition,
      handleDeleteNodes,
      handleDeleteEdge,
      handleDuplicateNode,
      handleStaticAttributesChange,
    ],
  );
}

export type UseCanvasStepsResult = ReturnType<typeof useCanvasSteps>;
