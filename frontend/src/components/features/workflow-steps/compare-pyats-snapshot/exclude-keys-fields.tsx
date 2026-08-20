"use client";

import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

import {
  buildComparePyatsSnapshotConfig,
  excludeKeysFromConfig,
} from "./compare-pyats-config";

export interface ExcludeKeysFieldsProps {
  nodeId: string;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
}

export function ExcludeKeysFields({ nodeId, config, onChange }: ExcludeKeysFieldsProps) {
  const excludeKeysInitializedFor = useRef<string | null>(null);
  const [excludeKeysText, setExcludeKeysText] = useState("");

  useEffect(() => {
    if (excludeKeysInitializedFor.current === nodeId) {
      return;
    }
    excludeKeysInitializedFor.current = nodeId;
    setExcludeKeysText(excludeKeysFromConfig(config).join(", "));
  }, [nodeId, config]);

  const handleExcludeKeysChange = (value: string) => {
    setExcludeKeysText(value);
    const excludeKeys = value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    onChange(buildComparePyatsSnapshotConfig(config, { exclude_keys: excludeKeys }));
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">exclude_keys</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          optional
        </Badge>
      </div>
      <Input
        value={excludeKeysText}
        onChange={(event) => handleExcludeKeysChange(event.target.value)}
        placeholder="updated, last_change, uptime"
        className="h-8 font-mono text-xs"
      />
      <p className="text-[11px] text-muted-foreground">
        Comma-separated dict keys to ignore during the diff (passed to Genie&rsquo;s{" "}
        <span className="font-mono">Diff(..., exclude=[...])</span>). Genie does{" "}
        <span className="font-medium text-foreground">not</span> ignore volatile fields like{" "}
        <span className="font-mono">updated</span> automatically — list any keys whose values
        change on their own (timers, counters, uptime) to avoid false mismatches.
      </p>
    </div>
  );
}
