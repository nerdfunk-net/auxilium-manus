"use client";

import {
  ChevronDown,
  ChevronUp,
  Code2,
  FileArchive,
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

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import type { PluginDefinition } from "../types/plugin-registry";
import type { WorkflowNodeKind } from "../types/workflow-canvas";

type PaletteItem = {
  kind: WorkflowNodeKind;
  label: string;
  description: string;
  artifactType: string;
  mandatoryInputs: string[];
  supportedOutputs: string[];
  outcomes: string[];
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
    mandatoryInputs: string[];
    supportedOutputs: string[];
    outcomes: string[];
  }) => void;
  plugins: PluginDefinition[];
}

const iconByArtifactType: Record<string, LucideIcon> = {
  command_execution: TerminalSquare,
  configuration_retrieval: HardDriveDownload,
  control_flow: GitBranch,
  inventory_selector: Router,
  persistent_artifact: FileArchive,
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
    mandatoryInputs: plugin.metadata.mandatory_input.map((field) => field.name),
    supportedOutputs: plugin.metadata.supported_output.map((field) => field.name),
    outcomes: plugin.metadata.outcomes.map((outcome) => outcome.name),
    icon: iconByArtifactType[plugin.artifact_type] ?? Code2,
  };
}

function groupPaletteItems(plugins: PluginDefinition[]): PaletteGroup[] {
  const groups = new Map<string, PaletteItem[]>();

  for (const plugin of plugins) {
    const items = groups.get(plugin.artifact_type) ?? [];
    items.push(toPaletteItem(plugin));
    groups.set(plugin.artifact_type, items);
  }

  return Array.from(groups.entries())
    .sort(([left], [right]) => left.localeCompare(right))
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
  const firstItem = paletteGroups[0]?.items[0];
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
        artifactType: item.artifactType,
        mandatoryInputs: item.mandatoryInputs,
        supportedOutputs: item.supportedOutputs,
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
        <div>
          <div className="mb-3 flex items-center justify-between rounded-lg bg-muted/40 px-3 py-2">
            <div>
              <p className="text-xs font-medium">Quick add</p>
              <p className="text-xs text-muted-foreground">
                Add the first workflow step
              </p>
            </div>
            {firstItem ? (
              <Button
                aria-label="Add workflow step"
                onClick={() => addStep(firstItem)}
                size="icon"
                variant="outline"
              >
                <Plus className="size-4" />
              </Button>
            ) : null}
          </div>
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
          ) : (
            <div className="max-h-[60vh] space-y-2 overflow-y-auto pr-1">
              {paletteGroups.map((group) => (
                <details
                  className="rounded-lg border bg-background/60"
                  key={group.artifactType}
                  open
                >
                  <summary className="cursor-pointer select-none px-3 py-2 text-xs font-semibold text-muted-foreground">
                    {group.label}
                  </summary>
                  <div className="space-y-1 px-1 pb-1">
                    {group.items.map((item) => (
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
                </details>
              ))}
            </div>
          )}
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
