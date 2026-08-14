"use client";

import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight, Server, XCircle } from "lucide-react";
import { useMemo, useState } from "react";

import { cn } from "@/lib/utils";
import type { DeviceContext } from "@/lib/workflow-context-types";

import { DeviceCard } from "./device-card";

/** Lists with more than this many devices start collapsed. */
const DEVICES_COLLAPSE_THRESHOLD = 5;

function summarizeDeviceStatuses(devices: DeviceContext[]) {
  return devices.reduce(
    (counts, device) => {
      if (device.status === "ok") {
        counts.ok += 1;
      } else if (device.status === "failed") {
        counts.failed += 1;
      } else {
        counts.other += 1;
      }
      return counts;
    },
    { ok: 0, failed: 0, other: 0 },
  );
}

function DeviceStatusSummary({ devices }: { devices: DeviceContext[] }) {
  const counts = useMemo(() => summarizeDeviceStatuses(devices), [devices]);
  const parts: string[] = [];
  if (counts.ok > 0) {
    parts.push(`${counts.ok} ok`);
  }
  if (counts.failed > 0) {
    parts.push(`${counts.failed} failed`);
  }
  if (counts.other > 0) {
    parts.push(`${counts.other} other`);
  }

  return (
    <span className="font-normal normal-case tracking-normal">
      {parts.length > 0 ? parts.join(" · ") : "no status recorded"}
    </span>
  );
}

export function DevicesSection({
  devices,
  runId,
  compact = false,
}: {
  devices: DeviceContext[];
  runId?: number | null;
  compact?: boolean;
}) {
  const [expanded, setExpanded] = useState(
    () => !compact && devices.length <= DEVICES_COLLAPSE_THRESHOLD,
  );
  const scrollDeviceList = devices.length > DEVICES_COLLAPSE_THRESHOLD;

  return (
    <div className="min-w-0">
      <button
        type="button"
        className="mb-2 flex w-full min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
      >
        {expanded ? (
          <ChevronDown className="size-3.5 shrink-0" aria-hidden />
        ) : (
          <ChevronRight className="size-3.5 shrink-0" aria-hidden />
        )}
        <Server className="size-3.5 shrink-0" aria-hidden />
        <span>Devices ({devices.length})</span>
        {!expanded && devices.length > 0 ? (
          <>
            <span className="font-normal normal-case tracking-normal text-muted-foreground/70">
              —
            </span>
            <DeviceStatusSummary devices={devices} />
          </>
        ) : null}
      </button>

      {devices.length === 0 ? (
        <p className="text-xs text-muted-foreground">No devices on this outcome path.</p>
      ) : expanded ? (
        <div
          className={cn(
            "min-w-0 space-y-2",
            scrollDeviceList && "max-h-96 overflow-y-auto pr-1",
          )}
        >
          {devices.map((device) => (
            <DeviceCard key={device.id} device={device} runId={runId} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function DeviceStatusIcon({ status }: { status: DeviceContext["status"] }) {
  switch (status) {
    case "ok":
      return <CheckCircle2 className="size-3.5 text-success-foreground" />;
    case "failed":
      return <XCircle className="size-3.5 text-destructive" />;
    default:
      return <AlertCircle className="size-3.5 text-muted-foreground" />;
  }
}
