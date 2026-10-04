"use client";

import { useMemo } from "react";

import { HelpUnavailable } from "@/components/features/workflow-steps/shared/step-help";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getPluginUI } from "@/lib/plugin-ui-registry";
import { cn } from "@/lib/utils";

import { PluginDetails } from "../components/node-config-description-tab";
import type { PluginDefinition } from "../types/plugin-registry";
import type { PaletteItem } from "../utils/step-catalog";
import {
  CATEGORY_TILE_FALLBACK,
  categoryTileClasses,
  formatPaletteCategory,
} from "../utils/step-visuals";

// Help panels are written for a configured canvas node; before a step exists
// they render against an empty config and no sibling steps.
const EMPTY_CONFIG: Record<string, unknown> = {};
const NO_OP = () => undefined;
const TAB_TRIGGER_CLASS = "px-4";
const TAB_CONTENT_CLASS = "mt-0 min-h-0 flex-1 overflow-y-auto p-5";

interface StepDetailsDialogProps {
  item: PaletteItem | null;
  onOpenChange: (open: boolean) => void;
  plugin: PluginDefinition | undefined;
}

/** Description and Help of one step, opened from the Steps library. */
export function StepDetailsDialog({ item, onOpenChange, plugin }: StepDetailsDialogProps) {
  const Icon = item?.icon;
  const HelpPanel = useMemo(() => (item ? getPluginUI(item.kind)?.HelpPanel : undefined), [item]);

  return (
    <Dialog onOpenChange={onOpenChange} open={item !== null}>
      <DialogContent className="flex h-[75vh] flex-col gap-0 p-0 sm:max-w-2xl">
        {item && Icon ? (
          <>
            <div className="flex shrink-0 items-start gap-3 border-b px-5 py-4 pr-12">
              <span
                className={cn(
                  "flex size-10 shrink-0 items-center justify-center rounded-lg",
                  categoryTileClasses[item.paletteCategory] ?? CATEGORY_TILE_FALLBACK,
                )}
              >
                <Icon className="size-5" aria-hidden />
              </span>
              <div className="min-w-0">
                <DialogTitle>{item.title}</DialogTitle>
                <DialogDescription className="text-xs">
                  {formatPaletteCategory(item.paletteCategory)}
                </DialogDescription>
              </div>
            </div>
            <Tabs className="flex min-h-0 flex-1 flex-col gap-0" defaultValue="description">
              <TabsList className="mx-5 mt-3 shrink-0 self-start">
                <TabsTrigger className={TAB_TRIGGER_CLASS} value="description">
                  Description
                </TabsTrigger>
                <TabsTrigger className={TAB_TRIGGER_CLASS} value="help">
                  Help
                </TabsTrigger>
              </TabsList>
              <TabsContent className={TAB_CONTENT_CLASS} value="description">
                <div className="space-y-4">
                  <p className="whitespace-pre-line text-[13px] leading-5 text-muted-foreground">
                    {item.description || item.overview}
                  </p>
                  <PluginDetails plugin={plugin} />
                </div>
              </TabsContent>
              <TabsContent className={TAB_CONTENT_CLASS} value="help">
                {HelpPanel ? (
                  <HelpPanel
                    config={EMPTY_CONFIG}
                    nodeId={item.kind}
                    onChange={NO_OP}
                    onPreview={NO_OP}
                  />
                ) : (
                  <HelpUnavailable />
                )}
              </TabsContent>
            </Tabs>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
