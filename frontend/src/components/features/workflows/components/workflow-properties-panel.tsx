"use client";

import {
  ArrowDownToLine,
  ChevronsRight,
  GitBranch,
  MoveRight,
  PanelRightOpen,
  Settings2,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { getPluginUI } from "@/lib/plugin-ui-registry";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import type {
  PluginDefinition,
  PluginIOField,
  PluginStepOutcome,
} from "../types/plugin-registry";
import type {
  EdgeStyle,
  WorkflowCanvasEdge,
  WorkflowCanvasNode,
} from "../types/workflow-canvas";

const EMPTY_PLUGINS: PluginDefinition[] = [];
const EMPTY_EDGES: WorkflowCanvasEdge[] = [];

interface WorkflowPropertiesPanelProps {
  nodes: WorkflowCanvasNode[];
  edges?: WorkflowCanvasEdge[];
  plugins?: PluginDefinition[];
  onEdgeStyleChange?: (edgeId: string, style: EdgeStyle) => void;
  onNodeConfigChange?: (nodeId: string, config: Record<string, unknown>) => void;
  onNodeTitleChange?: (nodeId: string, title: string) => void;
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

function OutcomeRow({ outcome }: { outcome: PluginStepOutcome }) {
  return (
    <div className="rounded-lg border bg-background/60 px-3 py-2">
      <span className="font-mono text-xs font-medium">{outcome.name}</span>
    </div>
  );
}

function CapabilityList({
  icon: Icon,
  label,
  values,
}: {
  icon: LucideIcon;
  label: string;
  values: string[];
}) {
  if (values.length === 0) {
    return null;
  }

  return (
    <div className="space-y-1.5">
      <SectionHeader icon={Icon} label={label} />
      <div className="flex flex-wrap gap-1.5">
        {values.map((value) => (
          <Badge key={value} className="font-mono text-[10px]" variant="secondary">
            {value}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function MockConfigRow({ field }: { field: PluginIOField }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">{field.name}</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          {field.data_type}
        </Badge>
        {field.required && (
          <span className="ml-auto text-[10px] text-destructive">required</span>
        )}
      </div>
      <div className="rounded border bg-muted/40 px-2 py-1.5 text-[11px] text-muted-foreground">
        {field.example != null
          ? String(field.example)
          : field.default != null
            ? String(field.default)
            : "—"}
      </div>
    </div>
  );
}

export function WorkflowPropertiesPanel({
  nodes,
  edges = EMPTY_EDGES,
  plugins = EMPTY_PLUGINS,
  onEdgeStyleChange,
  onNodeConfigChange,
  onNodeTitleChange,
}: WorkflowPropertiesPanelProps) {
  const selectedNodeId = useWorkflowBuilderStore(
    (state) => state.selectedNodeId,
  );
  const selectedEdgeId = useWorkflowBuilderStore(
    (state) => state.selectedEdgeId,
  );
  const [isMinimized, setIsMinimized] = useState(false);

  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selectedNodeId),
    [nodes, selectedNodeId],
  );

  const selectedEdge = useMemo(
    () => edges.find((e) => e.id === selectedEdgeId),
    [edges, selectedEdgeId],
  );

  const sourceNode = useMemo(
    () => nodes.find((n) => n.id === selectedEdge?.source),
    [nodes, selectedEdge],
  );

  const targetNode = useMemo(
    () => nodes.find((n) => n.id === selectedEdge?.target),
    [nodes, selectedEdge],
  );

  const plugin = useMemo(
    () => plugins.find((p) => p.id === selectedNode?.data.kind),
    [plugins, selectedNode],
  );

  const pluginUI = useMemo(
    () => (plugin ? getPluginUI(plugin.id) : undefined),
    [plugin],
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

      {selectedEdge ? (
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <div className="mb-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Connection
            </p>
            <h2 className="mt-1 flex items-center gap-1.5 text-base font-semibold">
              <span className="truncate">
                {sourceNode?.data.title ?? selectedEdge.source}
              </span>
              <MoveRight className="size-4 shrink-0 text-muted-foreground" />
              <span className="truncate">
                {targetNode?.data.title ?? selectedEdge.target}
              </span>
            </h2>
            {selectedEdge.label ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Label: <span className="font-medium">{String(selectedEdge.label)}</span>
              </p>
            ) : null}
          </div>

          <div className="space-y-3">
            <SectionHeader icon={Settings2} label="Edge style" />
            <div className="flex gap-2">
              <Button
                className="flex-1"
                onClick={() => onEdgeStyleChange?.(selectedEdge.id, "straight")}
                size="sm"
                variant={
                  (selectedEdge.data?.edgeStyle ?? "straight") === "straight"
                    ? "default"
                    : "outline"
                }
              >
                Straight
              </Button>
              <Button
                className="flex-1"
                onClick={() => onEdgeStyleChange?.(selectedEdge.id, "smooth")}
                size="sm"
                variant={
                  selectedEdge.data?.edgeStyle === "smooth" ? "default" : "outline"
                }
              >
                Smooth
              </Button>
            </div>
            <p className="text-[11px] leading-4 text-muted-foreground">
              {(selectedEdge.data?.edgeStyle ?? "straight") === "straight"
                ? "Polyline path with bend points. Double-click the line to add a bend point, drag to reposition, right-click to remove."
                : "Bezier curve managed automatically. Bend points are inactive in smooth mode."}
            </p>
          </div>
        </div>
      ) : selectedNode ? (
        <Tabs className="flex min-h-0 flex-1 flex-col" defaultValue="config">
          <TabsList className="h-7 w-full shrink-0 rounded-none border-b bg-transparent p-0">
            <TabsTrigger
              className="h-7 flex-1 rounded-none text-xs data-[state=active]:border-b-2 data-[state=active]:border-primary data-[state=active]:shadow-none"
              value="config"
            >
              Config
            </TabsTrigger>
            <TabsTrigger
              className="h-7 flex-1 rounded-none text-xs data-[state=active]:border-b-2 data-[state=active]:border-primary data-[state=active]:shadow-none"
              value="description"
            >
              Description
            </TabsTrigger>
          </TabsList>

          <TabsContent
            className="min-h-0 flex-1 overflow-y-auto p-4 mt-0"
            value="config"
          >
            <div className="mb-4 space-y-1.5 border-b pb-4">
              <Label className="text-xs font-medium" htmlFor="step-name">
                Step name
              </Label>
              <Input
                id="step-name"
                value={selectedNode.data.title}
                onChange={(event) =>
                  onNodeTitleChange?.(selectedNode.id, event.target.value)
                }
                onBlur={(event) => {
                  const trimmed = event.target.value.trim();
                  const fallback = plugin?.name ?? selectedNode.data.title;
                  if (!trimmed) {
                    onNodeTitleChange?.(selectedNode.id, fallback);
                  } else if (trimmed !== event.target.value) {
                    onNodeTitleChange?.(selectedNode.id, trimmed);
                  }
                }}
                placeholder={plugin?.name ?? "Step name"}
                className="h-8 text-sm"
              />
              <p className="text-[11px] leading-4 text-muted-foreground">
                Shown on the canvas and in run results.
                {plugin ? (
                  <>
                    {" "}
                    Plugin type: <span className="font-medium">{plugin.name}</span>
                    <span className="font-mono"> ({plugin.id})</span>
                  </>
                ) : null}
              </p>
            </div>

            {pluginUI && selectedNode ? (
              <pluginUI.ConfigPanel
                config={
                  (selectedNode.data.pluginConfig ?? {}) as Record<
                    string,
                    unknown
                  >
                }
                nodeId={selectedNode.id}
                onChange={(config) =>
                  onNodeConfigChange?.(selectedNode.id, config)
                }
                onPreview={() => undefined}
              />
            ) : plugin && plugin.metadata.configuration_input.length > 0 ? (
              <div className="space-y-3">
                <SectionHeader icon={Settings2} label="Configuration" />
                <div className="space-y-2">
                  {plugin.metadata.configuration_input.map((field) => (
                    <MockConfigRow field={field} key={field.name} />
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                No configuration fields defined for this step.
              </p>
            )}
          </TabsContent>

          <TabsContent
            className="min-h-0 flex-1 overflow-y-auto p-4 mt-0"
            value="description"
          >
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

                <CapabilityList
                  icon={ArrowDownToLine}
                  label="Requires"
                  values={plugin.requires}
                />
                {plugin.requires_parsed.length > 0 ? (
                  <CapabilityList
                    icon={ArrowDownToLine}
                    label="Requires parsed"
                    values={plugin.requires_parsed}
                  />
                ) : null}
                <CapabilityList
                  icon={MoveRight}
                  label="Produces"
                  values={plugin.produces}
                />
                {plugin.produces_parsed.length > 0 ? (
                  <CapabilityList
                    icon={MoveRight}
                    label="Produces parsed"
                    values={plugin.produces_parsed}
                  />
                ) : null}
                <CapabilityList
                  icon={ChevronsRight}
                  label="Consumes"
                  values={plugin.consumes}
                />

                {plugin.outcomes.length > 0 ? (
                  <div className="space-y-1.5">
                    <SectionHeader icon={GitBranch} label="Outcomes" />
                    {plugin.outcomes.map((outcome) => (
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
          </TabsContent>
        </Tabs>
      ) : (
        <div className="p-5 text-sm text-muted-foreground">
          Select a node or connection on the canvas to inspect its properties.
        </div>
      )}
    </aside>
  );
}
