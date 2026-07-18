"use client";

import { ArrowDown, ArrowUp } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { ISESourceSelectDialog } from "../shared/ise-source-select-dialog";
import { iseSourceIdFromConfig, ISE_SOURCE_ID_KEY } from "../shared/ise-source-config";

type TierType =
  | "name_exact_32"
  | "name_any"
  | "location_group"
  | "ip_prefix_scan"
  | "ip_range_scan";

interface PriorityItem {
  type: TierType;
  enabled: boolean;
}

const PRIORITY_KEY = "priority";
const LOCATION_GROUP_PREFIX_KEY = "location_group_prefix";

const VALID_TIER_TYPES: readonly TierType[] = [
  "name_exact_32",
  "name_any",
  "location_group",
  "ip_prefix_scan",
  "ip_range_scan",
];

const DEFAULT_PRIORITY: PriorityItem[] = VALID_TIER_TYPES.map((type) => ({
  type,
  enabled: true,
}));

const TIER_LABELS: Record<TierType, string> = {
  name_exact_32: "Device name (ISE entry must be /32)",
  name_any: "Device name (any netmask)",
  location_group: "Nautobot location as ISE group",
  ip_prefix_scan: "IP prefix scan (/32 down to /8)",
  ip_range_scan: "IP range/wildcard scan (full inventory)",
};

const TIER_DESCRIPTIONS: Record<TierType, string> = {
  name_exact_32:
    "Look up the device by name in ISE; only accept the match if its configured netmask is exactly /32.",
  name_any: "Look up the device by name in ISE; accept any configured netmask.",
  location_group:
    "Build an ISE Location group name from the device's Nautobot location and look up devices in that group.",
  ip_prefix_scan:
    "Match the device's primary IPv4 against ISE entries, narrowing the netmask from /32 down to /8. Cheap, but only finds entries stored as a clean CIDR network address.",
  ip_range_scan:
    "Fallback for ISE entries stored as a range (e.g. 192.168.178.1-254) or wildcard (e.g. 192.168.178.*) instead of a clean CIDR address. Scans the full device inventory, so it's the most expensive tier — keep it last.",
};

function isPriorityItem(value: unknown): value is PriorityItem {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return (
    typeof item.type === "string" &&
    (VALID_TIER_TYPES as readonly string[]).includes(item.type) &&
    typeof item.enabled === "boolean"
  );
}

function priorityFromConfig(config: Record<string, unknown>): PriorityItem[] {
  const raw = config[PRIORITY_KEY];
  if (Array.isArray(raw) && raw.length === VALID_TIER_TYPES.length && raw.every(isPriorityItem)) {
    const types = new Set((raw as PriorityItem[]).map((item) => item.type));
    if (types.size === VALID_TIER_TYPES.length) {
      return raw as PriorityItem[];
    }
  }
  return DEFAULT_PRIORITY;
}

function locationGroupPrefixFromConfig(config: Record<string, unknown>): string {
  const raw = config[LOCATION_GROUP_PREFIX_KEY];
  return typeof raw === "string" ? raw : "All Locations";
}

function GetIseTacacsKeyConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceId = useMemo(() => iseSourceIdFromConfig(config), [config]);
  const priority = useMemo(() => priorityFromConfig(config), [config]);
  const locationGroupPrefix = useMemo(() => locationGroupPrefixFromConfig(config), [config]);

  const [sourceOpen, setSourceOpen] = useState(false);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [ISE_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleLocationGroupPrefixChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [LOCATION_GROUP_PREFIX_KEY]: event.target.value });
    },
    [config, onChange],
  );

  const handleToggle = useCallback(
    (index: number, enabled: boolean) => {
      const nextPriority = priority.map((item, itemIndex) =>
        itemIndex === index ? { ...item, enabled } : item,
      );
      onChange({ ...config, [PRIORITY_KEY]: nextPriority });
    },
    [config, onChange, priority],
  );

  const handleMove = useCallback(
    (index: number, direction: -1 | 1) => {
      const targetIndex = index + direction;
      if (targetIndex < 0 || targetIndex >= priority.length) return;
      const nextPriority = [...priority];
      const temp = nextPriority[index];
      nextPriority[index] = nextPriority[targetIndex];
      nextPriority[targetIndex] = temp;
      onChange({ ...config, [PRIORITY_KEY]: nextPriority });
    },
    [config, onChange, priority],
  );

  const noTierEnabled = !priority.some((item) => item.enabled);

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

      {/* priority */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{PRIORITY_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            ordered
          </Badge>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Tried top to bottom until one lookup finds a TACACS+ key.
        </p>

        <div className="space-y-2">
          {priority.map((item, index) => (
            <div key={item.type} className="space-y-1.5 rounded-lg border p-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1 space-y-0.5">
                  <p className="text-xs font-medium leading-snug">{TIER_LABELS[item.type]}</p>
                  <p className="text-[11px] leading-4 text-muted-foreground">
                    {TIER_DESCRIPTIONS[item.type]}
                  </p>
                </div>
                <Switch
                  checked={item.enabled}
                  onCheckedChange={(checked) => handleToggle(index, checked)}
                />
              </div>

              {item.type === "location_group" && (
                <div className="space-y-1 pl-0.5">
                  <Label className="text-[11px] text-muted-foreground">
                    {LOCATION_GROUP_PREFIX_KEY}
                  </Label>
                  <Input
                    className="h-7 font-mono text-xs"
                    placeholder="All Locations"
                    value={locationGroupPrefix}
                    onChange={handleLocationGroupPrefixChange}
                  />
                </div>
              )}

              <div className="flex justify-end gap-1">
                <Button
                  className="size-6"
                  size="icon"
                  type="button"
                  variant="ghost"
                  disabled={index === 0}
                  onClick={() => handleMove(index, -1)}
                  title="Move up"
                  aria-label="Move up"
                >
                  <ArrowUp className="size-3.5" aria-hidden />
                </Button>
                <Button
                  className="size-6"
                  size="icon"
                  type="button"
                  variant="ghost"
                  disabled={index === priority.length - 1}
                  onClick={() => handleMove(index, 1)}
                  title="Move down"
                  aria-label="Move down"
                >
                  <ArrowDown className="size-3.5" aria-hidden />
                </Button>
              </div>
            </div>
          ))}
        </div>

        {noTierEnabled && (
          <p className="text-[11px] text-amber-600">At least one priority tier must be enabled.</p>
        )}
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

export const GetIseTacacsKeyPlugin: PluginUIComponent = {
  ConfigPanel: GetIseTacacsKeyConfigPanel,
};
