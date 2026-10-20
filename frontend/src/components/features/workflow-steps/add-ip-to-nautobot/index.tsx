"use client";

import { Search } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";
import { useNautobotStatusesQuery } from "@/hooks/queries/use-nautobot-statuses-query";

import { AttributePathPicker } from "../shared/attribute-path-picker";
import { CheckboxField } from "../shared/checkbox-field";
import { boolField, numberInputField, stringField } from "../shared/config-field-helpers";
import { ExpressionField } from "../shared/expression-field";
import {
  NAUTOBOT_SOURCE_ID_KEY,
  isNautobotSourceConfigured,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import { SelectOrExpressionField } from "../shared/select-or-expression-field";
import {
  CREATE_PREFIX_KEY,
  DEFAULT_MASK_KEY,
  DEFAULT_NAMESPACE,
  DEFAULT_STATUS,
  DESCRIPTION_KEY,
  DNS_NAME_KEY,
  INTERFACE_KEY,
  IP_ADDRESS_KEY,
  NAMESPACE_KEY,
  RESULT_ATTRIBUTE_KEY,
  SET_PRIMARY_KEY,
  STATUS_KEY,
  configProblems,
  isValidMaskText,
  withNumberText,
} from "./config";
import { AddIpToNautobotHelpPanel } from "./help-panel";

function AddIpToNautobotConfigPanel({
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

  const ipAddress = stringField(config, IP_ADDRESS_KEY);
  const namespace = stringField(config, NAMESPACE_KEY, DEFAULT_NAMESPACE);
  const status = stringField(config, STATUS_KEY, DEFAULT_STATUS);
  const description = stringField(config, DESCRIPTION_KEY);
  const dnsName = stringField(config, DNS_NAME_KEY);
  const resultAttribute = stringField(config, RESULT_ATTRIBUTE_KEY);
  const interfaceName = stringField(config, INTERFACE_KEY);
  const createPrefix = boolField(config, CREATE_PREFIX_KEY);
  const setPrimary = boolField(config, SET_PRIMARY_KEY);
  const maskText = numberInputField(config, DEFAULT_MASK_KEY);
  const problems = configProblems(config);

  const statusOptions = useMemo(
    () => (statuses.data ?? []).map((item) => ({ value: item.name, label: item.name })),
    [statuses.data],
  );

  const [sourceOpen, setSourceOpen] = useState(false);
  const [resultPickerOpen, setResultPickerOpen] = useState(false);

  const patch = useCallback(
    (key: string, value: unknown) => onChange({ ...config, [key]: value }),
    [config, onChange],
  );
  const handleSourceChange = useCallback(
    (next: string) => patch(NAUTOBOT_SOURCE_ID_KEY, next),
    [patch],
  );
  const handleMaskChange = useCallback(
    (text: string) => onChange(withNumberText(config, DEFAULT_MASK_KEY, text)),
    [config, onChange],
  );
  const closeResultPicker = useCallback(() => setResultPickerOpen(false), [setResultPickerOpen]);
  const handleResultPicked = useCallback(
    (path: string) => {
      patch(RESULT_ATTRIBUTE_KEY, path.replace(/^\{|\}$/g, ""));
      setResultPickerOpen(false);
    },
    [patch, setResultPickerOpen],
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
        configKey={IP_ADDRESS_KEY}
        value={ipAddress}
        placeholder="{custom.new_ip}"
        onValueChange={(next) => patch(IP_ADDRESS_KEY, next)}
        nodeId={nodeId}
        workflowNodes={nodes}
        workflowEdges={edges}
      >
        {problems.includes("ip_address is not configured") ? (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
        ) : null}
        <p className="text-[11px] leading-4 text-muted-foreground">
          Fixed address or <span className="font-mono">{"{path}"}</span>. Without a prefix length
          the length of the prefix that contains it is used.
        </p>
      </ExpressionField>

      <ExpressionField
        configKey={NAMESPACE_KEY}
        value={namespace}
        placeholder={DEFAULT_NAMESPACE}
        onValueChange={(next) => patch(NAMESPACE_KEY, next)}
        nodeId={nodeId}
        workflowNodes={nodes}
        workflowEdges={edges}
      >
        <p className="text-[11px] leading-4 text-muted-foreground">
          Namespace of the address. Empty uses{" "}
          <span className="font-mono">{DEFAULT_NAMESPACE}</span>.
        </p>
      </ExpressionField>

      <SelectOrExpressionField
        label={STATUS_KEY}
        value={status}
        placeholder={DEFAULT_STATUS}
        onValueChange={(next) => patch(STATUS_KEY, next)}
        sourceId={sourceId}
        options={statusOptions}
        optionsLoading={statuses.isLoading}
        required
        hint="Status of the new IP address. Pick one Nautobot offers, or type a name or {path}."
        nodeId={nodeId}
        workflowNodes={nodes}
        workflowEdges={edges}
      />

      <div className="space-y-2 border-t pt-3">
        <CheckboxField
          id={`${nodeId}-create-prefix`}
          label={CREATE_PREFIX_KEY}
          checked={createPrefix}
          onCheckedChange={(next) => patch(CREATE_PREFIX_KEY, next)}
          description="Create the parent prefix when no prefix contains the address."
        />
        {createPrefix ? (
          <div className="space-y-1.5 pl-6">
            <span className="font-mono text-xs font-medium">{DEFAULT_MASK_KEY}</span>
            <Input
              type="number"
              min={1}
              max={128}
              aria-label="Default prefix length"
              placeholder="24"
              value={maskText}
              onChange={(event) => handleMaskChange(event.target.value)}
              className="h-8 font-mono text-xs focus-visible:ring-step/40"
            />
            {isValidMaskText(maskText) ? null : (
              <p className="text-[11px] text-warning-foreground">Enter a length from 1 to 128.</p>
            )}
            <p className="text-[11px] leading-4 text-muted-foreground">
              For an address without a length and no containing prefix. Empty uses 24 (IPv4) or 64
              (IPv6).
            </p>
          </div>
        ) : null}
      </div>

      <ExpressionField
        configKey={DESCRIPTION_KEY}
        value={description}
        placeholder=""
        onValueChange={(next) => patch(DESCRIPTION_KEY, next)}
        nodeId={nodeId}
        workflowNodes={nodes}
        workflowEdges={edges}
      />

      <ExpressionField
        configKey={DNS_NAME_KEY}
        value={dnsName}
        placeholder="host.example.org"
        onValueChange={(next) => patch(DNS_NAME_KEY, next)}
        nodeId={nodeId}
        workflowNodes={nodes}
        workflowEdges={edges}
      />

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{RESULT_ATTRIBUTE_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <div className="flex items-center gap-1.5">
          <Input
            aria-label="Attribute that receives the IP address ID"
            value={resultAttribute}
            onChange={(event) => patch(RESULT_ATTRIBUTE_KEY, event.target.value)}
            placeholder="custom.ip_id"
            className="h-8 font-mono text-xs focus-visible:ring-step/40"
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8 shrink-0"
            onClick={() => setResultPickerOpen(true)}
            title="Browse attributes"
          >
            <Search className="size-3.5" aria-hidden />
          </Button>
        </div>
        <p className="text-[11px] leading-4 text-muted-foreground">
          Optional. Receives the Nautobot ID (UUID) of the created or existing address.
        </p>
        <AttributePathPicker
          open={resultPickerOpen}
          onClose={closeResultPicker}
          onSelect={handleResultPicked}
          nodeId={nodeId}
          workflowNodes={nodes}
          workflowEdges={edges}
        />
      </div>

      <div className="space-y-2 border-t pt-3">
        <ExpressionField
          configKey={INTERFACE_KEY}
          value={interfaceName}
          placeholder="Vlan1"
          onValueChange={(next) => patch(INTERFACE_KEY, next)}
          nodeId={nodeId}
          workflowNodes={nodes}
          workflowEdges={edges}
        >
          <p className="text-[11px] leading-4 text-muted-foreground">
            Optional. Assigns the address to this interface of the device (it must exist in
            Nautobot).
          </p>
        </ExpressionField>
        <CheckboxField
          id={`${nodeId}-set-primary`}
          label={SET_PRIMARY_KEY}
          checked={setPrimary}
          onCheckedChange={(next) => patch(SET_PRIMARY_KEY, next)}
          description="Also make it the device's primary IPv4."
        />
        {problems.includes("set_primary needs interface_name") ? (
          <p className="text-[11px] text-warning-foreground">set_primary needs interface_name.</p>
        ) : null}
      </div>

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceChange}
      />
    </div>
  );
}

export const AddIpToNautobotPlugin: PluginUIComponent = {
  ConfigPanel: AddIpToNautobotConfigPanel,
  HelpPanel: AddIpToNautobotHelpPanel,
};
