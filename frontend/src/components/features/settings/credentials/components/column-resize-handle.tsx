"use client";

import { useCallback, useRef } from "react";

interface ColumnResizeHandleProps {
  label: string;
  width: number;
  onResize: (delta: number, startWidth: number) => void;
  onCommit: () => void;
  onReset: () => void;
}

const KEY_STEP = 16;

/** Drag (or use the arrow keys) to change the width of the column to its left. */
export function ColumnResizeHandle({
  label,
  width,
  onResize,
  onCommit,
  onReset,
}: ColumnResizeHandleProps) {
  const drag = useRef<{ startX: number; startWidth: number } | null>(null);

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = { startX: event.clientX, startWidth: width };
    },
    [width],
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!drag.current) {
        return;
      }
      onResize(event.clientX - drag.current.startX, drag.current.startWidth);
    },
    [onResize],
  );

  const handlePointerUp = useCallback(() => {
    if (!drag.current) {
      return;
    }
    drag.current = null;
    onCommit();
  }, [onCommit]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
        return;
      }
      event.preventDefault();
      onResize(event.key === "ArrowRight" ? KEY_STEP : -KEY_STEP, width);
      onCommit();
    },
    [onCommit, onResize, width],
  );

  return (
    <div
      aria-label={`Resize ${label} column`}
      aria-orientation="vertical"
      aria-valuenow={width}
      className="absolute -right-2 top-0 z-10 flex h-full w-3 cursor-col-resize touch-none select-none justify-center focus-visible:outline-none group"
      role="separator"
      tabIndex={0}
      title="Drag to resize, double-click to reset all columns"
      onDoubleClick={onReset}
      onKeyDown={handleKeyDown}
      onPointerCancel={handlePointerUp}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
    >
      <div className="h-full w-px bg-border group-hover:bg-primary group-focus-visible:bg-primary" />
    </div>
  );
}
