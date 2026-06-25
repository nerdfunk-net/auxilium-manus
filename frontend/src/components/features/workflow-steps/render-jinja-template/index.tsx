"use client";

import { FileCode2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { TemplateEditorDialog } from "./template-editor-dialog";
import {
  buildRenderJinjaTemplateConfig,
  DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG,
  parseRenderJinjaTemplateConfig,
} from "./template-config";

function RenderJinjaTemplateConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes = [],
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorSession, setEditorSession] = useState(0);
  const parsed = useMemo(() => parseRenderJinjaTemplateConfig(config), [config]);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!config.output_key && !config.template) {
      onChange(buildRenderJinjaTemplateConfig(config, DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG));
    }
  }, [nodeId, config, onChange]);

  const handleOutputKeyChange = useCallback(
    (value: string) => {
      onChange(buildRenderJinjaTemplateConfig(config, { output_key: value }));
    },
    [config, onChange],
  );

  const handleEditorSave = useCallback(
    (patch: Partial<typeof parsed>) => {
      onChange(buildRenderJinjaTemplateConfig(config, patch));
    },
    [config, onChange],
  );

  const templateLines = parsed.template.trim().split("\n").length;

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
        <p className="text-[11px] text-muted-foreground">
          {templateLines} line{templateLines === 1 ? "" : "s"} configured
        </p>
        <Button
          type="button"
          variant="outline"
          className="h-8 w-full justify-start text-xs"
          onClick={() => {
            setEditorSession((current) => current + 1);
            setEditorOpen(true);
          }}
        >
          <FileCode2 className="mr-2 size-3.5" />
          Open template editor
        </Button>
      </div>

      <TemplateEditorDialog
        key={editorSession}
        open={editorOpen}
        config={config}
        workflowNodes={workflowNodes}
        onClose={() => setEditorOpen(false)}
        onSave={handleEditorSave}
      />
    </div>
  );
}

export const RenderJinjaTemplatePlugin: PluginUIComponent = {
  ConfigPanel: RenderJinjaTemplateConfigPanel,
};
