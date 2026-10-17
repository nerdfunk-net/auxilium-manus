"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";
import { AttributePathPicker } from "@/components/features/workflow-steps/shared/attribute-path-picker";
import { AttributePathPreview } from "@/components/features/workflow-steps/shared/attribute-path-preview";

import { RouteOnAttributeHelpPanel } from "./help-panel";
import {
  buildRouteOnAttributeConfig,
  DEFAULT_ROUTE_ON_ATTRIBUTE_CONFIG,
  parseRouteOnAttributeConfig,
} from "./route-config";
import { RoutesTabPanel } from "./routes-tab";

function RouteOnAttributeConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes,
  workflowEdges,
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const parsed = useMemo(() => parseRouteOnAttributeConfig(config), [config]);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!Array.isArray(config.routes) || config.routes.length === 0) {
      onChange(buildRouteOnAttributeConfig(config, DEFAULT_ROUTE_ON_ATTRIBUTE_CONFIG));
    }
  }, [nodeId, config, onChange]);

  const handleAttributePathChange = useCallback(
    (value: string) => {
      onChange(buildRouteOnAttributeConfig(config, { attribute_path: value }));
    },
    [config, onChange],
  );

  const handleDefaultOutcomeChange = useCallback(
    (value: string) => {
      onChange(buildRouteOnAttributeConfig(config, { default_outcome: value }));
    },
    [config, onChange],
  );

  const handleCaseSensitiveChange = useCallback(
    (checked: boolean) => {
      onChange(buildRouteOnAttributeConfig(config, { case_sensitive: checked }));
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">attribute_path</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <div className="flex items-center gap-1.5">
          <Input
            value={parsed.attribute_path}
            onChange={(event) => handleAttributePathChange(event.target.value)}
            placeholder="device.network_driver"
            className="h-8 font-mono text-xs"
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 shrink-0 text-xs"
            onClick={() => setPickerOpen(true)}
          >
            Browse attributes
          </Button>
        </div>
        <p className="text-[11px] leading-4 text-muted-foreground">
          Use <span className="font-mono">device.network_driver</span> for core device
          fields, <span className="font-mono">nautobot.role.name</span> for Nautobot
          attributes, or <span className="font-mono">custom.field</span> for user-defined
          attribute bags.
        </p>
        <AttributePathPreview
          path={parsed.attribute_path}
          nodeId={nodeId}
          workflowNodes={workflowNodes ?? []}
          workflowEdges={workflowEdges ?? []}
        />
        <AttributePathPicker
          open={pickerOpen}
          onClose={() => setPickerOpen(false)}
          onSelect={handleAttributePathChange}
          nodeId={nodeId}
          workflowNodes={workflowNodes ?? []}
          workflowEdges={workflowEdges ?? []}
        />
      </div>

      <p className="rounded-md border border-dashed bg-muted/40 px-3 py-2 text-[11px] leading-4 text-muted-foreground">
        {parsed.routes.length} route{parsed.routes.length === 1 ? "" : "s"} configured. Edit the
        outcomes and their expressions in the <span className="font-medium">Routes</span> tab.
      </p>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">default_outcome</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={parsed.default_outcome}
          onChange={(event) => handleDefaultOutcomeChange(event.target.value)}
          placeholder="unmatched"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Devices with a missing or unmatched attribute value are sent to this outcome.
          Leave empty to send them to the failure handle instead.
        </p>
      </div>

      <div className="flex items-start gap-2">
        <Checkbox
          id={`case-sensitive-${nodeId}`}
          checked={parsed.case_sensitive}
          onCheckedChange={(checked) => handleCaseSensitiveChange(checked === true)}
          className="mt-0.5"
        />
        <div className="space-y-0.5">
          <Label htmlFor={`case-sensitive-${nodeId}`} className="font-mono text-xs font-medium">
            case_sensitive
          </Label>
          <p className="text-[11px] text-muted-foreground">
            When disabled, route matching ignores letter case.
          </p>
        </div>
      </div>
    </div>
  );
}

export const RouteOnAttributePlugin = {
  ConfigPanel: RouteOnAttributeConfigPanel,
  HelpPanel: RouteOnAttributeHelpPanel,
  modalTabs: [{ id: "routes", label: "Routes", Panel: RoutesTabPanel }],
};
