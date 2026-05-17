"use client";

import {
  Boxes,
  FileArchive,
  Network,
  PlayCircle,
  Settings,
  Workflow,
} from "lucide-react";

import { cn } from "@/lib/utils";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";

type NavigationItem = {
  label: string;
  icon: typeof Workflow;
  kind: "workflows" | "artifacts" | "runs" | "placeholder";
};

const navigationItems = [
  { label: "Workflows", icon: Workflow, kind: "workflows" },
  { label: "Inventory", icon: Network, kind: "placeholder" },
  { label: "Runs", icon: PlayCircle, kind: "runs" },
  { label: "Artifacts", icon: FileArchive, kind: "artifacts" },
  { label: "Settings", icon: Settings, kind: "placeholder" },
] satisfies NavigationItem[];

export function WorkflowSidebar() {
  const mode = useWorkflowBuilderStore((state) => state.mode);
  const setMode = useWorkflowBuilderStore((state) => state.setMode);
  const isActionsPanelVisible = useWorkflowBuilderStore(
    (state) => state.isActionsPanelVisible,
  );
  const toggleActionsPanel = useWorkflowBuilderStore(
    (state) => state.toggleActionsPanel,
  );

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r bg-card">
      <div className="flex h-16 items-center gap-3 border-b px-5">
        <div className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <Boxes className="size-5" />
        </div>
        <div>
          <p className="text-sm font-semibold">Auxilium Manus</p>
          <p className="text-xs text-muted-foreground">NetDevOps builder</p>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-1 p-3">
        {navigationItems.map((item) => {
          const isActive =
            (item.kind === "workflows" && mode === "editor") ||
            (item.kind === "runs" && mode === "executions") ||
            (item.kind === "artifacts" && isActionsPanelVisible);
          const isPlaceholder = item.kind === "placeholder";
          const handleClick =
            item.kind === "artifacts"
              ? toggleActionsPanel
              : item.kind === "workflows"
                ? () => setMode("editor")
                : item.kind === "runs"
                  ? () => setMode("executions")
                  : undefined;

          return (
            <button
              aria-current={
                item.kind !== "artifacts" && isActive ? "page" : undefined
              }
              aria-pressed={
                item.kind === "artifacts" ? isActionsPanelVisible : undefined
              }
              disabled={isPlaceholder}
              key={item.label}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
                isActive && "bg-accent text-accent-foreground",
                isPlaceholder &&
                  "cursor-not-allowed opacity-60 hover:bg-transparent hover:text-muted-foreground",
              )}
              onClick={handleClick}
              type="button"
            >
              <item.icon className="size-4" />
              {item.label}
            </button>
          );
        })}
      </nav>

      <div className="border-t p-4">
        <p className="text-xs font-medium text-muted-foreground">
          MVP workspace
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Design first, execution later.
        </p>
      </div>
    </aside>
  );
}
