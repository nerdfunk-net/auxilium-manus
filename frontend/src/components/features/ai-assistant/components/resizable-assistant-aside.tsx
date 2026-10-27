"use client";

import { useCallback, useRef, useState } from "react";

import { cn } from "@/lib/utils";

const STORAGE_KEY = "manus.ai-assistant.width";
const DEFAULT_WIDTH = 420;
const MIN_WIDTH = 320;
const MAX_WIDTH = 900;
const KEYBOARD_STEP = 24;

function clampWidth(width: number): number {
  const viewportMax =
    typeof window === "undefined" ? MAX_WIDTH : window.innerWidth * 0.7;
  return Math.round(
    Math.min(Math.max(width, MIN_WIDTH), Math.min(MAX_WIDTH, viewportMax)),
  );
}

function readStoredWidth(): number {
  try {
    const stored = Number(window.localStorage.getItem(STORAGE_KEY));
    return Number.isFinite(stored) && stored > 0
      ? clampWidth(stored)
      : DEFAULT_WIDTH;
  } catch {
    return DEFAULT_WIDTH;
  }
}

function storeWidth(width: number): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(width));
  } catch {
    // Storage can be blocked; the width then only lasts for this page view.
  }
}

interface ResizableAssistantAsideProps {
  children: React.ReactNode;
  className?: string;
}

/**
 * Right-hand AI assistant column with a drag handle on its left edge. The width is shared by every
 * page that hosts the assistant and remembered in this browser.
 */
export function ResizableAssistantAside({
  children,
  className,
}: ResizableAssistantAsideProps) {
  const [width, setWidth] = useState(readStoredWidth);
  const widthRef = useRef(width);
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null);

  const applyWidth = useCallback((next: number) => {
    const clamped = clampWidth(next);
    widthRef.current = clamped;
    setWidth(clamped);
  }, []);

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.currentTarget.setPointerCapture(event.pointerId);
      dragRef.current = {
        startX: event.clientX,
        startWidth: widthRef.current,
      };
    },
    [],
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      if (drag) {
        // The panel is on the right, so dragging left makes it wider.
        applyWidth(drag.startWidth + (drag.startX - event.clientX));
      }
    },
    [applyWidth],
  );

  const handlePointerUp = useCallback(() => {
    if (dragRef.current) {
      dragRef.current = null;
      storeWidth(widthRef.current);
    }
  }, []);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
        return;
      }
      event.preventDefault();
      applyWidth(
        widthRef.current +
          (event.key === "ArrowLeft" ? KEYBOARD_STEP : -KEYBOARD_STEP),
      );
      storeWidth(widthRef.current);
    },
    [applyWidth],
  );

  return (
    <aside
      style={{ width }}
      className={cn(
        "relative flex shrink-0 flex-col gap-3 border-l bg-card p-4",
        className,
      )}
      aria-label="AI Assistant"
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize AI Assistant"
        aria-valuemin={MIN_WIDTH}
        aria-valuemax={MAX_WIDTH}
        aria-valuenow={width}
        tabIndex={0}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onKeyDown={handleKeyDown}
        className="absolute inset-y-0 -left-1 z-10 w-2 cursor-col-resize touch-none select-none transition-colors hover:bg-primary/30 focus-visible:bg-primary/40 focus-visible:outline-none active:bg-primary/40"
      />
      {children}
    </aside>
  );
}
