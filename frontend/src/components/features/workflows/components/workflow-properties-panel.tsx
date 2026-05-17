"use client";

import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ChevronsRight,
  GitBranch,
  PanelRightOpen,
  Settings2,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import type {
  PluginDefinition,
  PluginIOField,
  PluginOutcome,
} from "../types/plugin-registry";
import type { WorkflowCanvasNode } from "../types/workflow-canvas";

const EMPTY_PLUGINS: PluginDefinition[] = [];

interface WorkflowPropertiesPanelProps {
  nodes: WorkflowCanvasNode[];
  plugins?: PluginDefinition[];
}

function formatArtifactType(artifactType: string) {
  return artifactType
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function SectionHeader({
  icon: Icon,
  label,
}: {
  icon: LucideIcon;
  label: string;
}) {
  return (
    <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
      <Icon className="size-3.5" />
      {label}
    </div>
  );
}

function FieldRow({ field }: { field: PluginIOField }) {
  return (
    <div className="rounded-lg border bg-background/60 px-3 py-2">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">{field.name}</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          {field.data_type}
        </Badge>
        {field.required && (
          <span className="ml-auto text-[10px] text-destructive">required</span>
        )}
      </div>
      {field.description ? (
        <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
          {field.description}
        </p>
      ) : null}
    </div>
  );
}

function OutcomeRow({ outcome }: { outcome: PluginOutcome }) {
  return (
    <div className="rounded-lg border bg-background/60 px-3 py-2">
      <span className="font-mono text-xs font-medium">{outcome.name}</span>
      {outcome.description ? (
        <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
          {outcome.description}
        </p>
      ) : null}
    </div>
  );
}

export function WorkflowPropertiesPanel({
  nodes,
  plugins = EMPTY_PLUGINS,
}: WorkflowPropertiesPanelProps) {
  const selectedNodeId = useWorkflowBuilderStore(
    (state) => state.selectedNodeId,
  );
  const [isMinimized, setIsMinimized] = useState(false);

  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selectedNodeId),
    [nodes, selectedNodeId],
  );

  const plugin = useMemo(
    () => plugins.find((p) => p.id === selectedNode?.data.kind),
    [plugins, selectedNode],
  );

  if (isMinimized) {
    return (
      <aside className="flex w-8 shrink-0 flex-col items-center border-l bg-card pt-3">
        <Button
          aria-label="Expand step properties"
          onClick={() => setIsMinimized(false)}
          size="icon"
          variant="ghost"
        >
          <PanelRightOpen className="size-4" />
        </Button>
      </aside>
    );
  }

  return (
    <aside className="flex w-80 shrink-0 flex-col border-l bg-card">
      <div className="flex items-center justify-between border-b p-4">
        <div>
          <p className="text-sm font-semibold">Step properties</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Configure the selected workflow step.
          </p>
        </div>
        <Button
          aria-label="Minimize step properties"
          onClick={() => setIsMinimized(true)}
          size="icon"
          variant="ghost"
        >
          <ChevronsRight className="size-4" />
        </Button>
      </div>

      {selectedNode ? (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <div className="mb-4">
              {selectedNode.data.artifactType ? (
                <Badge className="mb-2" variant="secondary">
                  {formatArtifactType(selectedNode.data.artifactType)}
                </Badge>
              ) : null}
              <h2 className="text-base font-semibold">
                {selectedNode.data.title}
              </h2>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {selectedNode.data.description}
              </p>
            </div>

            {plugin ? (
              <div className="space-y-4">
                {plugin.metadata.configuration_input.length > 0 ? (
                  <div className="space-y-1.5">
                    <SectionHeader
                      icon={Settings2}
                      label="Configuration inputs"
                    />
                    {plugin.metadata.configuration_input.map((field) => (
                      <FieldRow field={field} key={field.name} />
                    ))}
                  </div>
                ) : null}

                {plugin.metadata.mandatory_input.length > 0 ? (
                  <div className="space-y-1.5">
                    <SectionHeader
                      icon={ArrowDownToLine}
                      label="Mandatory inputs"
                    />
                    {plugin.metadata.mandatory_input.map((field) => (
                      <FieldRow field={field} key={field.name} />
                    ))}
                  </div>
                ) : null}

                {plugin.metadata.supported_output.length > 0 ? (
                  <div className="space-y-1.5">
                    <SectionHeader icon={ArrowUpFromLine} label="Outputs" />
                    {plugin.metadata.supported_output.map((field) => (
                      <FieldRow field={field} key={field.name} />
                    ))}
                  </div>
                ) : null}

                {plugin.metadata.outcomes.length > 0 ? (
                  <div className="space-y-1.5">
                    <SectionHeader icon={GitBranch} label="Outcomes" />
                    {plugin.metadata.outcomes.map((outcome) => (
                      <OutcomeRow key={outcome.name} outcome={outcome} />
                    ))}
                  </div>
                ) : null}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Plugin metadata not available.
              </p>
            )}
          </div>

          <div className="border-t p-4">
            <Button className="w-full" variant="outline">
              Open full configuration
            </Button>
          </div>
        </>
      ) : (
        <div className="p-5 text-sm text-muted-foreground">
          Select a node on the canvas to inspect its metadata, content
          settings, and execution role.
        </div>
      )}
    </aside>
  );
}
