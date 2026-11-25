"use client";

import { useCallback, useEffect, useRef } from "react";

import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { CheckboxField } from "../shared/checkbox-field";
import { FromChangeRequestHelpPanel } from "./help-panel";

const DEFAULTS = {
  load_configs: true,
};

function bool(config: Record<string, unknown>, key: keyof typeof DEFAULTS): boolean {
  const value = config[key];
  return typeof value === "boolean" ? value : DEFAULTS[key];
}

function FromChangeRequestConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);

  useEffect(() => {
    if (initializedForNode.current === nodeId) return;
    initializedForNode.current = nodeId;
    if (config.load_configs === undefined) {
      onChange({ ...DEFAULTS, ...config });
    }
  }, [nodeId, config, onChange]);

  const patch = useCallback(
    (next: Record<string, unknown>) => onChange({ ...DEFAULTS, ...config, ...next }),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <p className="text-[11px] text-muted-foreground">
        First step of a deploy workflow. Rebuilds the device list from the change request
        that triggered this run — no upstream inventory step needed. Only works when the run
        was started by approving a change request.
      </p>

      <CheckboxField
        id={`${nodeId}-load-configs`}
        label="load_configs"
        description="Load each device's committed config file as running_config, so you can go straight to upload-config / configure-replace-config."
        checked={bool(config, "load_configs")}
        onCheckedChange={(checked) => patch({ load_configs: checked })}
      />
    </div>
  );
}

export const FromChangeRequestPlugin: PluginUIComponent = {
  ConfigPanel: FromChangeRequestConfigPanel,
  HelpPanel: FromChangeRequestHelpPanel,
};
