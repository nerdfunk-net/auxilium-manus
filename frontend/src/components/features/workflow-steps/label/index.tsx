"use client";

import { useCallback, useEffect, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";
import { DEFAULT_LABEL_CONFIG } from "@/components/features/workflows/types/workflow-canvas";

import { LabelHelpPanel } from "./help-panel";

function buildLabelConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    text:
      typeof config.text === "string" ? config.text : DEFAULT_LABEL_CONFIG.text,
    font_size:
      typeof config.font_size === "number"
        ? config.font_size
        : DEFAULT_LABEL_CONFIG.font_size,
    font_family:
      typeof config.font_family === "string"
        ? config.font_family
        : DEFAULT_LABEL_CONFIG.font_family,
    color:
      typeof config.color === "string"
        ? config.color
        : DEFAULT_LABEL_CONFIG.color,
    width:
      typeof config.width === "number"
        ? config.width
        : DEFAULT_LABEL_CONFIG.width,
    height:
      typeof config.height === "number"
        ? config.height
        : DEFAULT_LABEL_CONFIG.height,
    ...patch,
  };
}

function LabelConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const text =
    typeof config.text === "string" ? config.text : DEFAULT_LABEL_CONFIG.text;
  const fontSize =
    typeof config.font_size === "number"
      ? config.font_size
      : DEFAULT_LABEL_CONFIG.font_size;
  const fontFamily =
    typeof config.font_family === "string"
      ? config.font_family
      : DEFAULT_LABEL_CONFIG.font_family;
  const color =
    typeof config.color === "string" ? config.color : DEFAULT_LABEL_CONFIG.color;
  const width =
    typeof config.width === "number" ? config.width : DEFAULT_LABEL_CONFIG.width;
  const height =
    typeof config.height === "number"
      ? config.height
      : DEFAULT_LABEL_CONFIG.height;

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!config.text && !config.font_size) {
      onChange(buildLabelConfig(config));
    }
  }, [nodeId, config, onChange]);

  const patch = useCallback(
    (partial: Record<string, unknown>) => {
      onChange(buildLabelConfig(config, partial));
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">text</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={text}
          onChange={(event) => patch({ text: event.target.value })}
          placeholder="Label"
          className="h-8 text-xs"
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">font_size</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            px
          </Badge>
        </div>
        <Input
          type="number"
          min={8}
          max={96}
          value={fontSize}
          onChange={(event) =>
            patch({ font_size: Number(event.target.value) || 16 })
          }
          className="h-8 font-mono text-xs"
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">font_family</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            sans | serif | mono
          </Badge>
        </div>
        <Select
          value={fontFamily}
          onValueChange={(value) => patch({ font_family: value })}
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="sans">Sans</SelectItem>
            <SelectItem value="serif">Serif</SelectItem>
            <SelectItem value="mono">Mono</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">color</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            hex
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <Input
            type="color"
            value={color}
            onChange={(event) => patch({ color: event.target.value })}
            className="h-8 w-12 cursor-pointer p-1"
            aria-label="Text color"
          />
          <Input
            value={color}
            onChange={(event) => patch({ color: event.target.value })}
            className="h-8 font-mono text-xs"
            placeholder="#0f172a"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1.5">
          <Label className="font-mono text-[11px] text-muted-foreground">
            width
          </Label>
          <Input
            type="number"
            min={40}
            value={width}
            onChange={(event) =>
              patch({ width: Number(event.target.value) || 40 })
            }
            className="h-8 font-mono text-xs"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="font-mono text-[11px] text-muted-foreground">
            height
          </Label>
          <Input
            type="number"
            min={24}
            value={height}
            onChange={(event) =>
              patch({ height: Number(event.target.value) || 24 })
            }
            className="h-8 font-mono text-xs"
          />
        </div>
      </div>
      <p className="text-[11px] leading-4 text-muted-foreground">
        Canvas decoration only — not executed and not connectable. You can also
        resize the label on the canvas.
      </p>
    </div>
  );
}

export const LabelPlugin = {
  ConfigPanel: LabelConfigPanel,
  HelpPanel: LabelHelpPanel,
};
