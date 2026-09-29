"use client";

import { Search } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
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

import { AttributePathPicker } from "../shared/attribute-path-picker";
import {
  NAUTOBOT_SOURCE_ID_KEY,
  isNautobotSourceConfigured,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import { ExistsInNautobotHelpPanel } from "./help-panel";

const STRATEGY_KEY = "strategy";
const IP_ADDRESS_KEY = "ip_address";
const CASE_INSENSITIVE_KEY = "case_insensitive_lookup";
const DEFAULT_STRATEGY = "name";
const DEFAULT_IP_ADDRESS = "{device.primary_ip4}";

const STRATEGIES = [
  { value: "name", label: "Device name", hint: "Match a device with the same name." },
  {
    value: "primary_ip",
    label: "Primary IP",
    hint: "Match a device whose primary IPv4 is the IP address.",
  },
  {
    value: "interface_ip",
    label: "Interface IP",
    hint: "Match a device with the IP address assigned to any interface.",
  },
] as const;

type Strategy = (typeof STRATEGIES)[number]["value"];

function strategyFromConfig(config: Record<string, unknown>): Strategy {
  const raw = config[STRATEGY_KEY];
  return STRATEGIES.some((s) => s.value === raw) ? (raw as Strategy) : DEFAULT_STRATEGY;
}

function ExistsInNautobotConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes,
  workflowEdges,
}: PluginConfigPanelProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });
  const strategy = strategyFromConfig(config);
  const strategyHint = STRATEGIES.find((s) => s.value === strategy)?.hint;
  const isIpStrategy = strategy !== "name";
  const ipAddress =
    typeof config[IP_ADDRESS_KEY] === "string"
      ? (config[IP_ADDRESS_KEY] as string)
      : DEFAULT_IP_ADDRESS;
  const caseInsensitive = config[CASE_INSENSITIVE_KEY] === true;
  const isSourceConfigured = isNautobotSourceConfigured(config);

  const [sourceOpen, setSourceOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  const handleSourceIdChange = useCallback(
    (next: string) => onChange({ ...config, [NAUTOBOT_SOURCE_ID_KEY]: next }),
    [config, onChange],
  );
  const handleStrategyChange = useCallback(
    (next: string) => onChange({ ...config, [STRATEGY_KEY]: next }),
    [config, onChange],
  );
  const handleIpChange = useCallback(
    (next: string) => onChange({ ...config, [IP_ADDRESS_KEY]: next }),
    [config, onChange],
  );
  const handleCaseInsensitiveChange = useCallback(
    (checked: boolean) => onChange({ ...config, [CASE_INSENSITIVE_KEY]: checked }),
    [config, onChange],
  );
  const closePicker = useCallback(() => setPickerOpen(false), []);
  const handlePickIp = useCallback(
    (path: string) => handleIpChange(`{${path.replace(/^\{|\}$/g, "")}}`),
    [handleIpChange],
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

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{STRATEGY_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={strategy} onValueChange={handleStrategyChange}>
          <SelectTrigger className="h-7 text-xs focus-visible:ring-step/40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STRATEGIES.map((s) => (
              <SelectItem key={s.value} value={s.value} className="text-xs">
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[11px] leading-4 text-muted-foreground">{strategyHint}</p>
      </div>

      {isIpStrategy ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">{IP_ADDRESS_KEY}</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <div className="flex items-center gap-1.5">
            <Input
              value={ipAddress}
              onChange={(event) => handleIpChange(event.target.value)}
              placeholder={DEFAULT_IP_ADDRESS}
              className="h-8 font-mono text-xs focus-visible:ring-step/40"
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="size-8 shrink-0"
              onClick={() => setPickerOpen(true)}
              title="Browse attributes"
            >
              <Search className="size-3.5" aria-hidden />
            </Button>
          </div>
          <p className="text-[11px] leading-4 text-muted-foreground">
            Fixed IP or a <span className="font-mono">{"{path}"}</span> resolved per
            device. A /prefix length is ignored.
          </p>
          <AttributePathPicker
            open={pickerOpen}
            onClose={closePicker}
            onSelect={handlePickIp}
            nodeId={nodeId}
            workflowNodes={workflowNodes ?? []}
            workflowEdges={workflowEdges ?? []}
          />
        </div>
      ) : (
        <div className="space-y-1.5 border-t pt-3">
          <label className="flex items-center gap-1.5 text-xs font-medium">
            <Checkbox
              checked={caseInsensitive}
              onCheckedChange={(checked) => handleCaseInsensitiveChange(checked === true)}
            />
            Use case-insensitive lookup
          </label>
          <p className="text-[11px] leading-4 text-muted-foreground">
            Match the device name regardless of case.
          </p>
        </div>
      )}

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />
    </div>
  );
}

export const ExistsInNautobotPlugin: PluginUIComponent = {
  ConfigPanel: ExistsInNautobotConfigPanel,
  HelpPanel: ExistsInNautobotHelpPanel,
};
