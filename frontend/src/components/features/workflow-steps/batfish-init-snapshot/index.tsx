"use client";

import { useCallback, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { BatfishSourceSelectDialog } from "../shared/batfish-source-select-dialog";
import {
  batfishSourceIdFromConfig,
  BATFISH_SOURCE_ID_KEY,
} from "../shared/batfish-source-config";
import { BatfishInitSnapshotHelpPanel } from "./help-panel";

const RETAIN_SNAPSHOTS_KEY = "retain_snapshots";

function retainSnapshotsFromConfig(config: Record<string, unknown>): string {
  const raw = config[RETAIN_SNAPSHOTS_KEY];
  return typeof raw === "number" ? String(raw) : typeof raw === "string" ? raw : "";
}

function BatfishInitSnapshotConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceId = batfishSourceIdFromConfig(config);
  const retainSnapshots = retainSnapshotsFromConfig(config);

  const [sourceOpen, setSourceOpen] = useState(false);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [BATFISH_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleRetainSnapshotsChange = useCallback(
    (value: string) => {
      const parsed = Number.parseInt(value, 10);
      onChange({
        ...config,
        [RETAIN_SNAPSHOTS_KEY]: Number.isNaN(parsed) ? value : parsed,
      });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{BATFISH_SOURCE_ID_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            batfish
          </Badge>
        </div>

        {sourceId ? (
          <p className="font-mono text-[11px] text-muted-foreground">{sourceId}</p>
        ) : (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
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

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{RETAIN_SNAPSHOTS_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            integer
          </Badge>
        </div>
        <Input
          type="number"
          min={0}
          value={retainSnapshots}
          onChange={(event) => handleRetainSnapshotsChange(event.target.value)}
          placeholder="5"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Snapshots for this workflow beyond the N most recent are deleted
          after each successful run.
        </p>
      </div>

      <BatfishSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />
    </div>
  );
}

export const BatfishInitSnapshotPlugin: PluginUIComponent = {
  ConfigPanel: BatfishInitSnapshotConfigPanel,
  HelpPanel: BatfishInitSnapshotHelpPanel,
};
