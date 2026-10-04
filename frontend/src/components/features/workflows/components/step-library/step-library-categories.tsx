"use client";

import { LayoutGrid } from "lucide-react";

import { cn } from "@/lib/utils";

import type { PaletteGroup } from "../../utils/step-catalog";
import { CATEGORY_TILE_FALLBACK, categoryTileClasses } from "../../utils/step-visuals";
import { ALL_CATEGORY_KEY } from "../../utils/step-library-filter";

interface StepLibraryCategoriesProps {
  groups: PaletteGroup[];
  selectedKey: string;
  onSelect: (categoryKey: string) => void;
}

function CategoryButton({
  count,
  isSelected,
  label,
  onSelect,
  tile,
}: {
  count: number;
  isSelected: boolean;
  label: string;
  onSelect: () => void;
  tile: React.ReactNode;
}) {
  return (
    <button
      aria-current={isSelected ? "true" : undefined}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-lg p-2 text-left text-[13px] transition-colors",
        isSelected ? "bg-accent font-semibold" : "hover:bg-accent/40",
      )}
      onClick={onSelect}
      type="button"
    >
      {tile}
      <span className="flex-1 truncate">{label}</span>
      <span className="rounded-full bg-muted px-2 text-[11px] text-muted-foreground">{count}</span>
    </button>
  );
}

export function StepLibraryCategories({ groups, selectedKey, onSelect }: StepLibraryCategoriesProps) {
  const total = groups.reduce((sum, group) => sum + group.items.length, 0);
  return (
    <nav aria-label="Step categories" className="flex min-h-0 flex-col gap-0.5 overflow-y-auto border-r p-2">
      <CategoryButton
        count={total}
        isSelected={selectedKey === ALL_CATEGORY_KEY}
        label="All"
        onSelect={() => onSelect(ALL_CATEGORY_KEY)}
        tile={
          <span className="flex size-[26px] shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
            <LayoutGrid className="size-3.5" aria-hidden />
          </span>
        }
      />
      {groups.map((group) => {
        const Icon = group.items[0]?.icon;
        return (
          <CategoryButton
            count={group.items.length}
            isSelected={selectedKey === group.categoryKey}
            key={group.categoryKey}
            label={group.label}
            onSelect={() => onSelect(group.categoryKey)}
            tile={
              <span
                className={cn(
                  "flex size-[26px] shrink-0 items-center justify-center rounded-md",
                  categoryTileClasses[group.categoryKey] ?? CATEGORY_TILE_FALLBACK,
                )}
              >
                {Icon ? <Icon className="size-3.5" aria-hidden /> : null}
              </span>
            }
          />
        );
      })}
    </nav>
  );
}
