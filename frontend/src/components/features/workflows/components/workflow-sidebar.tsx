import {
  Boxes,
  FileArchive,
  Network,
  PlayCircle,
  Settings,
  Workflow,
} from "lucide-react";

import { cn } from "@/lib/utils";

const navigationItems = [
  { label: "Workflows", icon: Workflow, active: true },
  { label: "Inventory", icon: Network, active: false },
  { label: "Runs", icon: PlayCircle, active: false },
  { label: "Artifacts", icon: FileArchive, active: false },
  { label: "Settings", icon: Settings, active: false },
];

export function WorkflowSidebar() {
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
        {navigationItems.map((item) => (
          <button
            key={item.label}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
              item.active && "bg-accent text-accent-foreground",
            )}
            type="button"
          >
            <item.icon className="size-4" />
            {item.label}
          </button>
        ))}
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
