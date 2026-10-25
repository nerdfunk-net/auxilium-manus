"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";

import { stringField } from "../shared/config-field-helpers";
import { ExpressionField } from "../shared/expression-field";
import {
  NAUTOBOT_SOURCE_ID_KEY,
  isNautobotSourceConfigured,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import {
  DEFAULT_DEVICE_ID,
  DEVICE_ID_KEY,
  DEVICE_ID_MISSING_PROBLEM,
  REMOVE_IP_ADDRESSES_KEY,
  configProblems,
  removeIpAddressesFromConfig,
} from "./config";
import { RemoveFromNautobotHelpPanel } from "./help-panel";

function RemoveFromNautobotConfigPanel({
  nodeId,
  config,
  onChange,
  workflowNodes,
  workflowEdges,
}: PluginConfigPanelProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });
  const isSourceConfigured = isNautobotSourceConfigured(config);
  const nodes = workflowNodes ?? [];
  const edges = workflowEdges ?? [];
  const problems = configProblems(config);
  const removeIps = removeIpAddressesFromConfig(config);

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
        <div className="flex items-start gap-2">
          <Checkbox
            id={`remove-ip-addresses-${nodeId}`}
            checked={removeIps}
            onCheckedChange={(checked) => patch(REMOVE_IP_ADDRESSES_KEY, checked === true)}
            className="mt-0.5"
          />
          <div className="space-y-0.5">
            <Label
              htmlFor={`remove-ip-addresses-${nodeId}`}
              className="font-mono text-xs font-medium"
            >
              {REMOVE_IP_ADDRESSES_KEY}
            </Label>
            <p className="text-[11px] leading-4 text-muted-foreground">
              Also remove the IP addresses assigned to the device. They are removed first, then
              the device. An address another device or VM also holds is kept.
            </p>
          </div>
        </div>
        <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
          {removeIps
            ? "The device, its interfaces and its exclusive IP addresses are deleted permanently."
            : "The device and its interfaces are deleted permanently."}
        </p>
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
