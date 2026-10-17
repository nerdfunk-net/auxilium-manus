"use client";

import {
  BaseEdge,
  EdgeLabelRenderer,
  type EdgeProps,
  getBezierPath,
  getSmoothStepPath,
  useReactFlow,
} from "@xyflow/react";
import { useCallback, useRef } from "react";

import { cn } from "@/lib/utils";

import {
  DEFAULT_EDGE_LABEL_FONT_SIZE,
  DEFAULT_EDGE_STYLE,
  type Waypoint,
  type WorkflowCanvasEdge,
} from "../../types/workflow-canvas";

/** Fraction of the way from the source/target point toward the edge midpoint,
 * so start/end labels clear the connected node's card instead of sitting
 * right on its boundary and getting visually clipped. */
const END_LABEL_MIDPOINT_PULL = 0.2;

/** Ensures debug labels always paint above node cards, regardless of DOM order. */
const EDGE_LABEL_Z_INDEX = 1000;

function buildPath(
  sourceX: number,
  sourceY: number,
  targetX: number,
  targetY: number,
  waypoints: Waypoint[],
): string {
  const points = [{ x: sourceX, y: sourceY }, ...waypoints, { x: targetX, y: targetY }];
  return points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
}

function distToSegment(p: Waypoint, a: Waypoint, b: Waypoint): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return Math.hypot(p.x - a.x, p.y - a.y);
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq));
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

