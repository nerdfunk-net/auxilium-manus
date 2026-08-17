"use client";

import { useState } from "react";
import { Responsive, WidthProvider } from "react-grid-layout/legacy";
import type { Layout, ResponsiveLayouts } from "react-grid-layout/legacy";

import "react-grid-layout/css/styles.css";

import { WIDGET_REGISTRY } from "@/components/features/dashboard/registry/widget-registry";
import { WidgetShell } from "@/components/features/dashboard/components/widget-shell";
import type {
  DashboardBreakpoint,
  DashboardLayoutDoc,
  WidgetId,
} from "@/components/features/dashboard/types/dashboard";

const ResponsiveGridLayout = WidthProvider(Responsive);

const BREAKPOINTS = { lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 };
const COLS = { lg: 10, md: 8, sm: 6, xs: 4, xxs: 2 };

function toResponsiveLayouts(doc: DashboardLayoutDoc): ResponsiveLayouts {
  const layouts: ResponsiveLayouts = {};
  for (const breakpoint of Object.keys(doc.layouts) as DashboardBreakpoint[]) {
    const items = doc.layouts[breakpoint];
    if (items) {
      layouts[breakpoint] = items;
    }
  }
  return layouts;
}

interface DashboardGridProps {
  layout: DashboardLayoutDoc;
  isEditing: boolean;
  onLayoutChange: (breakpoint: DashboardBreakpoint, items: Layout) => void;
  onRemoveWidget: (id: WidgetId) => void;
}

export function DashboardGrid({
  layout,
  isEditing,
  onLayoutChange,
  onRemoveWidget,
}: DashboardGridProps) {
  const [currentBreakpoint, setCurrentBreakpoint] = useState<DashboardBreakpoint>("lg");

  const activeIds = (layout.layouts.lg ?? layout.layouts.md ?? []).map(
    (item) => item.i as WidgetId,
  );

  return (
    <ResponsiveGridLayout
      breakpoints={BREAKPOINTS}
      cols={COLS}
      draggableHandle=".drag-handle"
      isDraggable={isEditing}
      isResizable={isEditing}
      layouts={toResponsiveLayouts(layout)}
      margin={[16, 16]}
      onBreakpointChange={(breakpoint) =>
        setCurrentBreakpoint(breakpoint as DashboardBreakpoint)
      }
      onLayoutChange={(currentLayout) => {
        onLayoutChange(currentBreakpoint, currentLayout);
      }}
      rowHeight={60}
    >
      {activeIds.map((id) => {
        const definition = WIDGET_REGISTRY[id];
        if (!definition) return null;
        return (
          <div key={id}>
            <WidgetShell
              definition={definition}
              isEditing={isEditing}
              onRemove={() => onRemoveWidget(id)}
            >
              <definition.component />
            </WidgetShell>
          </div>
        );
      })}
    </ResponsiveGridLayout>
  );
}
