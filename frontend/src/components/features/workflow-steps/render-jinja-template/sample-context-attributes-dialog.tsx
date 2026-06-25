"use client";

import { ChevronDown, ChevronRight, GripHorizontal, X } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { constrainFloatingPosition } from "./draggable-panel-position";

export const SAMPLE_ATTRIBUTES_PANEL_ATTR = "data-sample-attributes-panel";

export function isWithinSampleAttributesPanel(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest(`[${SAMPLE_ATTRIBUTES_PANEL_ATTR}]`));
}

type OutsideInteractionEvent = {
  target: EventTarget | null;
  preventDefault: () => void;
  detail?: { originalEvent?: Event };
};

function interactionTarget(event: OutsideInteractionEvent): EventTarget | null {
  return event.detail?.originalEvent?.target ?? event.target;
}

export function preventTemplateEditorDismissForSamplePanel(event: OutsideInteractionEvent) {
  if (isWithinSampleAttributesPanel(interactionTarget(event))) {
    event.preventDefault();
  }
}

interface SampleContextAttributesDialogProps {
  open: boolean;
  context: Record<string, unknown>;
  deviceName?: string;
  isForeground?: boolean;
  onClose: () => void;
  onFocus?: () => void;
}

const DEFAULT_POSITION = { x: 16, y: 72 };

function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return String(value);
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function ContextSection({
  name,
  value,
  defaultOpen = false,
}: {
  name: string;
  value: unknown;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const isObject = value !== null && typeof value === "object";
  const preview = useMemo(() => {
    if (!isObject) {
      return formatValue(value);
    }
    const keys = Object.keys(value as Record<string, unknown>);
    return keys.length === 0 ? "{}" : `${keys.length} key${keys.length === 1 ? "" : "s"}`;
  }, [isObject, value]);

  return (
    <div className="rounded-md border bg-background/80">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium hover:bg-muted/50"
        onClick={() => setOpen((current) => !current)}
      >
        {open ? (
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
        )}
        <span className="font-mono">{name}</span>
        {!open ? (
          <span className="ml-auto truncate text-[11px] font-normal text-muted-foreground">
            {preview}
          </span>
        ) : null}
      </button>
      {open ? (
        <pre className="max-h-64 overflow-auto border-t bg-muted/20 p-3 font-mono text-[11px] leading-5 whitespace-pre-wrap break-all">
          {formatValue(value)}
        </pre>
      ) : null}
    </div>
  );
}

export function SampleContextAttributesDialog({
  open,
  context,
  deviceName,
  isForeground = false,
  onClose,
  onFocus,
}: SampleContextAttributesDialogProps) {
  const sections = useMemo(() => Object.entries(context), [context]);
  const mounted = typeof window !== "undefined";
  const [position, setPosition] = useState(DEFAULT_POSITION);
  const [isDragging, setIsDragging] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const dragOffsetRef = useRef({ x: 0, y: 0 });

  const handleDragPointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    dragOffsetRef.current = {
      x: event.clientX - position.x,
      y: event.clientY - position.y,
    };
    setIsDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  }, [position.x, position.y]);

  const handleDragPointerMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!isDragging) {
      return;
    }
    event.preventDefault();
    const panel = panelRef.current;
    const width = panel?.offsetWidth ?? 320;
    const height = panel?.offsetHeight ?? 480;
    setPosition(
      constrainFloatingPosition(
        {
          x: event.clientX - dragOffsetRef.current.x,
          y: event.clientY - dragOffsetRef.current.y,
        },
        width,
        height,
      ),
    );
  }, [isDragging]);

  const handleDragPointerUp = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!isDragging) {
      return;
    }
    setIsDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, [isDragging]);

  if (!open || !mounted) {
    return null;
  }

  return createPortal(
    <div
      ref={panelRef}
      data-sample-attributes-panel=""
      className={cn(
        "pointer-events-auto fixed flex max-h-[84vh] w-[min(24rem,34vw)] flex-col overflow-hidden rounded-lg border bg-background shadow-2xl",
        isForeground ? "z-[110]" : "z-[100]",
        isDragging && "select-none",
      )}
      style={{ left: position.x, top: position.y }}
      onPointerDown={() => onFocus?.()}
    >
      <div className="flex items-start gap-2 border-b bg-muted/30 px-3 py-2">
        <div
          className={cn(
            "flex min-w-0 flex-1 cursor-grab items-start gap-2 active:cursor-grabbing",
            isDragging && "cursor-grabbing",
          )}
          onPointerDown={handleDragPointerDown}
          onPointerMove={handleDragPointerMove}
          onPointerUp={handleDragPointerUp}
          onPointerCancel={handleDragPointerUp}
        >
          <GripHorizontal className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold leading-5">Sample attributes</p>
            {deviceName ? (
              <p className="text-xs text-muted-foreground">
                Loaded from Nautobot: <span className="font-mono">{deviceName}</span>
              </p>
            ) : null}
          </div>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-7 shrink-0"
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            onClose();
          }}
          aria-label="Close sample attributes"
        >
          <X className="size-4" />
        </Button>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-4">
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="secondary" className="text-[10px]">
            editor only
          </Badge>
          <Badge variant="outline" className="text-[10px]">
            {sections.length} namespace{sections.length === 1 ? "" : "s"}
          </Badge>
        </div>
        <p className="text-[11px] leading-4 text-muted-foreground">
          Drag this panel aside while editing — it can extend past the window edge. Keep the
          header visible to move it back. Reference paths like{" "}
          <span className="font-mono">{"{{ device.hostname }}"}</span> or{" "}
          <span className="font-mono">{"{{ nautobot.role.name }}"}</span>.
        </p>
        {sections.map(([name, value], index) => (
          <ContextSection
            key={name}
            name={name}
            value={value}
            defaultOpen={index === 0}
          />
        ))}
      </div>
    </div>,
    document.body,
  );
}
