"use client";

import { useCallback, useMemo, useState } from "react";

import {
  type EdgeStyle,
  type HandleSide,
  type WorkflowEdgeData,
} from "../types/workflow-canvas";
import { resolveContainment } from "../utils/canvas-containment";
import { groupNodeId } from "../utils/canvas-group-projection";
import { alignCanvasNodes, type NodeAlignment } from "../utils/node-alignment";
import { runAutoLayout, type AutoLayoutDirection } from "../utils/auto-layout";
import type { UseWorkflowCanvasCoreResult } from "./use-workflow-canvas-core";

/**
 * Edge styling/labels, node title and handle-side editing, node alignment,
 * and auto-layout — everything that repositions or restyles existing canvas
 * content without changing which nodes/edges/groups exist.
 */
export function useCanvasLayout(core: UseWorkflowCanvasCoreResult) {
  const {
    projected,
    setAllNodes,
    setAllEdges,
    setGroups,
    markDirty,
    requestFitView,
    toast,
  } = core;

  const [isAutoLayoutRunning, setIsAutoLayoutRunning] = useState(false);

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
    [projected.edges, setAllEdges, markDirty],
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
    [projected.edges, setAllEdges, markDirty],
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
    [setAllNodes, markDirty],
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
    [setAllNodes, markDirty],
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
    [setAllNodes, markDirty],
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
    [projected.nodes, setAllNodes, setGroups, markDirty],
  );

  const handleAutoLayout = useCallback(
    async (nodeIds: string[] | null, direction: AutoLayoutDirection) => {
      setIsAutoLayoutRunning(true);
      try {
        const result = await runAutoLayout(projected.nodes, projected.edges, direction, nodeIds);
        if (result.movedNodeIds.length === 0) {
          return;
        }
        const movedIds = new Set(result.movedNodeIds);
        const positionById = new Map(result.nodes.map((n) => [n.id, n.position]));

        setAllNodes((current) => {
          const withNewPositions = current.map((n) =>
            movedIds.has(n.id) && positionById.has(n.id)
              ? { ...n, position: positionById.get(n.id)! }
              : n,
          );
          // Re-resolve background containment per moved node, same as the
          // drag-end path in handleNodesChange — a step relaid out
          // into/out of a background must not keep a stale parentId.
          let next = withNewPositions;
          for (const id of movedIds) {
            const node = next.find((n) => n.id === id);
            if (!node) continue;
            const { parentId, position } = resolveContainment(node, next);
            next = next.map((n) => (n.id === id ? { ...n, parentId, position } : n));
          }
          return next;
        });

        setGroups((current) =>
          current.map((g) => {
            const syntheticId = groupNodeId(g.id);
            return positionById.has(syntheticId)
              ? { ...g, position: positionById.get(syntheticId)! }
              : g;
          }),
        );

        // Manual bends no longer make geometric sense once either endpoint
        // moved. Resolved against `projected.edges` (not `allEdges` directly)
        // so a group-boundary proxy edge whose *synthetic* group-node
        // endpoint moved still maps back to its real edge id.
        const touchedRealEdgeIds = new Set(
          projected.edges
            .filter((e) => movedIds.has(e.source) || movedIds.has(e.target))
            .map((e) => e.data?.realEdgeId ?? e.id),
        );
        setAllEdges((current) =>
          current.map((e) =>
            touchedRealEdgeIds.has(e.id)
              ? { ...e, data: { ...e.data, waypoints: undefined } }
              : e,
          ),
        );

        requestFitView(result.movedNodeIds);
        markDirty();
      } catch {
        toast({
          title: "Auto layout failed",
          description: "Could not lay out the canvas. Nothing was moved.",
          variant: "destructive",
        });
      } finally {
        setIsAutoLayoutRunning(false);
      }
    },
    [
      projected.nodes,
      projected.edges,
      setAllNodes,
      setAllEdges,
      setGroups,
      requestFitView,
      markDirty,
      toast,
    ],
  );

  return useMemo(
    () => ({
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
      handleAutoLayout,
      isAutoLayoutRunning,
    }),
    [
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
      handleAutoLayout,
      isAutoLayoutRunning,
    ],
  );
}

export type UseCanvasLayoutResult = ReturnType<typeof useCanvasLayout>;