export function WaypointEdge({
  id,
  sourceX,
  sourceY,
  sourcePosition,
  targetX,
  targetY,
  targetPosition,
  data,
  markerEnd,
  style,
  selected,
}: EdgeProps<WorkflowCanvasEdge>) {
  // ── All hooks first — no conditional returns above this line ────────────
  const { setEdges, screenToFlowPosition } = useReactFlow();
  const draggingIndex = useRef<number | null>(null);

  const handleDoubleClick = useCallback(
    (e: React.MouseEvent<SVGPathElement>) => {
      e.stopPropagation();
      const flowPos = screenToFlowPosition({ x: e.clientX, y: e.clientY });
      const waypoints = (data?.waypoints as Waypoint[] | undefined) ?? [];
      const allPoints = [
        { x: sourceX, y: sourceY },
        ...waypoints,
        { x: targetX, y: targetY },
      ];

      let minDist = Infinity;
      let insertAt = 0;
      for (let i = 0; i < allPoints.length - 1; i++) {
        const dist = distToSegment(flowPos, allPoints[i], allPoints[i + 1]);
        if (dist < minDist) {
          minDist = dist;
          insertAt = i;
        }
      }

      setEdges((edges) =>
        edges.map((edge) => {
          if (edge.id !== id) return edge;
          const current = (edge.data?.waypoints as Waypoint[] | undefined) ?? [];
          const next = [...current];
          next.splice(insertAt, 0, flowPos);
          return { ...edge, data: { ...edge.data, waypoints: next } };
        }),
      );
    },
    [id, data?.waypoints, sourceX, sourceY, targetX, targetY, setEdges, screenToFlowPosition],
  );

  const handleWaypointMouseDown = useCallback(
    (e: React.MouseEvent<SVGCircleElement>, index: number) => {
      e.stopPropagation();
      e.preventDefault();
      draggingIndex.current = index;

      const onMouseMove = (ev: MouseEvent) => {
        if (draggingIndex.current === null) return;
        const idx = draggingIndex.current;
        const flowPos = screenToFlowPosition({ x: ev.clientX, y: ev.clientY });
        setEdges((edges) =>
          edges.map((edge) => {
            if (edge.id !== id) return edge;
            const next = [...((edge.data?.waypoints as Waypoint[] | undefined) ?? [])];
            next[idx] = flowPos;
            return { ...edge, data: { ...edge.data, waypoints: next } };
          }),
        );
      };

      const onMouseUp = () => {
        draggingIndex.current = null;
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
      };

      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    },
    [id, setEdges, screenToFlowPosition],
  );

  const handleWaypointContextMenu = useCallback(
    (e: React.MouseEvent<SVGCircleElement>, index: number) => {
      e.preventDefault();
      e.stopPropagation();
      setEdges((edges) =>
        edges.map((edge) => {
          if (edge.id !== id) return edge;
          const next = ((edge.data?.waypoints as Waypoint[] | undefined) ?? []).filter(
            (_, i) => i !== index,
          );
          return { ...edge, data: { ...edge.data, waypoints: next } };
        }),
      );
    },
    [id, setEdges],
  );
  // ── End of hooks ─────────────────────────────────────────────────────────

  const waypoints: Waypoint[] = (data?.waypoints as Waypoint[] | undefined) ?? [];
  const edgeStyleValue = data?.edgeStyle ?? DEFAULT_EDGE_STYLE;
  const edgeColor = selected ? "#6366f1" : "#94a3b8";
  const edgeWidth = selected ? 2 : 1.5;
  const labelX = (sourceX + targetX) / 2;
  const labelY = (sourceY + targetY) / 2;
  const labelText = data?.label;
  const startLabelText = data?.startLabel;
  const endLabelText = data?.endLabel;
  const hasAnyLabel = !!labelText || !!startLabelText || !!endLabelText;
  const labelBold = !!data?.labelBold;
  const labelFontSize = data?.labelFontSize ?? DEFAULT_EDGE_LABEL_FONT_SIZE;

  // Pulled toward the midpoint so the pill clears the connected node's card
  // instead of sitting on its boundary (where it would be visually clipped).
  const startAnchor = {
    x: sourceX + (labelX - sourceX) * END_LABEL_MIDPOINT_PULL,
    y: sourceY + (labelY - sourceY) * END_LABEL_MIDPOINT_PULL,
  };
  const endAnchor = {
    x: targetX + (labelX - targetX) * END_LABEL_MIDPOINT_PULL,
    y: targetY + (labelY - targetY) * END_LABEL_MIDPOINT_PULL,
  };

  const labelPillClassName = cn(
    "nodrag nopan pointer-events-none absolute rounded-full bg-background px-1.5 py-0.5 text-muted-foreground shadow-sm",
    labelBold ? "font-bold" : "font-medium",
  );
  const labelPillStyle: React.CSSProperties = {
    fontSize: `${labelFontSize}px`,
    zIndex: EDGE_LABEL_Z_INDEX,
  };

  const labelNode = hasAnyLabel ? (
    <EdgeLabelRenderer>
      {startLabelText ? (
        <span
          className={labelPillClassName}
          style={{
            ...labelPillStyle,
            transform: `translate(-50%, -50%) translate(${startAnchor.x}px, ${startAnchor.y}px)`,
          }}
        >
          {startLabelText}
        </span>
      ) : null}
      {labelText ? (
        <span
          className={labelPillClassName}
          style={{
            ...labelPillStyle,
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
          }}
        >
          {labelText}
        </span>
      ) : null}
      {endLabelText ? (
        <span
          className={labelPillClassName}
          style={{
            ...labelPillStyle,
            transform: `translate(-50%, -50%) translate(${endAnchor.x}px, ${endAnchor.y}px)`,
          }}
        >
          {endLabelText}
        </span>
      ) : null}
    </EdgeLabelRenderer>
  ) : null;

  // ── Bezier / step / smoothstep modes — React Flow computes the path ───────
  if (edgeStyleValue !== "straight") {
    const pathParams = { sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition };
    const [path] =
      edgeStyleValue === "step"
        ? getSmoothStepPath({ ...pathParams, borderRadius: 0 })
        : edgeStyleValue === "smoothstep"
          ? getSmoothStepPath(pathParams)
          : getBezierPath(pathParams);

    return (
      <>
        <BaseEdge
          path={path}
          markerEnd={markerEnd}
          style={{ ...style, stroke: edgeColor, strokeWidth: edgeWidth }}
        />
        {labelNode}
      </>
    );
  }

  // ── Straight (waypoint) mode ──────────────────────────────────────────────
  const d = buildPath(sourceX, sourceY, targetX, targetY, waypoints);

  return (
    <>
      <g>
        {/* Wide transparent hit area — double-click to add a waypoint */}
        <path
          d={d}
          fill="none"
          stroke="transparent"
          strokeWidth={20}
          style={{ cursor: "crosshair" }}
          onDoubleClick={handleDoubleClick}
        />
        {/* Visible edge line */}
        <path
          className="react-flow__edge-path"
          d={d}
          fill="none"
          markerEnd={markerEnd}
          stroke={edgeColor}
          strokeWidth={edgeWidth}
          style={style}
        />
        {/* Waypoint handles — visible only when edge is selected */}
        {selected
          ? waypoints.map((wp, index) => (
              <circle
                key={index}
                cx={wp.x}
                cy={wp.y}
                r={5}
                fill="white"
                stroke="#6366f1"
                strokeWidth={2}
                style={{ cursor: "move" }}
                onMouseDown={(e) => handleWaypointMouseDown(e, index)}
                onContextMenu={(e) => handleWaypointContextMenu(e, index)}
              />
            ))
          : null}
      </g>
      {labelNode}
    </>
  );
}
