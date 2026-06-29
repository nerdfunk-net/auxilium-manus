"use client";

import {
  ArrowDownToLine,
  ChevronsRight,
  GitBranch,
  MoveRight,
  Settings2,
  type LucideIcon,
} from "lucide-react";
import { useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import type { WorkflowCanvasNode } from "../types/workflow-canvas";

const EMPTY_PLUGINS: PluginDefinition[] = [];
const EMPTY_NODES: WorkflowCanvasNode[] = [];

interface NodeConfigModalProps {
  nodes: WorkflowCanvasNode[];
  plugins?: PluginDefinition[];
  onNodeConfigChange?: (nodeId: string, config: Record<string, unknown>) => void;
  onNodeTitleChange?: (nodeId: string, title: string) => void;
  workflowNodes?: WorkflowCanvasNode[];
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

export function NodeConfigModal({
  nodes,
  plugins = EMPTY_PLUGINS,
  onNodeConfigChange,
  onNodeTitleChange,
  workflowNodes = EMPTY_NODES,
}: NodeConfigModalProps) {
  const configModalNodeId = useWorkflowBuilderStore(
    (state) => state.configModalNodeId,
  );
  const closeConfigModal = useWorkflowBuilderStore(
    (state) => state.closeConfigModal,
  );

  const activeNode = useMemo(
    () => (configModalNodeId ? nodes.find((n) => n.id === configModalNodeId) ?? null : null),
    [nodes, configModalNodeId],
  );

  const plugin = useMemo(
    () => plugins.find((p) => p.id === activeNode?.data.kind),
    [plugins, activeNode],
  );

  const pluginUI = useMemo(
    () => (plugin ? getPluginUI(plugin.id) : undefined),
    [plugin],
  );

  const hasConfigTab =
    !!pluginUI || (plugin?.metadata.configuration_input.length ?? 0) > 0;

  return (
    <Dialog open={configModalNodeId !== null} onOpenChange={(open) => { if (!open) closeConfigModal(); }}>
      <DialogContent className="flex h-[75vh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="shrink-0 border-b border-sky-200 bg-accent px-6 py-4">
          <DialogTitle className="text-base text-accent-foreground">
            {activeNode?.data.title ?? "Step configuration"}
          </DialogTitle>
          {plugin ? (
            <p className="mt-0.5 font-mono text-xs text-accent-foreground/60">
              {plugin.name} ({plugin.id})
            </p>
          ) : null}
        </DialogHeader>

        {activeNode ? (
          <Tabs className="flex min-h-0 flex-1 flex-col" defaultValue="general">
            <TabsList className="h-9 w-full shrink-0 rounded-none border-b border-sky-200 bg-accent/20 p-0">
              <TabsTrigger
                className="h-9 rounded-none border-b-2 border-transparent px-5 text-xs text-muted-foreground hover:text-accent-foreground data-[state=active]:border-accent-foreground data-[state=active]:bg-accent/30 data-[state=active]:font-medium data-[state=active]:text-accent-foreground data-[state=active]:shadow-none"
                value="general"
              >
                General
              </TabsTrigger>
              {hasConfigTab ? (
                <TabsTrigger
                  className="h-9 rounded-none border-b-2 border-transparent px-5 text-xs text-muted-foreground hover:text-accent-foreground data-[state=active]:border-accent-foreground data-[state=active]:bg-accent/30 data-[state=active]:font-medium data-[state=active]:text-accent-foreground data-[state=active]:shadow-none"
                  value="configuration"
                >
                  Configuration
                </TabsTrigger>
              ) : null}
              <TabsTrigger
                className="h-9 rounded-none border-b-2 border-transparent px-5 text-xs text-muted-foreground hover:text-accent-foreground data-[state=active]:border-accent-foreground data-[state=active]:bg-accent/30 data-[state=active]:font-medium data-[state=active]:text-accent-foreground data-[state=active]:shadow-none"
                value="description"
              >
                Description
              </TabsTrigger>
            </TabsList>

            <TabsContent
              className="mt-0 min-h-0 flex-1 overflow-y-auto p-6"
              value="general"
            >
              <div className="max-w-sm space-y-1.5">
                <Label className="text-xs font-medium" htmlFor="modal-step-name">
                  Step name
                </Label>
                <Input
                  id="modal-step-name"
                  value={activeNode.data.title}
                  onChange={(event) =>
                    onNodeTitleChange?.(activeNode.id, event.target.value)
                  }
                  onBlur={(event) => {
                    const trimmed = event.target.value.trim();
                    const fallback = plugin?.name ?? activeNode.data.title;
                    if (!trimmed) {
                      onNodeTitleChange?.(activeNode.id, fallback);
                    } else if (trimmed !== event.target.value) {
                      onNodeTitleChange?.(activeNode.id, trimmed);
                    }
                  }}
                  placeholder={plugin?.name ?? "Step name"}
                  className="h-8 text-sm"
                />
                <p className="text-[11px] leading-4 text-muted-foreground">
                  Shown on the canvas and in run results.
                </p>
              </div>
            </TabsContent>

            {hasConfigTab ? (
              <TabsContent
                className="mt-0 min-h-0 flex-1 overflow-y-auto p-6"
                value="configuration"
              >
                {pluginUI ? (
                  <pluginUI.ConfigPanel
                    config={
                      (activeNode.data.pluginConfig ?? {}) as Record<string, unknown>
                    }
                    nodeId={activeNode.id}
                    workflowNodes={workflowNodes}
                    onChange={(config) =>
                      onNodeConfigChange?.(activeNode.id, config)
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
                ) : null}
              </TabsContent>
            ) : null}

            <TabsContent
              className="mt-0 min-h-0 flex-1 overflow-y-auto p-6"
              value="description"
            >
              <div className="space-y-4">
                {/* Group 1: Name */}
                <div>
                  {activeNode.data.artifactType ? (
                    <Badge className="mb-2" variant="secondary">
                      {formatArtifactType(activeNode.data.artifactType)}
                    </Badge>
                  ) : null}
                  <h2 className="text-base font-semibold">
                    {activeNode.data.title}
                  </h2>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    {activeNode.data.description}
                  </p>
                </div>

                {plugin ? (
                  <>
                    {/* Group 2: Capabilities (Produces, Consumes) */}
                    {(plugin.produces.length > 0 ||
                      plugin.produces_parsed.length > 0 ||
                      plugin.consumes.length > 0) ? (
                      <div className="space-y-3 rounded-lg border bg-muted/20 p-4">
                        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          Capabilities
                        </p>
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
                      </div>
                    ) : null}

                    {/* Group 3: Configuration inputs, Requires, Outcomes */}
                    {(plugin.metadata.configuration_input.length > 0 ||
                      plugin.requires.length > 0 ||
                      plugin.requires_parsed.length > 0 ||
                      plugin.outcomes.length > 0) ? (
                      <div className="space-y-4 rounded-lg border bg-muted/20 p-4">
                        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          Schema
                        </p>
                        {plugin.metadata.configuration_input.length > 0 ? (
                          <div className="space-y-1.5">
                            <SectionHeader icon={Settings2} label="Configuration inputs" />
                            {plugin.metadata.configuration_input.map((field) => (
                              <FieldRow field={field} key={field.name} />
                            ))}
                          </div>
                        ) : null}
                        {plugin.requires.length > 0 ? (
                          <CapabilityList
                            icon={ArrowDownToLine}
                            label="Requires"
                            values={plugin.requires}
                          />
                        ) : null}
                        {plugin.requires_parsed.length > 0 ? (
                          <CapabilityList
                            icon={ArrowDownToLine}
                            label="Requires parsed"
                            values={plugin.requires_parsed}
                          />
                        ) : null}
                        {plugin.outcomes.length > 0 ? (
                          <div className="space-y-1.5">
                            <SectionHeader icon={GitBranch} label="Outcomes" />
                            {plugin.outcomes.map((outcome) => (
                              <OutcomeRow key={outcome.name} outcome={outcome} />
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Plugin metadata not available.
                  </p>
                )}
              </div>
            </TabsContent>
          </Tabs>
        ) : null}

        <div className="shrink-0 border-t border-sky-100 bg-accent/10 px-6 py-3">
          <Button size="sm" variant="outline" onClick={closeConfigModal}>
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
