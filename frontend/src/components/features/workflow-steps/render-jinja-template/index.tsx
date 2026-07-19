"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

import { useTemplatesQuery } from "@/components/features/templates/hooks/use-templates-query";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { RenderJinjaTemplateHelpPanel } from "./help-panel";
import {
  buildRenderJinjaTemplateConfig,
  DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG,
  parseRenderJinjaTemplateConfig,
} from "./template-config";

function RenderJinjaTemplateConfigPanel({
  config,
  onChange,
  nodeId,
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const parsed = useMemo(() => parseRenderJinjaTemplateConfig(config), [config]);

  const { data, isLoading, isError } = useTemplatesQuery();

  const templates = useMemo(
    () => (data?.templates ?? []).filter((template) => template.template_type === "jinja2"),
    [data],
  );

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (config.output_key === undefined) {
      onChange(buildRenderJinjaTemplateConfig(config, DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG));
    }
  }, [nodeId, config, onChange]);

  const handleOutputKeyChange = useCallback(
    (value: string) => {
      onChange(buildRenderJinjaTemplateConfig(config, { output_key: value }));
    },
    [config, onChange],
  );

  const handleTemplateChange = useCallback(
    (value: string) => {
      onChange(buildRenderJinjaTemplateConfig(config, { template_id: Number(value) }));
    },
    [config, onChange],
  );

  const selectedValue = parsed.template_id !== null ? String(parsed.template_id) : "";
  const selectedMissing =
    parsed.template_id !== null &&
    !isLoading &&
    !isError &&
    !templates.some((template) => template.id === parsed.template_id);

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">output_key</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={parsed.output_key}
          onChange={(event) => handleOutputKeyChange(event.target.value)}
          placeholder="device_config"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Downstream steps reference this key in{" "}
          <span className="font-mono">device.parsed.{parsed.output_key || "output_key"}</span>.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">template</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            jinja2
          </Badge>
        </div>
        <Select
          value={selectedValue}
          onValueChange={handleTemplateChange}
          disabled={isLoading || templates.length === 0}
        >
          <SelectTrigger className="h-8 w-full text-xs">
            <SelectValue
              placeholder={isLoading ? "Loading templates…" : "Select a stored template"}
            />
          </SelectTrigger>
          <SelectContent>
            {templates.map((template) => (
              <SelectItem key={template.id} value={String(template.id)} className="text-xs">
                {template.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {isError ? (
          <p className="text-[11px] leading-4 text-destructive">
            Failed to load stored templates.
          </p>
        ) : null}
        {!isLoading && !isError && templates.length === 0 ? (
          <p className="text-[11px] leading-4 text-muted-foreground">
            No stored Jinja2 templates yet. Create one in the Templates section first.
          </p>
        ) : null}
        {selectedMissing ? (
          <p className="text-[11px] leading-4 text-destructive">
            The previously selected template no longer exists. Pick another one.
          </p>
        ) : null}
        <p className="text-[11px] leading-4 text-muted-foreground">
          The selected template is rendered once per device at workflow runtime.
        </p>
      </div>
    </div>
  );
}

export const RenderJinjaTemplatePlugin: PluginUIComponent = {
  ConfigPanel: RenderJinjaTemplateConfigPanel,
  HelpPanel: RenderJinjaTemplateHelpPanel,
};
