"use client";

import { ChevronDown, Plus, Search } from "lucide-react";
import { useMemo, useState, type DragEvent } from "react";

import { cn } from "@/lib/utils";

import type { PluginDefinition } from "../types/plugin-registry";
import type { StepPayload } from "../types/workflow-canvas";
import {
  CATEGORY_TILE_FALLBACK,
  categoryTileClasses,
} from "../utils/step-visuals";
import {
  groupPaletteItems,
  STEP_DRAG_MIME_TYPE,
  type PaletteGroup,
  type PaletteItem,
} from "../utils/step-catalog";

interface StepCatalogProps {
  errorMessage?: string;
  isLoading: boolean;
  onAddStep: (step: StepPayload) => void;
  plugins: PluginDefinition[];
}

function CategoryHeader({
  group,
  isOpen,
  onToggle,
}: {
  group: PaletteGroup;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const Icon = group.items[0]?.icon;
  return (
    <button
      aria-expanded={isOpen}
      className="flex w-full items-center gap-2.5 rounded-lg p-2 text-left transition-colors hover:bg-accent/40"
      onClick={onToggle}
      type="button"
    >
      <span
        className={cn(
          "flex size-[26px] shrink-0 items-center justify-center rounded-md",
          categoryTileClasses[group.artifactType] ?? CATEGORY_TILE_FALLBACK,
        )}
      >
        {Icon ? <Icon className="size-3.5" aria-hidden /> : null}
      </span>
      <span className="flex-1 text-[13px] font-semibold">{group.label}</span>
      <span className="rounded-full bg-muted px-2 text-[11px] text-muted-foreground">
        {group.items.length}
      </span>
      <ChevronDown
        className={cn(
          "size-3.5 shrink-0 text-muted-foreground transition-transform duration-150",
          !isOpen && "-rotate-90",
        )}
      />
    </button>
  );
}

function StepRow({
  item,
  onAddStep,
}: {
  item: PaletteItem;
  onAddStep: (step: StepPayload) => void;
}) {
  const Icon = item.icon;

  const handleDragStart = (event: DragEvent<HTMLDivElement>) => {
    event.dataTransfer.setData(STEP_DRAG_MIME_TYPE, item.kind);
    event.dataTransfer.effectAllowed = "copy";
  };

  return (
    <div
      className={cn(
        "group flex cursor-grab items-start gap-[11px] rounded-[10px] border bg-card p-[9px_10px] transition-colors",
        "hover:border-sky-200 hover:bg-sky-50/60 hover:shadow-[0_2px_8px_rgba(56,189,248,0.14)]",
      )}
      draggable
      onClick={() => onAddStep(item)}
      onDragStart={handleDragStart}
      role="button"
      tabIndex={0}
    >
      <span
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-lg",
          categoryTileClasses[item.artifactType] ?? CATEGORY_TILE_FALLBACK,
        )}
      >
        <Icon className="size-4" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[12.5px] font-semibold leading-tight">{item.title}</span>
        <span className="mt-0.5 line-clamp-2 block text-[11px] leading-[1.35] text-muted-foreground">
          {item.description}
        </span>
      </span>
      <Plus className="mt-0.5 size-3.5 shrink-0 text-border" aria-hidden />
    </div>
  );
}

export function StepCatalog({ errorMessage, isLoading, onAddStep, plugins }: StepCatalogProps) {
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const groups = useMemo(() => groupPaletteItems(plugins), [plugins]);
  const query = search.trim().toLowerCase();

  const visibleGroups = useMemo(() => {
    if (!query) return groups;
    return groups
      .map((group) => ({
        ...group,
        items: group.items.filter(
          (item) =>
            item.title.toLowerCase().includes(query) ||
            item.description.toLowerCase().includes(query) ||
            item.kind.toLowerCase().includes(query),
        ),
      }))
      .filter((group) => group.items.length > 0);
  }, [groups, query]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 border-b p-[12px_14px]">
        <div className="flex items-center gap-[9px] rounded-[10px] border bg-muted/60 px-3 py-[9px]">
          <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <input
            className="w-full border-none bg-transparent text-[13px] text-foreground outline-none placeholder:text-muted-foreground"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search steps…"
            value={search}
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-[8px_10px_24px]">
        {isLoading ? (
          <p className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
            Loading plugins...
          </p>
        ) : errorMessage ? (
          <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-4 text-sm text-destructive">
            {errorMessage}
          </p>
        ) : visibleGroups.length === 0 ? (
          <p className="px-2 py-8 text-center text-[13px] text-muted-foreground">
            {query ? `No steps match "${search}".` : "No plugins are available."}
          </p>
        ) : (
          visibleGroups.map((group) => {
            const isOpen = query ? true : !collapsed[group.artifactType];
            return (
              <div className="mb-1.5" key={group.artifactType}>
                <CategoryHeader
                  group={group}
                  isOpen={isOpen}
                  onToggle={() =>
                    setCollapsed((current) => ({
                      ...current,
                      [group.artifactType]: !current[group.artifactType],
                    }))
                  }
                />
                {isOpen ? (
                  <div className="flex flex-col gap-1 p-[2px_2px_6px_4px]">
                    {group.items.map((item) => (
                      <StepRow item={item} key={item.kind} onAddStep={onAddStep} />
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
