import type { ComponentType } from "react";
import type { LucideIcon } from "lucide-react";

export type WidgetId = "schedules" | "recent-runs" | "notifications";

export interface WidgetDefaultSize {
  w: number;
  h: number;
  minW: number;
  minH: number;
}

export interface WidgetDefinition {
  id: WidgetId;
  title: string;
  description: string;
  icon: LucideIcon;
  defaultSize: WidgetDefaultSize;
  component: ComponentType;
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
}

export type DashboardBreakpoint = keyof DashboardLayoutDoc["layouts"];
