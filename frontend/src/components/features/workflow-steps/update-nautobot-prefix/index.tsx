"use client";

import { useCallback, useMemo, useState } from "react";

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
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import { SelectOrExpressionField } from "../shared/select-or-expression-field";
import {
  DESCRIPTION_KEY,
  DRY_RUN_KEY,
  INTERFACE_CONFLICT_PROBLEM,
  PREFIXES_FROM_INTERFACES_KEY,
  interfaceModeEnabledPatch,
  isFromInterfaces,
  NO_FIELD_PROBLEM,
  NO_PREFIX_PROBLEM,
  ROLE_KEY,
  STATUS_KEY,
  PREFIX_ID_KEY,
  PREFIX_KEY,
  NAMESPACE_KEY,
  configProblems,
} from "./config";
import { UpdateNautobotPrefixHelpPanel } from "./help-panel";
import { DryRunSwitch, FromInterfacesSwitch, LocationsFields } from "../shared/nautobot-update-fields";
import { NautobotSourceStatus, SourceRow } from "../shared/source-row";

function UpdateNautobotPrefixConfigPanel({
  nodeId,
  config,
  onChange,
  workflowNodes,
  workflowEdges,
}: PluginConfigPanelProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });
  const statuses = useNautobotStatusesQuery({
    sourceId,
    contentType: "ipam.prefix",
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
              [PREFIXES_FROM_INTERFACES_KEY]: false,
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
      <SourceRow
        label={NAUTOBOT_SOURCE_ID_KEY}
        badge="nautobot"
        sourceId={sourceId}
        onOpen={() => setSourceOpen(true)}
        status={
          <NautobotSourceStatus
            isReady={credentials.isReady}
            isLoading={credentials.isLoading}
            url={credentials.url}
          />
        }
      />

      <FromInterfacesSwitch
        label="Prefixes from interfaces"
        description="Take the parent prefix of every IP address on the device's interfaces and add the device's location to each. Needs Get Nautobot Attributes with interfaces."
        ariaLabel={PREFIXES_FROM_INTERFACES_KEY}
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
            description="Write nothing; list per device the prefixes that would get the location."
            checked={dryRun}
            onCheckedChange={handleDryRunChange}
          />
        </div>
      ) : (
        <>
          <div className="space-y-4">
            {problems.includes(NO_PREFIX_PROBLEM) ? (
              <p className="text-[11px] text-warning-foreground">
                Set prefix_id or prefix to select the prefix.
              </p>
            ) : null}
            <ExpressionField
              configKey={PREFIX_ID_KEY}
              value={stringField(config, PREFIX_ID_KEY)}
              placeholder="{custom.prefix_id}"
              onValueChange={(next) => patch(PREFIX_ID_KEY, next)}
              nodeId={nodeId}
              workflowNodes={nodes}
              workflowEdges={edges}
            >
              <p className="text-[11px] leading-4 text-muted-foreground">
                Nautobot ID (UUID) of the prefix. When set, prefix is ignored.
              </p>
            </ExpressionField>
            <ExpressionField
              configKey={PREFIX_KEY}
              value={stringField(config, PREFIX_KEY)}
              placeholder="10.0.0.0/24"
              onValueChange={(next) => patch(PREFIX_KEY, next)}
              nodeId={nodeId}
              workflowNodes={nodes}
              workflowEdges={edges}
            >
              <p className="text-[11px] leading-4 text-muted-foreground">
                Network of the prefix, looked up when prefix_id is empty.
              </p>
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
                Name or UUID of a namespace that narrows the prefix lookup.
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
              hint="Pick a status Nautobot offers for prefixes, or type a name or {path}."
              nodeId={nodeId}
              workflowNodes={nodes}
              workflowEdges={edges}
            />

            <ExpressionField
              configKey={ROLE_KEY}
              value={stringField(config, ROLE_KEY)}
              placeholder="Management"
              onValueChange={(next) => patch(ROLE_KEY, next)}
              nodeId={nodeId}
              workflowNodes={nodes}
              workflowEdges={edges}
            >
              <p className="text-[11px] leading-4 text-muted-foreground">
                Name or UUID of a role that applies to prefixes.
              </p>
            </ExpressionField>

            <LocationsFields
              config={config}
              patch={patch}
              problems={problems}
              noun="prefix"
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

export const UpdateNautobotPrefixPlugin: PluginUIComponent = {
  ConfigPanel: UpdateNautobotPrefixConfigPanel,
  HelpPanel: UpdateNautobotPrefixHelpPanel,
};
