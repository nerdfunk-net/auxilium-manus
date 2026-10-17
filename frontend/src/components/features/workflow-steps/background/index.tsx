"use client";

import { useCallback, useEffect, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";
import { DEFAULT_BACKGROUND_CONFIG } from "@/components/features/workflows/types/workflow-canvas";

import { BackgroundHelpPanel } from "./help-panel";

function buildBackgroundConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    color:
      typeof config.color === "string"
        ? config.color
        : DEFAULT_BACKGROUND_CONFIG.color,
    width:
      typeof config.width === "number"
        ? config.width
        : DEFAULT_BACKGROUND_CONFIG.width,
    height:
      typeof config.height === "number"
        ? config.height
        : DEFAULT_BACKGROUND_CONFIG.height,
    ...patch,
  };
}

function BackgroundConfigPanel({
  config,
  onChange,
  nodeId,
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const color =
    typeof config.color === "string"
      ? config.color
      : DEFAULT_BACKGROUND_CONFIG.color;
  const width =
    typeof config.width === "number"
      ? config.width
      : DEFAULT_BACKGROUND_CONFIG.width;
  const height =
    typeof config.height === "number"
      ? config.height
      : DEFAULT_BACKGROUND_CONFIG.height;

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!config.color && !config.width) {
      onChange(buildBackgroundConfig(config));
    }
  }, [nodeId, config, onChange]);

  const patch = useCallback(
    (partial: Record<string, unknown>) => {
      onChange(buildBackgroundConfig(config, partial));
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
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
            aria-label="Background color"
          />
          <Input
            value={color}
            onChange={(event) => patch({ color: event.target.value })}
            className="h-8 font-mono text-xs"
            placeholder="#e2e8f0"
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
            min={80}
            value={width}
            onChange={(event) =>
              patch({ width: Number(event.target.value) || 80 })
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
            min={80}
            value={height}
            onChange={(event) =>
              patch({ height: Number(event.target.value) || 80 })
            }
            className="h-8 font-mono text-xs"
          />
        </div>
      </div>
      <p className="text-[11px] leading-4 text-muted-foreground">
        Drawn behind other steps. Canvas decoration only — not executed and not
        connectable. Resize on the canvas or set exact dimensions here.
      </p>
    </div>
  );
}

export const BackgroundPlugin = {
  ConfigPanel: BackgroundConfigPanel,
  HelpPanel: BackgroundHelpPanel,
};
