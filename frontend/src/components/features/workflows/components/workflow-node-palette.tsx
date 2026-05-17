"use client";

import {
  ChevronDown,
  ChevronUp,
  FileArchive,
  GitBranch,
  GripVertical,
  Network,
  Plus,
  Router,
  TerminalSquare,
  X,
} from "lucide-react";
import {
  useCallback,
  useRef,
  useState,
  type PointerEvent,
} from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import type { WorkflowNodeKind } from "../types/workflow-canvas";

type PaletteItem = {
  kind: WorkflowNodeKind;
  label: string;
  description: string;
  icon: typeof Router;
};

const paletteItems: PaletteItem[] = [
  {
    kind: "device-selection",
    label: "Device Selection",
    description: "Choose target devices from inventory.",
    icon: Router,
  },
  {
    kind: "ssh-login",
    label: "SSH Login",
    description: "Open a managed CLI session.",
    icon: Network,
  },
  {
    kind: "run-command",
    label: "Run Command",
    description: "Execute a command against each device.",
    icon: TerminalSquare,
  },
  {
    kind: "condition",
    label: "Condition",
    description: "Branch based on metadata or content.",
    icon: GitBranch,
  },
  {
    kind: "store-artifact",
    label: "Store Artifact",
    description: "Persist generated content.",
    icon: FileArchive,
  },
];

const INITIAL_PANEL_POSITION = { x: 20, y: 20 };
const PALETTE_BODY_ID = "workflow-node-palette-body";

type PanelPosition = typeof INITIAL_PANEL_POSITION;

interface NodePaletteProps {
  onAddStep: (step: {
    kind: WorkflowNodeKind;
    title: string;
    description: string;
  }) => void;
}

export function NodePalette({ onAddStep }: NodePaletteProps) {
  const firstItem = paletteItems[0];
  const hideActionsPanel = useWorkflowBuilderStore(
    (state) => state.hideActionsPanel,
  );
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [position, setPosition] = useState<PanelPosition>(
    INITIAL_PANEL_POSITION,
  );
  const panelRef = useRef<HTMLDivElement>(null);
  const dragStartRef = useRef<{
    pointerId: number;
    pointerX: number;
    pointerY: number;
    panelX: number;
    panelY: number;
  } | null>(null);

  const addStep = useCallback(
    (item: PaletteItem) => {
      onAddStep({
        kind: item.kind,
        title: item.label,
        description: item.description,
      });
    },
    [onAddStep],
  );

  const handleDragStart = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) {
        return;
      }

      event.stopPropagation();
      event.currentTarget.setPointerCapture(event.pointerId);
      dragStartRef.current = {
        pointerId: event.pointerId,
        pointerX: event.clientX,
        pointerY: event.clientY,
        panelX: position.x,
        panelY: position.y,
      };
    },
    [position.x, position.y],
  );

  const handleDragMove = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const dragStart = dragStartRef.current;

    if (!dragStart || dragStart.pointerId !== event.pointerId) {
      return;
    }

    event.stopPropagation();
    const panel = panelRef.current;
    const container = panel?.parentElement;
    const maxX =
      panel && container
        ? Math.max(0, container.clientWidth - panel.offsetWidth)
        : Number.POSITIVE_INFINITY;
    const maxY =
      panel && container
        ? Math.max(0, container.clientHeight - panel.offsetHeight)
        : Number.POSITIVE_INFINITY;
    const nextX = dragStart.panelX + event.clientX - dragStart.pointerX;
    const nextY = dragStart.panelY + event.clientY - dragStart.pointerY;

    setPosition({
      x: Math.min(Math.max(0, nextX), maxX),
      y: Math.min(Math.max(0, nextY), maxY),
    });
  }, []);

  const handleDragEnd = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const dragStart = dragStartRef.current;

    if (!dragStart || dragStart.pointerId !== event.pointerId) {
      return;
    }

    event.stopPropagation();
    event.currentTarget.releasePointerCapture(event.pointerId);
    dragStartRef.current = null;
  }, []);

  return (
    <div
      ref={panelRef}
      className={cn(
        "absolute z-10 w-64 rounded-xl border bg-card shadow-sm",
        isCollapsed ? "p-2" : "p-3",
      )}
      style={{ left: position.x, top: position.y }}
    >
      <div
        className={cn(
          "flex cursor-move touch-none select-none items-center justify-between gap-2",
          !isCollapsed && "mb-3",
        )}
        onPointerCancel={handleDragEnd}
        onPointerDown={handleDragStart}
        onPointerMove={handleDragMove}
        onPointerUp={handleDragEnd}
      >
        <div className="flex min-w-0 items-center gap-2">
          <GripVertical className="size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <p className="text-sm font-semibold">Add step</p>
            {!isCollapsed ? (
              <p className="text-xs text-muted-foreground">
                Workflow building blocks
              </p>
            ) : null}
          </div>
        </div>
        <div
          className="flex items-center gap-1"
          onPointerDown={(event) => event.stopPropagation()}
        >
          <Button
            aria-controls={PALETTE_BODY_ID}
            aria-expanded={!isCollapsed}
            aria-label={
              isCollapsed ? "Expand add step panel" : "Collapse add step panel"
            }
            onClick={() => setIsCollapsed((current) => !current)}
            size="icon"
            variant="ghost"
          >
            {isCollapsed ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronUp className="size-4" />
            )}
          </Button>
          <Button
            aria-label="Hide add step panel"
            onClick={hideActionsPanel}
            size="icon"
            variant="ghost"
          >
            <X className="size-4" />
          </Button>
        </div>
      </div>
      <div id={PALETTE_BODY_ID} hidden={isCollapsed}>
        <div>
          <div className="mb-3 flex items-center justify-between rounded-lg bg-muted/40 px-3 py-2">
            <div>
              <p className="text-xs font-medium">Quick add</p>
              <p className="text-xs text-muted-foreground">
                Add the first workflow step
              </p>
            </div>
            <Button
              aria-label="Add workflow step"
              onClick={() => addStep(firstItem)}
              size="icon"
              variant="outline"
            >
              <Plus className="size-4" />
            </Button>
          </div>
          <div className="space-y-1">
            {paletteItems.map((item) => (
              <button
                key={item.label}
                className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
                onClick={() => addStep(item)}
                type="button"
              >
                <item.icon className="size-4 text-muted-foreground" />
                {item.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      {isCollapsed ? (
        <Button
          className="mt-2 w-full justify-start"
          onClick={() => setIsCollapsed(false)}
          size="sm"
          variant="outline"
        >
          <Plus className="size-4" />
          Show actions
        </Button>
      ) : null}
    </div>
  );
}
