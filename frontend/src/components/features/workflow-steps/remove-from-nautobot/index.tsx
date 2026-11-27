"use client";

import { useCallback, useMemo, useState } from "react";

import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";

import { stringField } from "../shared/config-field-helpers";
import { ExpressionField } from "../shared/expression-field";
import {
  NAUTOBOT_SOURCE_ID_KEY,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import {
  DEFAULT_DEVICE_ID,
  DEVICE_ID_KEY,
  DEVICE_ID_MISSING_PROBLEM,
  DRY_RUN_KEY,
  REMOVE_IP_ADDRESSES_KEY,
  configProblems,
  dryRunFromConfig,
  removeIpAddressesFromConfig,
} from "./config";
import { RemoveFromNautobotHelpPanel } from "./help-panel";
import { NautobotSourceStatus, SourceRow } from "../shared/source-row";
import { CheckboxField } from "../shared/checkbox-field";

function RemoveFromNautobotConfigPanel({
  nodeId,
  config,
  onChange,
  workflowNodes,
  workflowEdges,
}: PluginConfigPanelProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });
  const nodes = workflowNodes ?? [];
  const edges = workflowEdges ?? [];
  const problems = configProblems(config);
  const removeIps = removeIpAddressesFromConfig(config);
  const dryRun = dryRunFromConfig(config);

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

      <ExpressionField
        configKey={DEVICE_ID_KEY}
        value={stringField(config, DEVICE_ID_KEY)}
        placeholder={DEFAULT_DEVICE_ID}
        onValueChange={(next) => patch(DEVICE_ID_KEY, next)}
        nodeId={nodeId}
        workflowNodes={nodes}
        workflowEdges={edges}
      >
        {problems.includes(DEVICE_ID_MISSING_PROBLEM) ? (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
        ) : null}
        <p className="text-[11px] leading-4 text-muted-foreground">
          Nautobot ID (UUID) of the device to remove. A name or address is not accepted.
        </p>
      </ExpressionField>

      <div className="space-y-1.5 border-t pt-3">
        <CheckboxField
          id={`remove-ip-addresses-${nodeId}`}
          label={REMOVE_IP_ADDRESSES_KEY}
          checked={removeIps}
          onCheckedChange={(checked) => patch(REMOVE_IP_ADDRESSES_KEY, checked)}
          description="Also remove the IP addresses assigned to the device. They are removed first, then the device. An address another device or VM also holds is kept."
        />
        <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
          {removeIps
            ? "The device, its interfaces and its exclusive IP addresses are deleted permanently."
            : "The device and its interfaces are deleted permanently."}
        </p>
        <div className="flex items-center justify-between gap-3">
          <div className="space-y-0.5">
            <Label className="text-xs font-medium">Dry run</Label>
            <p className="text-[11px] leading-4 text-muted-foreground">
              {dryRun
                ? "Nothing is deleted; each device gets a preview of what would be removed."
                : "Delete nothing; list per device what would be removed."}
            </p>
          </div>
          <Switch
            aria-label={DRY_RUN_KEY}
            checked={dryRun}
            onCheckedChange={(checked) => patch(DRY_RUN_KEY, checked)}
            className="data-[state=checked]:bg-step"
          />
        </div>
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

export const RemoveFromNautobotPlugin: PluginUIComponent = {
  ConfigPanel: RemoveFromNautobotConfigPanel,
  HelpPanel: RemoveFromNautobotHelpPanel,
};
