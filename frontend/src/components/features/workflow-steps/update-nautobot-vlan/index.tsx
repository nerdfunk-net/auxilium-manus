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
  DRY_RUN_KEY,
  INTERFACE_CONFLICT_PROBLEM,
  VLANS_FROM_INTERFACES_KEY,
  interfaceModeEnabledPatch,
  isFromInterfaces,
  NAME_KEY,
  NO_FIELD_PROBLEM,
  NO_VLAN_PROBLEM,
  ROLE_KEY,
  STATUS_KEY,
  VID_KEY,
  VLAN_GROUP_KEY,
  VLAN_ID_KEY,
  configProblems,
} from "./config";
import { UpdateNautobotVlanHelpPanel } from "./help-panel";
import { DryRunSwitch, FromInterfacesSwitch, LocationsFields } from "../shared/nautobot-update-fields";

function UpdateNautobotVlanConfigPanel({
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
    contentType: "ipam.vlan",
  });
  const nodes = workflowNodes ?? [];
  const edges = workflowEdges ?? [];
  const problems = configProblems(config);
  const fromInterfaces = isFromInterfaces(config);
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
  const handleFromInterfacesChange = useCallback(
    (next: boolean) =>
      onChange(
        next
          ? { ...config, ...interfaceModeEnabledPatch() }
          : {
              ...config,
              [VLANS_FROM_INTERFACES_KEY]: false,
              [DRY_RUN_KEY]: false,
            },
      ),
    [config, onChange],
  );
  const handleDryRunChange = useCallback(
    (next: boolean) => patch(DRY_RUN_KEY, next),
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
        label="VLANs from interfaces"
        description="Take the tagged and untagged VLANs of the device's interfaces and add the device's location to each. Needs Get Nautobot Attributes with interfaces."
        ariaLabel={VLANS_FROM_INTERFACES_KEY}
        checked={fromInterfaces}
        onCheckedChange={handleFromInterfacesChange}
        bordered
      />

      {fromInterfaces ? (
        <div className="space-y-3">
          {problems.includes(INTERFACE_CONFLICT_PROBLEM) ? (
            <p className="text-[11px] text-warning-foreground">
              {INTERFACE_CONFLICT_PROBLEM}.
            </p>
          ) : null}
          <DryRunSwitch
            description="Write nothing; list per device the VLANs that would get the location."
            checked={dryRun}
            onCheckedChange={handleDryRunChange}
          />
        </div>
      ) : (
        <>
          <div className="space-y-4">
            {problems.includes(NO_VLAN_PROBLEM) ? (
              <p className="text-[11px] text-warning-foreground">
                Set vlan_id or vid to select the VLAN.
              </p>
            ) : null}
            <ExpressionField
              configKey={VLAN_ID_KEY}
              value={stringField(config, VLAN_ID_KEY)}
              placeholder="{custom.vlan_id}"
              onValueChange={(next) => patch(VLAN_ID_KEY, next)}
              nodeId={nodeId}
              workflowNodes={nodes}
              workflowEdges={edges}
            >
              <p className="text-[11px] leading-4 text-muted-foreground">
                Nautobot ID (UUID) of the VLAN. When set, vid is ignored.
              </p>
            </ExpressionField>
            <ExpressionField
              configKey={VID_KEY}
              value={stringField(config, VID_KEY)}
              placeholder="100"
              onValueChange={(next) => patch(VID_KEY, next)}
              nodeId={nodeId}
              workflowNodes={nodes}
              workflowEdges={edges}
            >
              <p className="text-[11px] leading-4 text-muted-foreground">
                VLAN ID (1-4094), looked up when vlan_id is empty.
              </p>
            </ExpressionField>
            <ExpressionField
              configKey={VLAN_GROUP_KEY}
              value={stringField(config, VLAN_GROUP_KEY)}
              placeholder="Campus"
              onValueChange={(next) => patch(VLAN_GROUP_KEY, next)}
              nodeId={nodeId}
              workflowNodes={nodes}
              workflowEdges={edges}
            >
              <p className="text-[11px] leading-4 text-muted-foreground">
                Name or UUID of a VLAN group that narrows the vid lookup.
              </p>
            </ExpressionField>
          </div>

          <div className="space-y-4 border-t pt-3">
            {problems.includes(NO_FIELD_PROBLEM) ? (
              <p className="text-[11px] text-warning-foreground">
                Fill in at least one field to update.
              </p>
            ) : (
              <p className="text-[11px] leading-4 text-muted-foreground">
                Only filled-in fields are changed. An empty field is left as it
                is.
              </p>
            )}

            <ExpressionField
              configKey={NAME_KEY}
              value={stringField(config, NAME_KEY)}
              placeholder="CLIENT-ACCESS"
              onValueChange={(next) => patch(NAME_KEY, next)}
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

            <SelectOrExpressionField
              label={STATUS_KEY}
              value={stringField(config, STATUS_KEY)}
              placeholder="Active"
              onValueChange={(next) => patch(STATUS_KEY, next)}
              sourceId={sourceId}
              options={statusOptions}
              optionsLoading={statuses.isLoading}
              hint="Pick a status Nautobot offers for VLANs, or type a name or {path}."
              nodeId={nodeId}
              workflowNodes={nodes}
              workflowEdges={edges}
            />

            <ExpressionField
              configKey={ROLE_KEY}
              value={stringField(config, ROLE_KEY)}
              placeholder="Client access"
              onValueChange={(next) => patch(ROLE_KEY, next)}
              nodeId={nodeId}
              workflowNodes={nodes}
              workflowEdges={edges}
            >
              <p className="text-[11px] leading-4 text-muted-foreground">
                Name or UUID of a role that applies to VLANs.
              </p>
            </ExpressionField>

            <LocationsFields
              config={config}
              patch={patch}
              problems={problems}
              noun="VLAN"
              nodeId={nodeId}
              workflowNodes={nodes}
              workflowEdges={edges}
            />
          </div>
        </>
      )}

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={closeSource}
        onSave={handleSourceChange}
      />
    </div>
  );
}

export const UpdateNautobotVlanPlugin: PluginUIComponent = {
  ConfigPanel: UpdateNautobotVlanConfigPanel,
  HelpPanel: UpdateNautobotVlanHelpPanel,
};
