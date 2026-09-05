import type { Capability } from "@/lib/capability-types";

import { DEFAULT_GET_FROM_USER_CONFIG } from "@/components/features/workflow-steps/get-from-user/config";
import type { PluginDefinition } from "../types/plugin-registry";
import {
  BACKGROUND_Z_INDEX,
  DEFAULT_BACKGROUND_CONFIG,
  DEFAULT_LABEL_CONFIG,
  FOREGROUND_Z_INDEX,
  reactFlowTypeForKind,
  type PersistedCanvasNode,
  type WorkflowCanvasEdge,
} from "../types/workflow-canvas";

type LegacyNodeData = PersistedCanvasNode["data"] & {
  mandatoryInputs?: { name: string; dataType?: string }[];
  portOrientation?: "horizontal" | "vertical";
};

function applyPluginDefaults(
  data: PersistedCanvasNode["data"],
  plugin: PluginDefinition,
): { data: PersistedCanvasNode["data"]; changed: boolean } {
  const next = { ...data };
  let changed = false;

  if (!next.requires?.length && plugin.requires.length > 0) {
    next.requires = plugin.requires as Capability[];
    changed = true;
  }
  if (!next.requiresParsed?.length && plugin.requires_parsed.length > 0) {
    next.requiresParsed = plugin.requires_parsed;
    changed = true;
  }
  if (!next.produces?.length && plugin.produces.length > 0) {
    next.produces = plugin.produces as Capability[];
    changed = true;
  }
  if (!next.producesParsed?.length && plugin.produces_parsed.length > 0) {
    next.producesParsed = plugin.produces_parsed;
    changed = true;
  }
  if (!next.consumes?.length && plugin.consumes.length > 0) {
    next.consumes = plugin.consumes as Capability[];
    changed = true;
  }
  if (!next.outcomes?.length && plugin.outcomes.length > 0) {
    next.outcomes = plugin.outcomes.map((outcome) => ({ name: outcome.name }));
    changed = true;
  }
  if (!next.artifactType && plugin.artifact_type) {
    next.artifactType = plugin.artifact_type;
    changed = true;
  }
  if (!next.overview) {
    next.overview = plugin.overview;
    changed = true;
  }

  return { data: next, changed };
}

/**
 * Upgrade persisted canvas JSON from the legacy IO-handle model to capability fields.
 */
export function migrateCanvasState(
  nodes: PersistedCanvasNode[],
  edges: WorkflowCanvasEdge[],
  plugins: PluginDefinition[],
): {
  nodes: PersistedCanvasNode[];
  edges: WorkflowCanvasEdge[];
  migrated: boolean;
} {
  const pluginById = new Map(plugins.map((plugin) => [plugin.id, plugin]));
  let migrated = false;

  const migratedNodes = nodes.map((node) => {
    const legacyData = node.data as LegacyNodeData;
    let data = { ...legacyData };
    let nodeChanged = false;

    if ("mandatoryInputs" in legacyData) {
      const rest = { ...legacyData };
      delete rest.mandatoryInputs;
      data = rest;
      nodeChanged = true;
    }

    if ("portOrientation" in legacyData) {
      const rest = { ...data } as LegacyNodeData;
      const legacyOrientation = rest.portOrientation;
      delete rest.portOrientation;
      if (!rest.incomeHandleSide && !rest.outcomeHandleSide) {
        if (legacyOrientation === "vertical") {
          rest.incomeHandleSide = "top";
          rest.outcomeHandleSide = "bottom";
        } else {
          rest.incomeHandleSide = "left";
          rest.outcomeHandleSide = "right";
        }
      }
      data = rest;
      nodeChanged = true;
    }

    const plugin = pluginById.get(data.kind);
    if (plugin) {
      const result = applyPluginDefaults(data, plugin);
      data = result.data;
      nodeChanged = nodeChanged || result.changed;
    }

    const expectedType = reactFlowTypeForKind(data.kind);
    let nextNode: PersistedCanvasNode = nodeChanged
      ? ({ ...node, data } as PersistedCanvasNode)
      : node;

    if (nextNode.type !== expectedType) {
      nextNode = { ...nextNode, type: expectedType } as PersistedCanvasNode;
      nodeChanged = true;
    }

    const desiredZ =
      nextNode.type === "backgroundNode" ? BACKGROUND_Z_INDEX : FOREGROUND_Z_INDEX;
    if (nextNode.zIndex !== desiredZ) {
      nextNode = { ...nextNode, zIndex: desiredZ };
      nodeChanged = true;
    }

    if (data.kind === "label" || data.kind === "background") {
      const defaults =
        data.kind === "label" ? DEFAULT_LABEL_CONFIG : DEFAULT_BACKGROUND_CONFIG;
      const config = { ...defaults, ...(data.pluginConfig ?? {}) };
      const width =
        typeof config.width === "number" ? config.width : defaults.width;
      const height =
        typeof config.height === "number" ? config.height : defaults.height;
      if (
        nextNode.width !== width ||
        nextNode.height !== height ||
        !data.pluginConfig
      ) {
        nextNode = {
          ...nextNode,
          width,
          height,
          style: { ...nextNode.style, width, height },
          data: { ...nextNode.data, pluginConfig: config },
        };
        nodeChanged = true;
      }
    }

    if (data.kind === "get-from-user") {
      const existingParam =
        typeof data.pluginConfig?.device_param === "string"
          ? data.pluginConfig.device_param.trim()
          : "";
      if (!existingParam) {
        const config = { ...DEFAULT_GET_FROM_USER_CONFIG, ...(data.pluginConfig ?? {}) };
        nextNode = {
          ...nextNode,
          data: { ...nextNode.data, pluginConfig: config },
        };
        nodeChanged = true;
      }
    }

    if (nodeChanged) {
      migrated = true;
      return nextNode;
    }

    return node;
  });

  const migratedEdges = edges.map((edge) => {
    let nextEdge = edge;
    let edgeChanged = false;

    const legacyEdgeStyle = (edge.data as { edgeStyle?: string } | undefined)?.edgeStyle;
    if (legacyEdgeStyle === "smooth") {
      nextEdge = { ...nextEdge, data: { ...nextEdge.data, edgeStyle: "bezier" } };
      edgeChanged = true;
    }

    const targetNode = migratedNodes.find((node) => node.id === edge.target);
    const requires = targetNode?.data.requires ?? [];
    if (
      requires.length > 0 &&
      nextEdge.targetHandle &&
      nextEdge.targetHandle !== "input"
    ) {
      nextEdge = { ...nextEdge, targetHandle: "input" };
      edgeChanged = true;
    }

    if (edgeChanged) {
      migrated = true;
      return nextEdge;
    }

    return edge;
  });

  return { nodes: migratedNodes, edges: migratedEdges, migrated };
}
