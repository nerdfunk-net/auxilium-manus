"use client";

import { useCallback, useMemo, useState } from "react";

export interface ResizableColumn {
  key: string;
  defaultWidth: number;
  minWidth: number;
  /** Largest width in pixels; MAX_COLUMN_WIDTH when not given. */
  maxWidth?: number;
}

/**
 * A column can be dragged this wide at most. A width read from localStorage is
 * clamped as well, so a huge stored number cannot make the grid arbitrarily wide.
 */
export const MAX_COLUMN_WIDTH = 600;

function clampWidth(column: ResizableColumn, value: number): number {
  return Math.min(column.maxWidth ?? MAX_COLUMN_WIDTH, Math.max(column.minWidth, value));
}

const STORAGE_PREFIX = "resizable-columns:";

function readStoredWidths(
  storageKey: string,
  columns: readonly ResizableColumn[],
): Record<string, number> {
  const defaults = Object.fromEntries(columns.map((c) => [c.key, c.defaultWidth]));
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + storageKey);
    if (!raw) {
      return defaults;
    }
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) {
      return defaults;
    }
    const stored = parsed as Record<string, unknown>;
    return Object.fromEntries(
      columns.map((c) => {
        const value = stored[c.key];
        return [
          c.key,
          typeof value === "number" && Number.isFinite(value)
            ? clampWidth(c, value)
            : c.defaultWidth,
        ];
      }),
    );
  } catch {
    // Storage can be blocked or hold bad JSON; the defaults are always usable.
    return defaults;
  }
}

/**
 * Pixel widths for a set of resizable columns. The widths are a per-viewer
 * convenience, so they are kept in localStorage and the page works without it.
 */
export function useResizableColumns(
  storageKey: string,
  columns: readonly ResizableColumn[],
) {
  // Only use this in a component that renders on the client after data has
  // loaded (not on the server's first pass), or the stored widths would differ
  // from the server markup.
  const [widths, setWidths] = useState<Record<string, number>>(() =>
    readStoredWidths(storageKey, columns),
  );

  const persist = useCallback(
    (next: Record<string, number>) => {
      try {
        window.localStorage.setItem(STORAGE_PREFIX + storageKey, JSON.stringify(next));
      } catch {
        // Ignored on purpose: the widths only live for this page view then.
      }
    },
    [storageKey],
  );

  const resizeBy = useCallback(
    (key: string, delta: number, startWidth: number) => {
      const column = columns.find((c) => c.key === key);
      if (!column) {
        return;
      }
      const next = clampWidth(column, Math.round(startWidth + delta));
      setWidths((current) => ({ ...current, [key]: next }));
    },
    [columns],
  );

  const commit = useCallback(() => {
    setWidths((current) => {
      persist(current);
      return current;
    });
  }, [persist]);

  const reset = useCallback(() => {
    const defaults = Object.fromEntries(columns.map((c) => [c.key, c.defaultWidth]));
    setWidths(defaults);
    persist(defaults);
  }, [columns, persist]);

  return useMemo(
    () => ({ widths, resizeBy, commit, reset }),
    [widths, resizeBy, commit, reset],
  );
}
