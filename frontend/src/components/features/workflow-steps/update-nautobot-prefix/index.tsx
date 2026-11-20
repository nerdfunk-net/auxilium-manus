"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
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
import { Switch } from "@/components/ui/switch";
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
  BAD_MODE_PROBLEM,
  DRY_RUN_KEY,
  INTERFACE_CONFLICT_PROBLEM,
  PREFIXES_FROM_INTERFACES_KEY,
  interfaceModeEnabledPatch,
  isFromInterfaces,
  LOCATIONS_KEY,
  LOCATIONS_MODE_KEY,
  LOCATIONS_MODE_OPTIONS,
  NO_FIELD_PROBLEM,
  NO_PREFIX_PROBLEM,
  ROLE_KEY,
  STATUS_KEY,
  PREFIX_ID_KEY,
  PREFIX_KEY,
  NAMESPACE_KEY,
  configProblems,
  locationsModeFromConfig,
} from "./config";
import { UpdateNautobotPrefixHelpPanel } from "./help-panel";

function UpdateNautobotPrefixConfigPanel({
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
    contentType: "ipam.prefix",
  });
  const nodes = workflowNodes ?? [];
  const edges = workflowEdges ?? [];
  const problems = configProblems(config);
  const locationsMode = locationsModeFromConfig(config);
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
  const handleModeChange = useCallback(
    (next: string) => patch(LOCATIONS_MODE_KEY, next),
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

      <div className="flex items-center justify-between gap-3 border-t pt-3">
        <div className="space-y-0.5">
          <Label className="text-xs font-medium">
            Prefixes from interfaces
          </Label>
          <p className="text-[11px] text-muted-foreground">
            Take the parent prefix of every IP address on the device&apos;s
            interfaces and add the device&apos;s location to each. Needs Get
            Nautobot Attributes with interfaces.
          </p>
        </div>
        <Switch
          aria-label={PREFIXES_FROM_INTERFACES_KEY}
          checked={fromInterfaces}
          onCheckedChange={handleFromInterfacesChange}
          className="data-[state=checked]:bg-step"
        />
      </div>

      {fromInterfaces ? (
        <div className="space-y-3">
          {problems.includes(INTERFACE_CONFLICT_PROBLEM) ? (
            <p className="text-[11px] text-warning-foreground">
              {INTERFACE_CONFLICT_PROBLEM}.
            </p>
          ) : null}
          <div className="flex items-center justify-between gap-3">
            <div className="space-y-0.5">
              <Label className="text-xs font-medium">Dry run</Label>
              <p className="text-[11px] text-muted-foreground">
                Write nothing; list per device the prefixes that would get the
                location.
              </p>
            </div>
            <Switch
              aria-label={DRY_RUN_KEY}
              checked={dryRun}
              onCheckedChange={handleDryRunChange}
              className="data-[state=checked]:bg-step"
            />
          </div>
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

            <ExpressionField
              configKey={LOCATIONS_KEY}
              value={stringField(config, LOCATIONS_KEY)}
              placeholder="Berlin, Munich"
              onValueChange={(next) => patch(LOCATIONS_KEY, next)}
              nodeId={nodeId}
              workflowNodes={nodes}
              workflowEdges={edges}
            >
              <p className="text-[11px] leading-4 text-muted-foreground">
                Names or UUIDs separated by commas, or a {"{path}"}. Quote a
                name with a comma: &quot;Frankfurt, West&quot;.
              </p>
            </ExpressionField>

            <div className="space-y-1.5">
              <span className="font-mono text-xs font-medium">
                {LOCATIONS_MODE_KEY}
              </span>
              <Select value={locationsMode} onValueChange={handleModeChange}>
                <SelectTrigger
                  className="h-8 text-xs focus:ring-step/40"
                  aria-label={LOCATIONS_MODE_KEY}
                >
                  <SelectValue placeholder="Pick a mode" />
                </SelectTrigger>
                <SelectContent>
                  {LOCATIONS_MODE_OPTIONS.map((option) => (
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
              {problems.includes(BAD_MODE_PROBLEM) ? (
                <p className="text-[11px] text-warning-foreground">
                  The stored mode is not valid and the step would fail. Pick
                  replace, add or remove.
                </p>
              ) : (
                <p className="text-[11px] leading-4 text-muted-foreground">
                  How the list is applied to the prefix&apos;s current
                  locations.
                </p>
              )}
            </div>
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
