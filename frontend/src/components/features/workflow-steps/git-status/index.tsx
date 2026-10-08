"use client";

import { useCallback } from "react";

import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { GitSourceConfigPanel } from "@/components/features/workflow-steps/shared/git-source-config-panel";
import { GitStatusHelpPanel } from "./help-panel";

interface ToggleField {
  key: string;
  hint: string;
}

const TOGGLE_FIELDS: readonly ToggleField[] = [
  { key: "fetch_remote", hint: "Fetch from origin first so ahead/behind is current." },
  { key: "check_uncommitted", hint: "Modified or staged tracked files make it dirty." },
  { key: "check_untracked", hint: "Untracked files make it dirty." },
  {
    key: "check_sync",
    hint: "Local commits not on origin, commits missing locally, or a branch mismatch make it dirty.",
  },
];

function GitStatusConfigPanel(props: PluginConfigPanelProps) {
  const { config, onChange, nodeId } = props;

  const handleToggle = useCallback(
    (key: string, checked: boolean) => {
      onChange({ ...config, [key]: checked });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <GitSourceConfigPanel
        {...props}
        description="Inspect the local working tree of the selected Git repository."
        showChangeRequestBranchToggle
      />
      <div className="space-y-3 border-t pt-3">
        {TOGGLE_FIELDS.map(({ key, hint }) => (
          <div key={key} className="space-y-0.5">
            <div className="flex items-center justify-between">
              <Label htmlFor={`${nodeId}-${key}`} className="font-mono text-xs font-medium">
                {key}
              </Label>
              <Switch
                id={`${nodeId}-${key}`}
                checked={config[key] !== false}
                onCheckedChange={(checked) => handleToggle(key, checked)}
              />
            </div>
            <p className="text-[11px] text-muted-foreground">{hint}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export const GitStatusPlugin: PluginUIComponent = {
  ConfigPanel: GitStatusConfigPanel,
  HelpPanel: GitStatusHelpPanel,
};
