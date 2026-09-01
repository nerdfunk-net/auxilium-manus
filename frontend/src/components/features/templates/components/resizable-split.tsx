"use client";

import { GripVertical } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";

import { cn } from "@/lib/utils";

import {
  clampPanelWidth,
  DEFAULT_VARIABLES_WIDTH,
} from "../utils/clamp-panel-width";

const KEYBOARD_STEP = 16;

interface ResizableSplitProps {
  left: ReactNode;
  right: ReactNode;
  /** localStorage key used to persist the left-panel width across reloads. */
  storageKey: string;
  /** Minimum height of the split row, in pixels. */
  minHeight?: number;
}

function readStoredWidth(storageKey: string): number | null {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (raw === null) {
      return null;
    }
    const parsed = Number.parseFloat(raw);
    return Number.isFinite(parsed) ? clampPanelWidth(parsed) : null;
  } catch {
    return null;
  }
}

function writeStoredWidth(storageKey: string, width: number): void {
  try {
    window.localStorage.setItem(storageKey, String(width));
  } catch {
    // Ignore — private mode / storage disabled. Resizing still works this session.
  }
}

/**
 * Two panels separated by a draggable vertical divider. The left panel's width
 * is clamped to the VARIABLES-panel bounds and persisted to localStorage. Below
 * the `lg` breakpoint the panels stack and the divider is hidden.
 */
export function ResizableSplit({
  left,
  right,
  storageKey,
  minHeight = 480,
}: ResizableSplitProps) {
  const [leftWidth, setLeftWidth] = useState(DEFAULT_VARIABLES_WIDTH);
  // Mirrors leftWidth so the drag handlers can read/persist the latest value
  // without stale-closure issues mid-drag.
  const widthRef = useRef(leftWidth);

  const applyWidth = useCallback((next: number) => {
    const clamped = clampPanelWidth(next);
    widthRef.current = clamped;
    setLeftWidth(clamped);
    return clamped;
  }, []);

  // Restore the persisted width on the client only, after hydration, so the
  // server markup and the first client render match; the width then updates in
  // a follow-up render (same pattern as auth/login-page.tsx).
  useEffect(() => {
    const restore = async () => {
      const stored = readStoredWidth(storageKey);
      if (stored !== null) {
        applyWidth(stored);
      }
    };
    void restore();
  }, [storageKey, applyWidth]);

  const handleMouseDown = useCallback(
    (event: MouseEvent<HTMLDivElement>) => {
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = widthRef.current;

      const handleMouseMove = (moveEvent: globalThis.MouseEvent) => {
        applyWidth(startWidth + moveEvent.clientX - startX);
      };

      const handleMouseUp = () => {
        document.removeEventListener("mousemove", handleMouseMove);
        document.removeEventListener("mouseup", handleMouseUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        writeStoredWidth(storageKey, widthRef.current);
      };

      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    },
    [applyWidth, storageKey],
  );

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
        return;
      }
      event.preventDefault();
      const delta = event.key === "ArrowLeft" ? -KEYBOARD_STEP : KEYBOARD_STEP;
      const next = applyWidth(widthRef.current + delta);
      writeStoredWidth(storageKey, next);
    },
    [applyWidth, storageKey],
  );

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:gap-0" style={{ minHeight }}>
      <div className="shrink-0 max-lg:!w-full" style={{ width: leftWidth }}>
        {left}
      </div>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize variables panel"
        tabIndex={0}
        onMouseDown={handleMouseDown}
        onKeyDown={handleKeyDown}
        className={cn(
          "hidden w-2 shrink-0 cursor-col-resize items-center justify-center",
          "text-muted-foreground/60 transition-colors hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
          "lg:flex",
        )}
      >
        <GripVertical className="size-3" />
      </div>

      <div className="min-w-0 flex-1">{right}</div>
    </div>
  );
}
