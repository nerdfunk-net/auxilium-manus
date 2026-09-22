import type { ComponentType } from "react";
import type { LucideIcon } from "lucide-react";

export type WidgetId = "schedules" | "recent-runs" | "notifications" | "job-statistics";

export interface WidgetDefaultSize {
  w: number;
  h: number;
  minW: number;
  minH: number;
}

export type WidgetSettings = Record<string, unknown>;

export interface WidgetComponentProps {
  settings?: WidgetSettings;
  onSettingsChange?: (patch: WidgetSettings) => void;
}

export interface WidgetDefinition {
  id: WidgetId;
  title: string;
  description: string;
  icon: LucideIcon;
  defaultSize: WidgetDefaultSize;
  component: ComponentType<WidgetComponentProps>;
}

export interface DashboardLayoutItem {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  minW?: number;
  minH?: number;
}

export interface DashboardLayoutDoc {
  version: 1;
  layouts: {
    lg?: DashboardLayoutItem[];
    md?: DashboardLayoutItem[];
    sm?: DashboardLayoutItem[];
    xs?: DashboardLayoutItem[];
    xxs?: DashboardLayoutItem[];
  };
  // Per-widget-instance settings (custom title, widget-specific config like a
  // selected job) — keyed by WidgetId, opaque per-widget shape. Independent of
  // grid geometry so it never needs per-breakpoint duplication. Stored as part
  // of the same opaque `dashboard_layout` JSONB blob the backend already owns.
  widgetSettings?: Partial<Record<WidgetId, WidgetSettings>>;
}

export type DashboardBreakpoint = keyof DashboardLayoutDoc["layouts"];
