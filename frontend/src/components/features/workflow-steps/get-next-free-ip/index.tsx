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

import { AttributePathPicker } from "../shared/attribute-path-picker";
import { ExpressionField } from "../shared/expression-field";
import {
  NAUTOBOT_SOURCE_ID_KEY,
  isNautobotSourceConfigured,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import {
  ATTRIBUTE_PATH_KEY,
  COUNT_KEY,
  DEFAULT_COUNT,
  DEFAULT_NAMESPACE,
  DEFAULT_START_OFFSET,
  MAX_COUNT,
  NAMESPACE_KEY,
  PREFIX_KEY,
  START_OFFSET_KEY,
  isWholeNumber,
  numberText,
  stringFromConfig,
  withNumberText,
} from "./config";
import { GetNextFreeIpHelpPanel } from "./help-panel";

function GetNextFreeIpConfigPanel({
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

  const prefix = stringFromConfig(config, PREFIX_KEY);
  const namespace = config[NAMESPACE_KEY] === undefined
    ? DEFAULT_NAMESPACE
    : stringFromConfig(config, NAMESPACE_KEY);
  const attributePath = stringFromConfig(config, ATTRIBUTE_PATH_KEY);

  const [sourceOpen, setSourceOpen] = useState(false);
  const [pathPickerOpen, setPathPickerOpen] = useState(false);

  const handleSourceChange = useCallback(
    (next: string) => onChange({ ...config, [NAUTOBOT_SOURCE_ID_KEY]: next }),
    [config, onChange],
  );
  const handlePrefixChange = useCallback(
    (next: string) => onChange({ ...config, [PREFIX_KEY]: next }),
    [config, onChange],
  );
  const handleNamespaceChange = useCallback(
    (next: string) => onChange({ ...config, [NAMESPACE_KEY]: next }),
    [config, onChange],
  );
  const handleCountChange = useCallback(
    (text: string) => onChange(withNumberText(config, COUNT_KEY, text)),
    [config, onChange],
  );
  const handleOffsetChange = useCallback(
    (text: string) => onChange(withNumberText(config, START_OFFSET_KEY, text)),
    [config, onChange],
  );
  const handleAttributePathChange = useCallback(
    (next: string) => onChange({ ...config, [ATTRIBUTE_PATH_KEY]: next }),
    [config, onChange],
  );
  const closePathPicker = useCallback(() => setPathPickerOpen(false), [setPathPickerOpen]);
  const handlePathPicked = useCallback(
    (path: string) => {
      handleAttributePathChange(path.replace(/^\{|\}$/g, ""));
      setPathPickerOpen(false);
    },
    [handleAttributePathChange, setPathPickerOpen],
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
        configKey={PREFIX_KEY}
        value={prefix}
        placeholder="192.168.178.0/24"
        onValueChange={handlePrefixChange}
        nodeId={nodeId}
        workflowNodes={nodes}
        workflowEdges={edges}
      >
        {prefix.trim() ? null : (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
        )}
        <p className="text-[11px] leading-4 text-muted-foreground">
          Prefix in CIDR form, fixed or a <span className="font-mono">{"{path}"}</span>{" "}
          resolved per device.
        </p>
      </ExpressionField>

      <ExpressionField
        configKey={NAMESPACE_KEY}
        value={namespace}
        placeholder={DEFAULT_NAMESPACE}
        onValueChange={handleNamespaceChange}
        nodeId={nodeId}
        workflowNodes={nodes}
        workflowEdges={edges}
      >
        <p className="text-[11px] leading-4 text-muted-foreground">
          Namespace the prefix lives in. Empty uses{" "}
          <span className="font-mono">{DEFAULT_NAMESPACE}</span>.
        </p>
      </ExpressionField>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{COUNT_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            integer
          </Badge>
        </div>
        <Input
          type="number"
          min={1}
          max={MAX_COUNT}
          aria-label="Number of IP addresses"
          value={numberText(config, COUNT_KEY, DEFAULT_COUNT)}
          onChange={(event) => handleCountChange(event.target.value)}
          className="h-8 font-mono text-xs focus-visible:ring-step/40"
        />
        {isWholeNumber(config, COUNT_KEY, DEFAULT_COUNT) ? null : (
          <p className="text-[11px] text-warning-foreground">Enter a whole number.</p>
        )}
        <p className="text-[11px] leading-4 text-muted-foreground">
          Addresses per device. 1 stores a single address, more stores a list.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{START_OFFSET_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            integer
          </Badge>
        </div>
        <Input
          type="number"
          min={0}
          aria-label="Start offset"
          value={numberText(config, START_OFFSET_KEY, DEFAULT_START_OFFSET)}
          onChange={(event) => handleOffsetChange(event.target.value)}
          className="h-8 font-mono text-xs focus-visible:ring-step/40"
        />
        {isWholeNumber(config, START_OFFSET_KEY, DEFAULT_START_OFFSET) ? null : (
          <p className="text-[11px] text-warning-foreground">Enter a whole number.</p>
        )}
        <p className="text-[11px] leading-4 text-muted-foreground">
          Counted from the network address: 192.168.178.0/24 with 10 starts the search at
          192.168.178.10.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{ATTRIBUTE_PATH_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <div className="flex items-center gap-1.5">
          <Input
            aria-label="Attribute that receives the IP"
            value={attributePath}
            onChange={(event) => handleAttributePathChange(event.target.value)}
            placeholder="custom.new_ip"
            className="h-8 font-mono text-xs focus-visible:ring-step/40"
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8 shrink-0"
            onClick={() => setPathPickerOpen(true)}
            title="Browse attributes"
          >
            <Search className="size-3.5" aria-hidden />
          </Button>
        </div>
        {attributePath.trim() ? null : (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
        )}
        <p className="text-[11px] leading-4 text-muted-foreground">
          Attribute that receives the address (a list when count is above 1).
        </p>
        <AttributePathPicker
          open={pathPickerOpen}
          onClose={closePathPicker}
          onSelect={handlePathPicked}
          nodeId={nodeId}
          workflowNodes={nodes}
          workflowEdges={edges}
        />
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

export const GetNextFreeIpPlugin: PluginUIComponent = {
  ConfigPanel: GetNextFreeIpConfigPanel,
  HelpPanel: GetNextFreeIpHelpPanel,
};
