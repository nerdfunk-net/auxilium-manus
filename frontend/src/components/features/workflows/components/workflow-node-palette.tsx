"use client";

import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Code2,
  FileArchive,
  FileText,
  GitBranch,
  GripVertical,
  HardDriveDownload,
  Plus,
  Router,
  TerminalSquare,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type PointerEvent,
} from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { Capability } from "@/lib/capability-types";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import type { PluginDefinition } from "../types/plugin-registry";
import type { WorkflowNodeKind, WorkflowOutcomeField } from "../types/workflow-canvas";

type PaletteItem = {
  kind: WorkflowNodeKind;
  label: string;
  description: string;
  artifactType: string;
  requires: Capability[];
  requiresParsed: string[];
  produces: Capability[];
  producesParsed: string[];
  consumes: Capability[];
  outcomes: WorkflowOutcomeField[];
  icon: LucideIcon;
};

type PaletteGroup = {
  artifactType: string;
  label: string;
  items: PaletteItem[];
};

const INITIAL_PANEL_POSITION = { x: 20, y: 20 };
const PALETTE_BODY_ID = "workflow-node-palette-body";

type PanelPosition = typeof INITIAL_PANEL_POSITION;

interface NodePaletteProps {
  errorMessage?: string;
  isLoading: boolean;
  onAddStep: (step: {
    kind: WorkflowNodeKind;
    title: string;
    description: string;
    artifactType: string;
    requires: Capability[];
    requiresParsed: string[];
    produces: Capability[];
    producesParsed: string[];
    consumes: Capability[];
    outcomes: WorkflowOutcomeField[];
  }) => void;
  plugins: PluginDefinition[];
}

const iconByArtifactType: Record<string, LucideIcon> = {
  command_execution: TerminalSquare,
  configuration_retrieval: HardDriveDownload,
  control_flow: GitBranch,
  inventory_selector: Router,
  persistent_artifact: FileArchive,
  template_rendering: FileText,
};

function formatArtifactType(artifactType: string) {
  return artifactType
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function toPaletteItem(plugin: PluginDefinition): PaletteItem {
  return {
    kind: plugin.id,
    label: plugin.name,
    description: plugin.description,
    artifactType: plugin.artifact_type,
    requires: (plugin.requires ?? []) as Capability[],
    requiresParsed: plugin.requires_parsed ?? [],
    produces: (plugin.produces ?? []) as Capability[],
    producesParsed: plugin.produces_parsed ?? [],
    consumes: (plugin.consumes ?? []) as Capability[],
    outcomes: plugin.outcomes.map((outcome) => ({ name: outcome.name })),
    icon: iconByArtifactType[plugin.artifact_type] ?? Code2,
  };
}

const ARTIFACT_TYPE_ORDER = [
  "inventory_selector",
  "control_flow",
  "template_rendering",
  "command_execution",
  "configuration_retrieval",
  "persistent_artifact",
];

function groupPaletteItems(plugins: PluginDefinition[]): PaletteGroup[] {
  const groups = new Map<string, PaletteItem[]>();

  for (const plugin of plugins) {
    const items = groups.get(plugin.artifact_type) ?? [];
    items.push(toPaletteItem(plugin));
    groups.set(plugin.artifact_type, items);
  }

  return Array.from(groups.entries())
    .sort(([left], [right]) => {
      const leftIndex = ARTIFACT_TYPE_ORDER.indexOf(left);
      const rightIndex = ARTIFACT_TYPE_ORDER.indexOf(right);
      const leftOrder = leftIndex === -1 ? Number.MAX_SAFE_INTEGER : leftIndex;
      const rightOrder = rightIndex === -1 ? Number.MAX_SAFE_INTEGER : rightIndex;
      return leftOrder - rightOrder || left.localeCompare(right);
    })
    .map(([artifactType, items]) => ({
      artifactType,
      label: formatArtifactType(artifactType),
      items: items.sort((left, right) => left.label.localeCompare(right.label)),
    }));
}

export function NodePalette({
  errorMessage,
  isLoading,
  onAddStep,
  plugins,
}: NodePaletteProps) {
  const paletteGroups = useMemo(() => groupPaletteItems(plugins), [plugins]);
  const hideActionsPanel = useWorkflowBuilderStore(
    (state) => state.hideActionsPanel,
  );
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState<PaletteGroup | null>(null);
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
        artifactType: item.artifactType,
        requires: item.requires,
        requiresParsed: item.requiresParsed,
        produces: item.produces,
        producesParsed: item.producesParsed,
        consumes: item.consumes,
        outcomes: item.outcomes,
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
        {isLoading ? (
          <p className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
            Loading plugins...
          </p>
        ) : errorMessage ? (
          <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-4 text-sm text-destructive">
            {errorMessage}
          </p>
        ) : paletteGroups.length === 0 ? (
          <p className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
            No plugins are available.
          </p>
        ) : selectedGroup === null ? (
          <div className="max-h-[60vh] space-y-1 overflow-y-auto">
            {paletteGroups.map((group) => {
              const Icon = iconByArtifactType[group.artifactType] ?? Code2;
              return (
                <button
                  key={group.artifactType}
                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
                  onClick={() => setSelectedGroup(group)}
                  type="button"
                >
                  <Icon className="size-4 shrink-0 text-muted-foreground" />
                  <span className="flex-1 font-medium">{group.label}</span>
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                </button>
              );
            })}
          </div>
        ) : (
          <div>
            <div className="mb-2 flex items-center gap-1">
              <Button
                aria-label="Back to categories"
                onClick={() => setSelectedGroup(null)}
                size="icon"
                variant="ghost"
              >
                <ChevronLeft className="size-4" />
              </Button>
              <span className="text-xs font-semibold text-muted-foreground">
                {selectedGroup.label}
              </span>
            </div>
            <div className="max-h-[60vh] space-y-1 overflow-y-auto">
              {selectedGroup.items.map((item) => (
                <button
                  key={item.kind}
                  className="flex w-full items-start gap-3 rounded-lg px-2 py-2 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
                  onClick={() => addStep(item)}
                  type="button"
                >
                  <item.icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0">
                    <span className="block truncate">{item.label}</span>
                    <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">
                      {item.description}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
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
