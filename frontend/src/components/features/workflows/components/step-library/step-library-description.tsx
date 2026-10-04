"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { PaletteItem } from "../../utils/step-catalog";
import { CATEGORY_TILE_FALLBACK, categoryTileClasses, formatPaletteCategory } from "../../utils/step-visuals";

interface StepLibraryDescriptionProps {
  item: PaletteItem | null;
  onAdd: () => void;
  onShowStep: () => void;
}

export function StepLibraryDescription({ item, onAdd, onShowStep }: StepLibraryDescriptionProps) {
  const Icon = item?.icon;
  return (
    <div className="flex items-start gap-4 border-t bg-muted/30 p-4">
      <div className="min-w-0 flex flex-1 items-start gap-3">
        {item && Icon ? (
          <>
            <span
              className={cn(
                "flex size-10 shrink-0 items-center justify-center rounded-lg",
                categoryTileClasses[item.paletteCategory] ?? CATEGORY_TILE_FALLBACK,
              )}
            >
              <Icon className="size-5" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-semibold">
                {item.title}
                <span className="ml-2 text-xs font-normal text-muted-foreground">
                  {formatPaletteCategory(item.paletteCategory)}
                </span>
              </p>
              <p className="mt-1 max-h-20 overflow-y-auto text-[12.5px] text-muted-foreground">
                {item.description || item.overview}
              </p>
            </div>
          </>
        ) : (
          <p className="text-[13px] text-muted-foreground">Select a step to see what it does.</p>
        )}
      </div>
      <div className="flex shrink-0 gap-2">
        <Button disabled={!item} onClick={onShowStep} type="button" variant="outline">
          Show step
        </Button>
        <Button disabled={!item} onClick={onAdd} type="button">
          Add
        </Button>
      </div>
    </div>
  );
}
