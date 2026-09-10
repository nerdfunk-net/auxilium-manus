"use client";

import { useCallback, useEffect, useRef } from "react";

import { Label } from "@/components/ui/label";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

const DEFAULTS = {
  checkout_branch: true,
  load_configs: true,
};

function bool(config: Record<string, unknown>, key: keyof typeof DEFAULTS): boolean {
  const value = config[key];
  return typeof value === "boolean" ? value : DEFAULTS[key];
}

function ToggleRow({
  id,
  label,
  hint,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-start gap-2">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 size-4 rounded border"
      />
      <div className="space-y-0.5">
        <Label htmlFor={id} className="font-mono text-xs font-medium">
          {label}
        </Label>
        <p className="text-[11px] text-muted-foreground">{hint}</p>
      </div>
    </div>
  );
}

function FromChangeRequestConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);

  useEffect(() => {
    if (initializedForNode.current === nodeId) return;
    initializedForNode.current = nodeId;
    if (config.checkout_branch === undefined || config.load_configs === undefined) {
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

      <ToggleRow
        id={`${nodeId}-checkout-branch`}
        label="checkout_branch"
        hint="Also check out the manus/cr-* branch into the repo working tree."
        checked={bool(config, "checkout_branch")}
        onChange={(checked) => patch({ checkout_branch: checked })}
      />
      <ToggleRow
        id={`${nodeId}-load-configs`}
        label="load_configs"
        hint="Load each device's committed config file as running_config, so you can go straight to upload-config / configure-replace-config."
        checked={bool(config, "load_configs")}
        onChange={(checked) => patch({ load_configs: checked })}
      />
    </div>
  );
}

export const FromChangeRequestPlugin: PluginUIComponent = {
  ConfigPanel: FromChangeRequestConfigPanel,
};
