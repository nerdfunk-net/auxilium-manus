"use client";

import { Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import type { PaletteItem } from "../../utils/step-catalog";
import { CATEGORY_TILE_FALLBACK, categoryTileClasses } from "../../utils/step-visuals";

interface StepLibraryGridProps {
  emptyMessage: string;
  errorMessage?: string;
  isLoading: boolean;
  items: PaletteItem[];
  onActivate: (item: PaletteItem) => void;
  onSearchChange: (value: string) => void;
  onSelect: (item: PaletteItem) => void;
  search: string;
  selectedKind: string | null;
}

function StepTile({
  isSelected,
  item,
  onActivate,
  onSelect,
}: {
  isSelected: boolean;
  item: PaletteItem;
  onActivate: (item: PaletteItem) => void;
  onSelect: (item: PaletteItem) => void;
}) {
  const Icon = item.icon;
  return (
    <button
      aria-pressed={isSelected}
      className={cn(
        "flex flex-col items-center gap-2 rounded-xl border bg-card p-3 text-center transition-colors",
        "hover:border-info-border hover:bg-info/60",
        isSelected && "border-ring bg-accent ring-2 ring-ring",
      )}
      onClick={() => onSelect(item)}
      onDoubleClick={() => onActivate(item)}
      type="button"
    >
      <span
        className={cn(
          "flex size-12 items-center justify-center rounded-xl",
          categoryTileClasses[item.paletteCategory] ?? CATEGORY_TILE_FALLBACK,
        )}
      >
        <Icon className="size-6" aria-hidden />
      </span>
      <span className="line-clamp-2 text-[11.5px] font-medium leading-tight">{item.title}</span>
    </button>
  );
}

export function StepLibraryGrid({
  emptyMessage,
  errorMessage,
  isLoading,
  items,
  onActivate,
  onSearchChange,
  onSelect,
  search,
  selectedKind,
}: StepLibraryGridProps) {
  return (
    <div className="flex min-h-0 flex-col">
      <div className="shrink-0 border-b p-3">
        <div className="flex items-center gap-2 rounded-[10px] border bg-muted/60 px-3 py-2">
          <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <Input
            aria-label="Search steps"
            className="h-auto border-none bg-transparent p-0 text-[13px] shadow-none focus-visible:ring-0"
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search steps…"
            value={search}
          />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {isLoading ? (
          <p className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
            Loading plugins...
          </p>
        ) : errorMessage ? (
          <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-4 text-sm text-destructive">
            {errorMessage}
          </p>
        ) : items.length === 0 ? (
          <p className="px-2 py-8 text-center text-[13px] text-muted-foreground">{emptyMessage}</p>
        ) : (
          <div
            aria-label="Steps"
            className="grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] gap-2"
            role="group"
          >
            {items.map((item) => (
              <StepTile
                isSelected={item.kind === selectedKind}
                item={item}
                key={item.kind}
                onActivate={onActivate}
                onSelect={onSelect}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
