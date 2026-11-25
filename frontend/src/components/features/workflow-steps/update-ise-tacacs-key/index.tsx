"use client";

import { useCallback, useMemo, useState } from "react";

import type {
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "@/components/features/workflows/types/workflow-canvas";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { ExpressionField } from "../shared/expression-field";
import { ISESourceSelectDialog } from "../shared/ise-source-select-dialog";
import { iseSourceIdFromConfig, ISE_SOURCE_ID_KEY } from "../shared/ise-source-config";
import { UpdateIseTacacsKeyHelpPanel } from "./help-panel";
import { SourceRow } from "../shared/source-row";

const EMPTY_NODES: PersistedCanvasNode[] = [];
const EMPTY_EDGES: WorkflowCanvasEdge[] = [];

const NEW_KEY_KEY = "new_key";

function newKeyFromConfig(config: Record<string, unknown>): string {
  const raw = config[NEW_KEY_KEY];
  return typeof raw === "string" ? raw : "";
}

function UpdateIseTacacsKeyConfigPanel({
  nodeId,
  config,
  onChange,
  workflowNodes = EMPTY_NODES,
  workflowEdges = EMPTY_EDGES,
}: PluginConfigPanelProps) {
  const sourceId = useMemo(() => iseSourceIdFromConfig(config), [config]);
  const newKey = useMemo(() => newKeyFromConfig(config), [config]);

  const [sourceOpen, setSourceOpen] = useState(false);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [ISE_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleNewKeyChange = useCallback(
    (next: string) => {
      onChange({ ...config, [NEW_KEY_KEY]: next });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      {/* ise_source_id */}
      <SourceRow
        label={ISE_SOURCE_ID_KEY}
        badge="ise"
        sourceId={sourceId}
        onOpen={() => setSourceOpen(true)}
      />

      {/* new_key */}
      <ExpressionField
        configKey={NEW_KEY_KEY}
        value={newKey}
        placeholder="{tacacs.new_key}"
        onValueChange={handleNewKeyChange}
        nodeId={nodeId}
        workflowNodes={workflowNodes}
        workflowEdges={workflowEdges}
        secret
      >
        <p className="text-[11px] leading-4 text-muted-foreground">
          Reference an attribute, e.g.{" "}
          <span className="font-mono">{"{tacacs.new_key}"}</span>, filled by Secret Get,
          Secret Generate or Generate Password. Literal keys are rejected.
        </p>
        {!newKey && <p className="text-[11px] text-warning-foreground">Not configured</p>}
      </ExpressionField>

      <ISESourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />
    </div>
  );
}

export const UpdateIseTacacsKeyPlugin: PluginUIComponent = {
  ConfigPanel: UpdateIseTacacsKeyConfigPanel,
  HelpPanel: UpdateIseTacacsKeyHelpPanel,
};
