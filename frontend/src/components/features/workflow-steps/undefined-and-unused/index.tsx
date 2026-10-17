"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { BatfishDirectTargetFields } from "../shared/batfish-direct-target-fields";
import { UndefinedAndUnusedHelpPanel } from "./help-panel";

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function UndefinedAndUnusedConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const nodes = stringFromConfig(config, "nodes");
  const outputKey = stringFromConfig(config, "output_key");

  const handleFieldChange = useCallback(
    (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [key]: event.target.value });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">nodes</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={nodes}
          onChange={handleFieldChange("nodes")}
          placeholder="(this run's devices)"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          NodeSpecifier (e.g. &quot;/^r/&quot; or &quot;node1|node2&quot;). Leave blank to
          auto-scope to exactly this run&apos;s devices (by name, lowercased).
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">output_key</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={outputKey}
          onChange={handleFieldChange("output_key")}
          placeholder="undefined_and_unused"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Each device&apos;s own findings are written to device.parsed under
          &quot;&lt;output_key&gt;.undefined&quot; / &quot;&lt;output_key&gt;.unused&quot;; the
          full result is also stored as one workflow-level artifact under this key in the
          run&apos;s metadata.
        </p>
      </div>

      <BatfishDirectTargetFields config={config} onChange={onChange} />
    </div>
  );
}

export const UndefinedAndUnusedPlugin: PluginUIComponent = {
  ConfigPanel: UndefinedAndUnusedConfigPanel,
  HelpPanel: UndefinedAndUnusedHelpPanel,
};
