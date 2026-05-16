"use client";

import {
  FileArchive,
  GitBranch,
  Network,
  Plus,
  Router,
  TerminalSquare,
} from "lucide-react";

import { Button } from "@/components/ui/button";

import type { WorkflowNodeKind } from "../types/workflow-canvas";

type PaletteItem = {
  kind: WorkflowNodeKind;
  label: string;
  description: string;
  icon: typeof Router;
};

const paletteItems: PaletteItem[] = [
  {
    kind: "device-selection",
    label: "Device Selection",
    description: "Choose target devices from inventory.",
    icon: Router,
  },
  {
    kind: "ssh-login",
    label: "SSH Login",
    description: "Open a managed CLI session.",
    icon: Network,
  },
  {
    kind: "run-command",
    label: "Run Command",
    description: "Execute a command against each device.",
    icon: TerminalSquare,
  },
  {
    kind: "condition",
    label: "Condition",
    description: "Branch based on metadata or content.",
    icon: GitBranch,
  },
  {
    kind: "store-artifact",
    label: "Store Artifact",
    description: "Persist generated content.",
    icon: FileArchive,
  },
];

interface NodePaletteProps {
  onAddStep: (step: {
    kind: WorkflowNodeKind;
    title: string;
    description: string;
  }) => void;
}

export function NodePalette({ onAddStep }: NodePaletteProps) {
  const firstItem = paletteItems[0];

  const addStep = (item: PaletteItem) => {
    onAddStep({
      kind: item.kind,
      title: item.label,
      description: item.description,
    });
  };

  return (
    <div className="absolute right-5 top-5 z-10 w-64 rounded-xl border bg-card p-3 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold">Add step</p>
          <p className="text-xs text-muted-foreground">
            Workflow building blocks
          </p>
        </div>
        <Button
          aria-label="Add workflow step"
          onClick={() => addStep(firstItem)}
          size="icon"
          variant="outline"
        >
          <Plus className="size-4" />
        </Button>
      </div>
      <div className="space-y-1">
        {paletteItems.map((item) => (
          <button
            key={item.label}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
            onClick={() => addStep(item)}
            type="button"
          >
            <item.icon className="size-4 text-muted-foreground" />
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}
