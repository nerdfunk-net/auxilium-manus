"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { ISESourceSelectDialog } from "../shared/ise-source-select-dialog";
import { iseSourceIdFromConfig, ISE_SOURCE_ID_KEY } from "../shared/ise-source-config";
import { UpdateIseTacacsKeyHelpPanel } from "./help-panel";

const NEW_KEY_KEY = "new_key";

function newKeyFromConfig(config: Record<string, unknown>): string {
  const raw = config[NEW_KEY_KEY];
  return typeof raw === "string" ? raw : "";
}

function UpdateIseTacacsKeyConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceId = useMemo(() => iseSourceIdFromConfig(config), [config]);
  const newKey = useMemo(() => newKeyFromConfig(config), [config]);

  const [sourceOpen, setSourceOpen] = useState(false);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [ISE_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleNewKeyChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [NEW_KEY_KEY]: event.target.value });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      {/* ise_source_id */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{ISE_SOURCE_ID_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            ise
          </Badge>
        </div>

        {sourceId ? (
          <p className="font-mono text-[11px] text-muted-foreground">{sourceId}</p>
        ) : (
          <p className="text-[11px] text-amber-600">Not configured</p>
        )}

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setSourceOpen(true)}
        >
          {sourceId ? "Edit Source" : "Configure Source"}
        </Button>
      </div>

      {/* new_key */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{NEW_KEY_KEY}</span>
        <Input
          className="h-9 font-mono text-xs"
          placeholder="MySecretKey123 or {custom.new_tacacs_key}"
          type="password"
          value={newKey}
          onChange={handleNewKeyChange}
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Fixed value, or <span className="font-mono">{"{path.to.value}"}</span> such as{" "}
          <span className="font-mono">{"{custom.new_tacacs_key}"}</span> or{" "}
          <span className="font-mono">{"{nautobot.custom_fields.tacacs_key}"}</span>,
          optionally with a fallback:{" "}
          <span className="font-mono">
            {"{custom.new_tacacs_key | default('fallback')}"}
          </span>
          .
        </p>
        {!newKey && <p className="text-[11px] text-amber-600">Not configured</p>}
      </div>

      <ISESourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />
    </div>
  );
}

export const UpdateIseTacacsKeyPlugin: PluginUIComponent = {
  ConfigPanel: UpdateIseTacacsKeyConfigPanel,
  HelpPanel: UpdateIseTacacsKeyHelpPanel,
};
