"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Layout } from "react-grid-layout/legacy";

import { DashboardGrid } from "@/components/features/dashboard/components/dashboard-grid";
import { DashboardToolbar } from "@/components/features/dashboard/components/dashboard-toolbar";
import { AddWidgetDialog } from "@/components/features/dashboard/dialogs/add-widget-dialog";
import { WIDGET_REGISTRY } from "@/components/features/dashboard/registry/widget-registry";
import { DEFAULT_LAYOUT } from "@/components/features/dashboard/constants/default-layout";
import type {
  DashboardBreakpoint,
  DashboardLayoutDoc,
  DashboardLayoutItem,
  WidgetId,
} from "@/components/features/dashboard/types/dashboard";
import { useDashboardLayoutMutations } from "@/hooks/queries/use-dashboard-layout-mutations";
import { useDashboardLayoutQuery } from "@/hooks/queries/use-dashboard-layout-query";
import { queryKeys } from "@/lib/query-keys";

const ALL_BREAKPOINTS: DashboardBreakpoint[] = ["lg", "md", "sm", "xs", "xxs"];

function removeWidgetFromLayout(doc: DashboardLayoutDoc, id: WidgetId): DashboardLayoutDoc {
  const layouts = { ...doc.layouts };
  for (const breakpoint of ALL_BREAKPOINTS) {
    const items = layouts[breakpoint];
    if (items) {
      layouts[breakpoint] = items.filter((item) => item.i !== id);
    }
  }
  return { ...doc, layouts };
}

function addWidgetToLayout(doc: DashboardLayoutDoc, id: WidgetId): DashboardLayoutDoc {
  const definition = WIDGET_REGISTRY[id];
  const layouts = { ...doc.layouts };
  for (const breakpoint of ALL_BREAKPOINTS) {
    const items = layouts[breakpoint] ?? [];
    layouts[breakpoint] = [
      ...items,
      { i: id, x: 0, y: Infinity, ...definition.defaultSize },
    ];
  }
  return { ...doc, layouts };
}

function activeWidgetIdsOf(doc: DashboardLayoutDoc): Set<WidgetId> {
  return new Set((doc.layouts.lg ?? doc.layouts.md ?? []).map((item) => item.i as WidgetId));
}

export function DashboardPage() {
  const { data, isLoading } = useDashboardLayoutQuery();
  const { saveLayout } = useDashboardLayoutMutations();
  const queryClient = useQueryClient();

  const savedLayout = data?.layout ?? DEFAULT_LAYOUT;

  const [draftLayout, setDraftLayout] = useState<DashboardLayoutDoc | null>(null);
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false);

  const isEditing = draftLayout !== null;
  const displayedLayout = draftLayout ?? savedLayout;
  const activeWidgetIds = activeWidgetIdsOf(displayedLayout);

  const handleToggleEditing = () => {
    if (isEditing && draftLayout) {
      saveLayout.mutate({ layout: draftLayout });
      setDraftLayout(null);
    } else {
      setDraftLayout(savedLayout);
    }
  };

  const handleLayoutChange = (breakpoint: DashboardBreakpoint, items: Layout) => {
    if (!isEditing) return;
    const normalized: DashboardLayoutItem[] = items.map((item) => ({
      i: item.i,
      x: item.x,
      y: item.y,
      w: item.w,
      h: item.h,
      minW: item.minW,
      minH: item.minH,
    }));
    setDraftLayout((current) =>
      current
        ? { ...current, layouts: { ...current.layouts, [breakpoint]: normalized } }
        : current,
    );
  };

  const handleRemoveWidget = (id: WidgetId) => {
    setDraftLayout((current) => (current ? removeWidgetFromLayout(current, id) : current));
  };

  const handleAddWidget = (id: WidgetId) => {
    setDraftLayout((current) => (current ? addWidgetToLayout(current, id) : current));
  };

  const handleReset = () => {
    setDraftLayout(DEFAULT_LAYOUT);
  };

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.schedules() });
    queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.recentRuns() });
  };

  if (isLoading) {
    return null;
  }

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-6">
      <DashboardToolbar
        addDisabled={activeWidgetIds.size >= Object.keys(WIDGET_REGISTRY).length}
        isEditing={isEditing}
        onAddCard={() => setIsAddDialogOpen(true)}
        onRefresh={handleRefresh}
        onReset={handleReset}
        onToggleEditing={handleToggleEditing}
      />
      <DashboardGrid
        isEditing={isEditing}
        layout={displayedLayout}
        onLayoutChange={handleLayoutChange}
        onRemoveWidget={handleRemoveWidget}
      />
      <AddWidgetDialog
        activeWidgetIds={activeWidgetIds}
        onAdd={handleAddWidget}
        onOpenChange={setIsAddDialogOpen}
        open={isAddDialogOpen}
      />
    </div>
  );
}
