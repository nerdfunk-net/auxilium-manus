"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";
import { useNautobotStatusesQuery } from "@/hooks/queries/use-nautobot-statuses-query";

import { stringField } from "../shared/config-field-helpers";
import { ExpressionField } from "../shared/expression-field";
import {
  NAUTOBOT_SOURCE_ID_KEY,
  isNautobotSourceConfigured,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import { SelectOrExpressionField } from "../shared/select-or-expression-field";
import {
  DESCRIPTION_KEY,
  DNS_NAME_KEY,
  IP_ID_KEY,
  IP_TYPE_OPTIONS,
  NAMESPACE_KEY,
  NO_FIELD_PROBLEM,
  ROLE_KEY,
  STATUS_KEY,
  TYPE_KEY,
  configProblems,
} from "./config";
import { UpdateNautobotIpHelpPanel } from "./help-panel";

function UpdateNautobotIpConfigPanel({
  nodeId,
  config,
  onChange,
  workflowNodes,
  workflowEdges,
}: PluginConfigPanelProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });
  const isSourceConfigured = isNautobotSourceConfigured(config);
  const statuses = useNautobotStatusesQuery({ sourceId, contentType: "ipam.ipaddress" });
  const nodes = workflowNodes ?? [];
  const edges = workflowEdges ?? [];
  const problems = configProblems(config);

  const statusOptions = useMemo(
    () => (statuses.data ?? []).map((item) => ({ value: item.name, label: item.name })),
    [statuses.data],
  );

  const [sourceOpen, setSourceOpen] = useState(false);
  const closeSource = useCallback(() => setSourceOpen(false), []);

  const patch = useCallback(
    (key: string, value: unknown) => onChange({ ...config, [key]: value }),
    [config, onChange],
  );
  const handleSourceChange = useCallback(
    (next: string) => patch(NAUTOBOT_SOURCE_ID_KEY, next),
    [patch],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{NAUTOBOT_SOURCE_ID_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            nautobot
          </Badge>
        </div>
        {isSourceConfigured ? (
          <p className="font-mono text-[11px] text-muted-foreground">
            {sourceId}
            {credentials.isReady ? (
              <span className="block truncate font-sans text-muted-foreground">
                {credentials.url}
              </span>
            ) : credentials.isLoading ? (
              <span className="block font-sans">Loading credentials…</span>
            ) : (
              <span className="block font-sans text-warning-foreground">
                Source not found in settings
              </span>
            )}
          </p>
        ) : (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
        )}
        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setSourceOpen(true)}
        >
          {isSourceConfigured ? "Edit Source" : "Configure Source"}
        </Button>
      </div>

      <ExpressionField
        configKey={IP_ID_KEY}
        value={stringField(config, IP_ID_KEY)}
        placeholder="{custom.ip_id}"
        onValueChange={(next) => patch(IP_ID_KEY, next)}
        nodeId={nodeId}
        workflowNodes={nodes}
        workflowEdges={edges}
      >
        {problems.includes("ip_id is not configured") ? (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
        ) : null}
        <p className="text-[11px] leading-4 text-muted-foreground">
          Nautobot ID (UUID) of the address, for example the attribute Add IP to Nautobot filled.
        </p>
      </ExpressionField>

      <div className="space-y-4 border-t pt-3">
        {problems.includes(NO_FIELD_PROBLEM) ? (
          <p className="text-[11px] text-warning-foreground">
            Fill in at least one field to update.
          </p>
        ) : (
          <p className="text-[11px] leading-4 text-muted-foreground">
            Only filled-in fields are changed. An empty field is left as it is.
          </p>
        )}

        <SelectOrExpressionField
          label={STATUS_KEY}
          value={stringField(config, STATUS_KEY)}
          placeholder="Reserved"
          onValueChange={(next) => patch(STATUS_KEY, next)}
          sourceId={sourceId}
          options={statusOptions}
          optionsLoading={statuses.isLoading}
          hint="Pick a status Nautobot offers for IP addresses, or type a name or {path}."
          nodeId={nodeId}
          workflowNodes={nodes}
          workflowEdges={edges}
        />

        <SelectOrExpressionField
          label={TYPE_KEY}
          value={stringField(config, TYPE_KEY)}
          placeholder="host"
          onValueChange={(next) => patch(TYPE_KEY, next)}
          sourceId={sourceId}
          options={IP_TYPE_OPTIONS}
          hint="host, dhcp or slaac, or a {path}."
          nodeId={nodeId}
          workflowNodes={nodes}
          workflowEdges={edges}
        />

        <ExpressionField
          configKey={ROLE_KEY}
          value={stringField(config, ROLE_KEY)}
          placeholder="Secondary"
          onValueChange={(next) => patch(ROLE_KEY, next)}
          nodeId={nodeId}
          workflowNodes={nodes}
          workflowEdges={edges}
        >
          <p className="text-[11px] leading-4 text-muted-foreground">
            Name or UUID of a role that applies to IP addresses.
          </p>
        </ExpressionField>

        <ExpressionField
          configKey={DNS_NAME_KEY}
          value={stringField(config, DNS_NAME_KEY)}
          placeholder="host.example.org"
          onValueChange={(next) => patch(DNS_NAME_KEY, next)}
          nodeId={nodeId}
          workflowNodes={nodes}
          workflowEdges={edges}
        />

        <ExpressionField
          configKey={DESCRIPTION_KEY}
          value={stringField(config, DESCRIPTION_KEY)}
          placeholder=""
          onValueChange={(next) => patch(DESCRIPTION_KEY, next)}
          nodeId={nodeId}
          workflowNodes={nodes}
          workflowEdges={edges}
        />

        <ExpressionField
          configKey={NAMESPACE_KEY}
          value={stringField(config, NAMESPACE_KEY)}
          placeholder="Global"
          onValueChange={(next) => patch(NAMESPACE_KEY, next)}
          nodeId={nodeId}
          workflowNodes={nodes}
          workflowEdges={edges}
        >
          <p className="text-[11px] leading-4 text-muted-foreground">
            Moves the address to a prefix of this namespace that contains it; see Help.
          </p>
        </ExpressionField>
      </div>

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={closeSource}
        onSave={handleSourceChange}
      />
    </div>
  );
}

export const UpdateNautobotIpPlugin: PluginUIComponent = {
  ConfigPanel: UpdateNautobotIpConfigPanel,
  HelpPanel: UpdateNautobotIpHelpPanel,
};
