"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

export interface FanOutApprovalConfig {
  enabled: boolean;
  batch_size: number;
  first_batch_auto: boolean;
}

export interface FanOutConfig {
  enabled: boolean;
  mode: "per_device" | "chunked";
  chunk_size: number;
  max_concurrency: number;
  approval: FanOutApprovalConfig;
}

export const DEFAULT_FAN_OUT_APPROVAL: FanOutApprovalConfig = {
  enabled: false,
  batch_size: 1,
  first_batch_auto: true,
};

export const DEFAULT_FAN_OUT: FanOutConfig = {
  enabled: false,
  mode: "per_device",
  chunk_size: 1,
  max_concurrency: 0,
  approval: DEFAULT_FAN_OUT_APPROVAL,
};

function approvalFromConfig(raw: unknown): FanOutApprovalConfig {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const a = raw as Record<string, unknown>;
    return {
      enabled: Boolean(a.enabled),
      batch_size: typeof a.batch_size === "number" ? Math.max(1, a.batch_size) : 1,
      first_batch_auto: typeof a.first_batch_auto === "boolean" ? a.first_batch_auto : true,
    };
  }
  return DEFAULT_FAN_OUT_APPROVAL;
}

export function fanOutFromConfig(config: Record<string, unknown>): FanOutConfig {
  const raw = config.fan_out;
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const f = raw as Record<string, unknown>;
    return {
      enabled: Boolean(f.enabled),
      mode: f.mode === "chunked" ? "chunked" : "per_device",
      chunk_size: typeof f.chunk_size === "number" ? Math.max(1, f.chunk_size) : 1,
      max_concurrency:
        typeof f.max_concurrency === "number" ? Math.max(0, f.max_concurrency) : 0,
      approval: approvalFromConfig(f.approval),
    };
  }
  return DEFAULT_FAN_OUT;
}

interface FanOutConfigSectionProps {
  value: FanOutConfig;
  onChange: (patch: Partial<FanOutConfig>) => void;
}

/** Shared fan-out configuration block used by every inventory step's
 * ConfigPanel (get-nautobot-devices, get-git-devices, get-ise-devices,
 * get-from-list). See doc/WORKFLOW-STEPS.md "Fan-out execution" and
 * doc/WAIT-AND-RUN.md for the approval-gate semantics. */
export function FanOutConfigSection({ value, onChange }: FanOutConfigSectionProps) {
  const handleApprovalChange = (patch: Partial<FanOutApprovalConfig>) => {
    onChange({ approval: { ...value.approval, ...patch } });
  };

  return (
    <div className="space-y-2 border-t pt-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs font-medium">fan_out</span>
        <Switch
          checked={value.enabled}
          onCheckedChange={(checked) => onChange({ enabled: checked })}
        />
      </div>
      <p className="text-[11px] text-muted-foreground">
        Process each device (or chunk) as an independent Hatchet child workflow.
      </p>

      {value.enabled && (
        <div className="space-y-2 pl-1">
          <div className="space-y-1">
            <Label className="text-[11px] text-muted-foreground">Mode</Label>
            <Select
              value={value.mode}
              onValueChange={(v) => onChange({ mode: v as "per_device" | "chunked" })}
            >
              <SelectTrigger className="h-7 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="per_device">Per device (1 child per device)</SelectItem>
                <SelectItem value="chunked">Chunked (N devices per child)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {value.mode === "chunked" && (
            <div className="space-y-1">
              <Label className="text-[11px] text-muted-foreground">
                Chunk size (devices per child)
              </Label>
              <Input
                type="number"
                min={1}
                className="h-7 font-mono text-xs"
                value={value.chunk_size}
                onChange={(e) =>
                  onChange({ chunk_size: Math.max(1, Number(e.target.value)) })
                }
              />
            </div>
          )}

          <div className="space-y-1">
            <Label className="text-[11px] text-muted-foreground">
              Max concurrency (0 = unlimited, 1 = sequential)
            </Label>
            <Input
              type="number"
              min={0}
              className="h-7 font-mono text-xs"
              value={value.max_concurrency}
              onChange={(e) =>
                onChange({ max_concurrency: Math.max(0, Number(e.target.value)) })
              }
            />
          </div>

          <div className="space-y-2 border-t pt-2">
            <div className="flex items-center justify-between">
              <Label className="text-[11px] text-muted-foreground">
                Wait for approval between batches
              </Label>
              <Switch
                checked={value.approval.enabled}
                onCheckedChange={(checked) => handleApprovalChange({ enabled: checked })}
              />
            </div>

            {value.approval.enabled && (
              <div className="space-y-2 pl-1">
                <div className="space-y-1">
                  <Label className="text-[11px] text-muted-foreground">Groups per batch</Label>
                  <Input
                    type="number"
                    min={1}
                    className="h-7 font-mono text-xs"
                    value={value.approval.batch_size}
                    onChange={(e) =>
                      handleApprovalChange({
                        batch_size: Math.max(1, Number(e.target.value)),
                      })
                    }
                  />
                  <p className="text-[10px] text-muted-foreground">
                    per_device mode: devices per batch · chunked mode: chunks per batch
                  </p>
                </div>

                <div className="flex items-center justify-between">
                  <Label className="text-[11px] text-muted-foreground">
                    Run first batch immediately
                  </Label>
                  <Switch
                    checked={value.approval.first_batch_auto}
                    onCheckedChange={(checked) =>
                      handleApprovalChange({ first_batch_auto: checked })
                    }
                  />
                </div>

                <p className="text-[10px] text-muted-foreground">
                  Runs waiting for approval expire after 24h, same as any other run.
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
