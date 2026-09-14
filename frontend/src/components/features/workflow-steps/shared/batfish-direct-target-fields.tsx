"use client";

import { useCallback, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useBatfishNetworksQuery } from "@/hooks/queries/use-batfish-networks-query";
import { useBatfishSnapshotsQuery } from "@/hooks/queries/use-batfish-snapshots-query";

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
 * Shared "query a network directly" block for the Batfish query/fact steps
 * (Routing Table, Path Check, ACL Check, Validate Facts, Extract Facts):
 * optional batfish_source_id + network (+ snapshot) fields that bypass an
 * upstream Init Batfish Snapshot step's run metadata when both source and
 * network are set. Network/snapshot are fetched dropdowns once a source is
 * chosen (GET .../networks, .../networks/{network}/snapshots), falling back
 * to free-text entry when the coordinator has none, is unreachable, or the
 * operator wants to type a value that hasn't been created yet.
 */
export function BatfishDirectTargetFields({ config, onChange }: BatfishDirectTargetFieldsProps) {
  const sourceId = batfishSourceIdFromConfig(config);
  const network = stringFromConfig(config, NETWORK_KEY);
  const snapshot = stringFromConfig(config, SNAPSHOT_KEY);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [networkManual, setNetworkManual] = useState(false);
  const [snapshotManual, setSnapshotManual] = useState(false);

  const { data: networksData } = useBatfishNetworksQuery(sourceId);
  const networks = networksData?.networks ?? [];
  const { data: snapshotsData } = useBatfishSnapshotsQuery(sourceId, network);
  const snapshots = snapshotsData?.snapshots ?? [];

  const networkPickerAvailable = sourceId && networks.length > 0;
  const snapshotPickerAvailable = sourceId && Boolean(network) && snapshots.length > 0;
  const showNetworkPicker = networkPickerAvailable && !networkManual;
  const showSnapshotPicker = snapshotPickerAvailable && !snapshotManual;

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => onChange({ ...config, [BATFISH_SOURCE_ID_KEY]: newSourceId }),
    [config, onChange],
  );

  // Locks into manual mode on the first keystroke -- otherwise, if the
  // networks/snapshots list finishes loading mid-typing, the picker swaps
  // back in under the user's cursor (losing focus and, in some browsers,
  // triggering an autofill-suggestions dropdown of every partial value
  // typed so far).
  const handleNetworkInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      setNetworkManual(true);
      onChange({ ...config, [NETWORK_KEY]: event.target.value });
    },
    [config, onChange],
  );

  const handleSnapshotInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      setSnapshotManual(true);
      onChange({ ...config, [SNAPSHOT_KEY]: event.target.value });
    },
    [config, onChange],
  );

  const handleNetworkSelect = useCallback(
    (value: string) => {
      // Clear the snapshot when picking a different network -- a snapshot
      // name from the previous network wouldn't be valid here.
      onChange({ ...config, [NETWORK_KEY]: value, [SNAPSHOT_KEY]: "" });
    },
    [config, onChange],
  );

  const handleSnapshotSelect = useCallback(
    (value: string) => onChange({ ...config, [SNAPSHOT_KEY]: value }),
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
        {showNetworkPicker ? (
          <Select value={network || ""} onValueChange={handleNetworkSelect}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Choose a network…" />
            </SelectTrigger>
            <SelectContent>
              {networks.map((name) => (
                <SelectItem key={name} value={name}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input
            value={network}
            onChange={handleNetworkInputChange}
            placeholder="e.g. manus-production"
            className="h-8 font-mono text-xs"
            autoComplete="off"
          />
        )}
        {networkPickerAvailable ? (
          <button
            type="button"
            onClick={() => setNetworkManual((current) => !current)}
            className="text-[10px] text-muted-foreground underline hover:text-foreground"
          >
            {networkManual ? "Choose from list" : "Enter manually"}
          </button>
        ) : null}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{SNAPSHOT_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        {showSnapshotPicker ? (
          <Select value={snapshot || ""} onValueChange={handleSnapshotSelect}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="(most recent)" />
            </SelectTrigger>
            <SelectContent>
              {snapshots.map((snap) => (
                <SelectItem key={snap.name} value={snap.name}>
                  {snap.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input
            value={snapshot}
            onChange={handleSnapshotInputChange}
            placeholder="(most recent)"
            className="h-8 font-mono text-xs"
            autoComplete="off"
          />
        )}
        {snapshotPickerAvailable ? (
          <button
            type="button"
            onClick={() => setSnapshotManual((current) => !current)}
            className="text-[10px] text-muted-foreground underline hover:text-foreground"
          >
            {snapshotManual ? "Choose from list" : "Enter manually"}
          </button>
        ) : sourceId && !network ? (
          <p className="text-[11px] leading-4 text-muted-foreground">
            Pick or enter a network above first.
          </p>
        ) : null}
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
