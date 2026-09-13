"use client";

import { useCallback, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { BatfishSourceSelectDialog } from "./batfish-source-select-dialog";
import { batfishSourceIdFromConfig, BATFISH_SOURCE_ID_KEY } from "./batfish-source-config";

const NETWORK_KEY = "network";
const SNAPSHOT_KEY = "snapshot";

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

interface BatfishDirectTargetFieldsProps {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
}

/**
 * Shared "query a network directly" block for the three Batfish query steps
 * (Routing Table, Path Check, ACL Check): optional batfish_source_id +
 * network (+ snapshot) fields that bypass an upstream Init Batfish
 * Snapshot step's run metadata when both source and network are set.
 */
export function BatfishDirectTargetFields({ config, onChange }: BatfishDirectTargetFieldsProps) {
  const sourceId = batfishSourceIdFromConfig(config);
  const network = stringFromConfig(config, NETWORK_KEY);
  const snapshot = stringFromConfig(config, SNAPSHOT_KEY);
  const [sourceOpen, setSourceOpen] = useState(false);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => onChange({ ...config, [BATFISH_SOURCE_ID_KEY]: newSourceId }),
    [config, onChange],
  );

  const handleFieldChange = useCallback(
    (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [key]: event.target.value });
    },
    [config, onChange],
  );

  return (
    <div className="space-y-4 border-t pt-3">
      <div className="space-y-0.5">
        <span className="font-mono text-xs font-medium">Query a network directly</span>
        <p className="text-[11px] leading-4 text-muted-foreground">
          Optional. Leave blank to use the snapshot from an upstream Init Batfish Snapshot
          step in this run. Set Source and Network together to query any network directly —
          this always overrides the run&apos;s own snapshot when set.
        </p>
      </div>

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
          <p className="text-[11px] text-muted-foreground">Not set</p>
        )}
        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setSourceOpen(true)}
        >
          {sourceId ? "Change source" : "Choose source"}
        </Button>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{NETWORK_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={network}
          onChange={handleFieldChange(NETWORK_KEY)}
          placeholder="e.g. manus-production"
          className="h-8 font-mono text-xs"
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{SNAPSHOT_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={snapshot}
          onChange={handleFieldChange(SNAPSHOT_KEY)}
          placeholder="(most recent)"
          className="h-8 font-mono text-xs"
        />
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
