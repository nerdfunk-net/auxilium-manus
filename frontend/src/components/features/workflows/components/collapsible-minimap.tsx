"use client";

import { MiniMap, Panel } from "@xyflow/react";
import { ChevronDown, Map } from "lucide-react";

import { Button } from "@/components/ui/button";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";

export function CollapsibleMiniMap() {
  const isOpen = useWorkflowBuilderStore((state) => state.overviewPanelOpen);
  const setOverviewPanelOpen = useWorkflowBuilderStore(
    (state) => state.setOverviewPanelOpen,
  );

  return (
    <Panel className="!m-3 !p-0" position="bottom-right">
      {isOpen ? (
        <div className="overflow-hidden rounded-lg border bg-card shadow-md">
          <div className="flex items-center justify-between gap-2 border-b bg-muted/40 px-2 py-1">
            <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              Overview
            </span>
            <Button
              type="button"
              aria-label="Collapse canvas overview"
              variant="ghost"
              size="icon"
              className="size-6"
              onClick={() => setOverviewPanelOpen(false)}
            >
              <ChevronDown className="size-3.5" />
            </Button>
          </div>
          <MiniMap
            pannable
            zoomable
            className="!relative !inset-auto !m-0 !rounded-none !border-0 !shadow-none"
          />
        </div>
      ) : (
        <Button
          type="button"
          aria-label="Expand canvas overview"
          variant="secondary"
          size="sm"
          className="h-8 gap-1.5 px-2.5 text-xs shadow-md"
          onClick={() => setOverviewPanelOpen(true)}
        >
          <Map className="size-3.5" />
          Overview
        </Button>
      )}
    </Panel>
  );
}
