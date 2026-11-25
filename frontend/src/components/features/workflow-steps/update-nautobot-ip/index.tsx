"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  ADDRESS_TOKENS,
  DESCRIPTION_KEY,
  DNS_NAME_KEY,
  DRY_RUN_KEY,
  INTERFACE_IP_ID_PROBLEM,
  IPS_FROM_INTERFACES_KEY,
  IP_ID_KEY,
  IP_TYPE_OPTIONS,
  IP_VERSION_ANY,
  IP_VERSION_KEY,
  IP_VERSION_OPTIONS,
  NAMESPACE_KEY,
  NO_FIELD_PROBLEM,
  ROLE_KEY,
  STATUS_KEY,
  TYPE_KEY,
  configProblems,
  interfaceModeEnabledPatch,
  ipVersionFromConfig,
  isFromInterfaces,
} from "./config";
import { UpdateNautobotIpHelpPanel } from "./help-panel";
import { DryRunSwitch, FromInterfacesSwitch } from "../shared/nautobot-update-fields";

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
  const statuses = useNautobotStatusesQuery({
    sourceId,
    contentType: "ipam.ipaddress",
  });
  const nodes = workflowNodes ?? [];
  const edges = workflowEdges ?? [];
  const problems = configProblems(config);
  const fromInterfaces = isFromInterfaces(config);
  const ipVersion = ipVersionFromConfig(config);
  const dryRun = config[DRY_RUN_KEY] === true || config[DRY_RUN_KEY] === "true";

  const statusOptions = useMemo(
    () =>
      (statuses.data ?? []).map((item) => ({
        value: item.name,
        label: item.name,
      })),
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

  const tokenHint = (
    <p className="text-[11px] leading-4 text-muted-foreground">
      Per address: <span className="font-mono">{ADDRESS_TOKENS.join(" ")}</span>
    </p>
  );
  const handleFromInterfacesChange = useCallback(
    (next: boolean) =>
      onChange(
        next
          ? { ...config, ...interfaceModeEnabledPatch() }
          : {
              ...config,
              [IPS_FROM_INTERFACES_KEY]: false,
              [DRY_RUN_KEY]: false,
            },
      ),
    [config, onChange],
  );
  const handleDryRunChange = useCallback(
    (next: boolean) => patch(DRY_RUN_KEY, next),
    [patch],
  );
  const handleIpVersionChange = useCallback(
    (next: string) =>
      patch(IP_VERSION_KEY, next === IP_VERSION_ANY ? "" : next),
    [patch],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">
            {NAUTOBOT_SOURCE_ID_KEY}
          </span>
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

      <FromInterfacesSwitch
        label="IP addresses from interfaces"
        description="Apply the values below to every IP address on the device's interfaces. Addresses that are also assigned elsewhere are skipped. Needs Get Nautobot Attributes with interfaces."
        ariaLabel={IPS_FROM_INTERFACES_KEY}
        checked={fromInterfaces}
        onCheckedChange={handleFromInterfacesChange}
      />

      {fromInterfaces ? (
        <div className="space-y-3">
          {problems.includes(INTERFACE_IP_ID_PROBLEM) ? (
            <p className="text-[11px] text-warning-foreground">
              {INTERFACE_IP_ID_PROBLEM}.
            </p>
          ) : null}
          <div className="space-y-1.5">
            <span className="font-mono text-xs font-medium">
              {IP_VERSION_KEY}
            </span>
            <Select value={ipVersion} onValueChange={handleIpVersionChange}>
              <SelectTrigger
                className="h-8 text-xs focus:ring-step/40"
                aria-label={IP_VERSION_KEY}
              >
                <SelectValue placeholder="IPv4 and IPv6" />
              </SelectTrigger>
              <SelectContent>
                {IP_VERSION_OPTIONS.map((option) => (
                  <SelectItem
                    key={option.value}
                    value={option.value}
                    className="text-xs"
                  >
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DryRunSwitch
            description="Write nothing; list per device the addresses that would change."
            checked={dryRun}
            onCheckedChange={handleDryRunChange}
          />
        </div>
      ) : (
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
            <p className="text-[11px] text-warning-foreground">
              Not configured
            </p>
          ) : null}
          <p className="text-[11px] leading-4 text-muted-foreground">
            Nautobot ID (UUID) of the address, for example the attribute Add IP
            to Nautobot filled.
          </p>
        </ExpressionField>
      )}

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
        >
          {fromInterfaces ? tokenHint : null}
        </ExpressionField>

        <ExpressionField
          configKey={DESCRIPTION_KEY}
          value={stringField(config, DESCRIPTION_KEY)}
          placeholder=""
          onValueChange={(next) => patch(DESCRIPTION_KEY, next)}
          nodeId={nodeId}
          workflowNodes={nodes}
          workflowEdges={edges}
        >
          {fromInterfaces ? tokenHint : null}
        </ExpressionField>

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
            Moves the address to a prefix of this namespace that contains it;
            see Help.
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
