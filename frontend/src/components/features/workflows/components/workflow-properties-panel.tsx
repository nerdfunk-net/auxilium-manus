"use client";

import { Code2, Database, Info } from "lucide-react";
import { useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import type { WorkflowCanvasNode } from "../types/workflow-canvas";

interface WorkflowPropertiesPanelProps {
  nodes: WorkflowCanvasNode[];
}

export function WorkflowPropertiesPanel({ nodes }: WorkflowPropertiesPanelProps) {
  const selectedNodeId = useWorkflowBuilderStore((state) => state.selectedNodeId);
  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selectedNodeId),
    [nodes, selectedNodeId],
  );

  return (
    <aside className="w-80 shrink-0 border-l bg-card">
      <div className="border-b p-5">
        <p className="text-sm font-semibold">Step properties</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Configure the selected workflow step.
        </p>
      </div>

      {selectedNode ? (
        <div className="space-y-5 p-5">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <Badge variant="secondary">{selectedNode.data.kind}</Badge>
              {selectedNode.data.status ? (
                <Badge variant="outline">{selectedNode.data.status}</Badge>
              ) : null}
            </div>
            <h2 className="text-lg font-semibold">{selectedNode.data.title}</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              {selectedNode.data.description}
            </p>
          </div>

          <div className="rounded-xl border bg-muted/40 p-4">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Info className="size-4" />
              Metadata
            </div>
            <dl className="mt-3 space-y-2 text-xs text-muted-foreground">
              <div className="flex justify-between">
                <dt>Step ID</dt>
                <dd className="font-mono">{selectedNode.id}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Position</dt>
                <dd>
                  {Math.round(selectedNode.position.x)},{" "}
                  {Math.round(selectedNode.position.y)}
                </dd>
              </div>
            </dl>
          </div>

          {selectedNode.data.command ? (
            <div className="rounded-xl border bg-muted/40 p-4">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Code2 className="size-4" />
                Command
              </div>
              <code className="mt-3 block rounded-lg bg-background p-3 text-xs">
                {selectedNode.data.command}
              </code>
            </div>
          ) : null}

          {selectedNode.data.artifactPath ? (
            <div className="rounded-xl border bg-muted/40 p-4">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Database className="size-4" />
                Artifact target
              </div>
              <code className="mt-3 block rounded-lg bg-background p-3 text-xs">
                {selectedNode.data.artifactPath}
              </code>
            </div>
          ) : null}

          <Button className="w-full" variant="outline">
            Open full configuration
          </Button>
        </div>
      ) : (
        <div className="p-5 text-sm text-muted-foreground">
          Select a node on the canvas to inspect its metadata, content settings,
          and execution role.
        </div>
      )}
    </aside>
  );
}
