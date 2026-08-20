"use client";

import { Settings2 } from "lucide-react";
import { useMemo } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { HelpUnavailable } from "@/components/features/workflow-steps/shared/step-help";
import { getPluginUI } from "@/lib/plugin-ui-registry";

import {
  MockConfigRow,
  NodeConfigDescriptionTab,
  SectionHeader,
} from "./node-config-description-tab";
import { NodeConfigGeneralTab } from "./node-config-general-tab";
import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import type { PluginDefinition } from "../types/plugin-registry";
import type {
  HandleSide,
  WorkflowCanvasEdge,
  PersistedCanvasNode,
} from "../types/workflow-canvas";

import {
  EMPTY_PLUGINS,
  EMPTY_WORKFLOW_EDGES as EMPTY_EDGES,
  EMPTY_WORKFLOW_NODES as EMPTY_NODES,
} from "../constants/empty-canvas";

const MODAL_TAB_TRIGGER_CLASS =
  "h-9 rounded-none border-b-2 border-transparent px-5 text-xs text-muted-foreground hover:text-foreground data-[state=active]:border-accent-foreground data-[state=active]:bg-background data-[state=active]:font-medium data-[state=active]:text-accent-foreground data-[state=active]:shadow-none";

const MODAL_TAB_CONTENT_CLASS = "mt-0 min-h-0 flex-1 overflow-y-auto p-6";

interface NodeConfigModalProps {
  nodes: PersistedCanvasNode[];
  edges?: WorkflowCanvasEdge[];
  plugins?: PluginDefinition[];
  onNodeConfigChange?: (nodeId: string, config: Record<string, unknown>) => void;
  onNodeTitleChange?: (nodeId: string, title: string) => void;
  onNodeIncomeHandleSideChange?: (nodeId: string, side: HandleSide) => void;
  onNodeOutcomeHandleSideChange?: (nodeId: string, side: HandleSide) => void;
  workflowNodes?: PersistedCanvasNode[];
}

export function NodeConfigModal({
  nodes,
  edges = EMPTY_EDGES,
  plugins = EMPTY_PLUGINS,
  onNodeConfigChange,
  onNodeTitleChange,
  onNodeIncomeHandleSideChange,
  onNodeOutcomeHandleSideChange,
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

  const pluginConfig = useMemo(
    () => (activeNode?.data.pluginConfig ?? {}) as Record<string, unknown>,
    [activeNode?.data.pluginConfig],
  );

  const hasConfigTab =
    !!pluginUI || (plugin?.metadata.configuration_input.length ?? 0) > 0;

  const visibleModalTabs = useMemo(
    () =>
      (pluginUI?.modalTabs ?? []).filter(
        (tab) => tab.isVisible?.(pluginConfig) ?? true,
      ),
    [pluginUI, pluginConfig],
  );

  const tabsKey = useMemo(
    () =>
      `${configModalNodeId ?? "none"}:${visibleModalTabs.map((tab) => tab.id).join(",")}:${hasConfigTab}`,
    [configModalNodeId, visibleModalTabs, hasConfigTab],
  );

  return (
    <Dialog open={configModalNodeId !== null} onOpenChange={(open) => { if (!open) closeConfigModal(); }}>
      <DialogContent className="flex h-[75vh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="shrink-0 border-b border-info-border bg-accent px-6 py-4">
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
          <Tabs
            key={tabsKey}
            className="flex min-h-0 flex-1 flex-col"
            defaultValue="general"
          >
            <TabsList className="h-9 w-full shrink-0 rounded-none border-b border-border bg-muted p-0">
              <TabsTrigger className={MODAL_TAB_TRIGGER_CLASS} value="general">
                General
              </TabsTrigger>
              {hasConfigTab ? (
                <TabsTrigger className={MODAL_TAB_TRIGGER_CLASS} value="configuration">
                  Configuration
                </TabsTrigger>
              ) : null}
              {visibleModalTabs.map((tab) => (
                <TabsTrigger key={tab.id} className={MODAL_TAB_TRIGGER_CLASS} value={tab.id}>
                  {tab.label}
                </TabsTrigger>
              ))}
              <TabsTrigger className={MODAL_TAB_TRIGGER_CLASS} value="description">
                Description
              </TabsTrigger>
              <TabsTrigger className={MODAL_TAB_TRIGGER_CLASS} value="help">
                Help
              </TabsTrigger>
            </TabsList>

            <NodeConfigGeneralTab
              activeNode={activeNode}
              plugin={plugin}
              onNodeTitleChange={onNodeTitleChange}
              onNodeIncomeHandleSideChange={onNodeIncomeHandleSideChange}
              onNodeOutcomeHandleSideChange={onNodeOutcomeHandleSideChange}
            />

            {hasConfigTab ? (
              <TabsContent className={MODAL_TAB_CONTENT_CLASS} value="configuration">
                {pluginUI ? (
                  <pluginUI.ConfigPanel
                    config={pluginConfig}
                    nodeId={activeNode.id}
                    workflowNodes={workflowNodes}
                    workflowEdges={edges}
                    plugins={plugins}
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

            {visibleModalTabs.map((tab) => (
              <TabsContent key={tab.id} className={MODAL_TAB_CONTENT_CLASS} value={tab.id}>
                <tab.Panel
                  config={pluginConfig}
                  nodeId={activeNode.id}
                  workflowNodes={workflowNodes}
                  workflowEdges={edges}
                  plugins={plugins}
                  onChange={(config) => onNodeConfigChange?.(activeNode.id, config)}
                  onPreview={() => undefined}
                />
              </TabsContent>
            ))}

            <NodeConfigDescriptionTab activeNode={activeNode} plugin={plugin} />

            <TabsContent className={MODAL_TAB_CONTENT_CLASS} value="help">
              {pluginUI?.HelpPanel ? (
                <pluginUI.HelpPanel
                  config={pluginConfig}
                  nodeId={activeNode.id}
                  workflowNodes={workflowNodes}
                  workflowEdges={edges}
                  plugins={plugins}
                  onChange={(config) => onNodeConfigChange?.(activeNode.id, config)}
                  onPreview={() => undefined}
                />
              ) : (
                <HelpUnavailable />
              )}
            </TabsContent>
          </Tabs>
        ) : null}

        <div className="shrink-0 border-t border-info-border bg-accent/10 px-6 py-3">
          <Button size="sm" variant="outline" onClick={closeConfigModal}>
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
