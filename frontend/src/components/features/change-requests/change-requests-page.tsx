"use client";

import { useMemo, useState } from "react";
import { GitPullRequestArrow, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";

import { ChangeRequestDetailPane } from "./components/change-request-detail-pane";
import { ChangeRequestStatusBadge } from "./components/change-request-status-badge";
import { useChangeRequestsQuery } from "./hooks/use-change-requests-query";
import type { ChangeRequestSummary } from "./types/change-request";

function diffSummary(item: ChangeRequestSummary): string {
  const stats = item.diff_stats;
  if (!stats) return "";
  const parts: string[] = [];
  if (stats.additions != null) parts.push(`+${stats.additions}`);
  if (stats.deletions != null) parts.push(`-${stats.deletions}`);
  return parts.join(" ");
}

function relativeAge(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function ChangeRequestsPage() {
  const { data, isLoading } = useChangeRequestsQuery();
  const items = useMemo(() => data?.items ?? [], [data]);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Derive the active selection: an explicit pick that still exists, else the
  // first row. Keeps selection stable across polls without a setState effect.
  const effectiveSelectedId =
    selectedId != null && items.some((item) => item.id === selectedId)
      ? selectedId
      : (items[0]?.id ?? null);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center gap-4 border-b px-6 py-4">
        <div className="flex size-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <GitPullRequestArrow className="size-5" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-foreground">Change Requests</h1>
          <p className="text-sm text-muted-foreground">
            Review staged config changes before they deploy to devices.
          </p>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(320px,380px)_1fr]">
        <div className="min-h-0 overflow-y-auto border-b lg:border-b-0 lg:border-r">
          {isLoading ? (
            <div className="flex items-center justify-center py-16 text-muted-foreground">
              <Loader2 className="size-5 animate-spin" aria-hidden />
            </div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center gap-3 px-4 py-16 text-center text-muted-foreground">
              <GitPullRequestArrow className="size-10 opacity-30" aria-hidden />
              <p className="text-sm">
                No change requests yet. End a workflow with an{" "}
                <span className="font-mono">Open Change Request</span> step.
              </p>
            </div>
          ) : (
            <ul className="divide-y">
              {items.map((item) => {
                const isSelected = item.id === effectiveSelectedId;
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(item.id)}
                      className={`flex w-full flex-col gap-1.5 px-4 py-3 text-left transition-colors hover:bg-muted/50 ${
                        isSelected ? "bg-muted" : ""
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-medium text-foreground">
                          {item.title || `Change request #${item.id}`}
                        </span>
                        <ChangeRequestStatusBadge status={item.status} />
                      </div>
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                        {item.branch ? (
                          <span className="font-mono">{item.branch}</span>
                        ) : null}
                        {diffSummary(item) ? (
                          <Badge variant="secondary" className="h-4 px-1 font-mono text-[10px]">
                            {diffSummary(item)}
                          </Badge>
                        ) : null}
                        <span>{relativeAge(item.created_at)}</span>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="min-h-0">
          <ChangeRequestDetailPane
            key={effectiveSelectedId ?? "none"}
            changeRequestId={effectiveSelectedId}
          />
        </div>
      </div>
    </div>
  );
}
