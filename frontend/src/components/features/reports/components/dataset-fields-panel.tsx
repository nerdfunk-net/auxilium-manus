"use client";

import { Badge } from "@/components/ui/badge";

import type { DatasetInfo } from "../types/report-query";

interface DatasetFieldsPanelProps {
  dataset: DatasetInfo;
}

function formatShare(share: number): string {
  return `${Math.round(share * 100)}% empty`;
}

/** What the user can query in a dataset: grain, field types and a few example values. */
export function DatasetFieldsPanel({ dataset }: DatasetFieldsPanelProps) {
  return (
    <details className="group rounded-md border bg-muted/20 text-xs">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2">
        <Badge variant="secondary">
          {dataset.mode === "items" ? "one row per list item" : "one row per device"}
        </Badge>
        <span className="text-muted-foreground">
          {dataset.fields.length} {dataset.fields.length === 1 ? "field" : "fields"}
        </span>
        <span className="ml-auto text-muted-foreground group-open:hidden">Show</span>
        <span className="ml-auto hidden text-muted-foreground group-open:inline">Hide</span>
      </summary>
      <div className="space-y-2 border-t px-3 py-2">
        {dataset.last_collected_at ? (
          <p className="text-muted-foreground">
            Last collected {dataset.last_collected_at.replace("T", " ").slice(0, 16)}
          </p>
        ) : null}
        <ul className="space-y-1.5">
          {dataset.fields.map((field) => (
            <li key={field.name} className="space-y-0.5">
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="font-mono font-medium">{field.name}</span>
                <Badge className="h-4 rounded px-1 text-[10px]" variant="outline">
                  {field.type}
                </Badge>
                {field.null_share > 0 ? (
                  <span className="text-muted-foreground">{formatShare(field.null_share)}</span>
                ) : null}
              </div>
              {field.sample_values.length > 0 ? (
                <p className="truncate text-muted-foreground">
                  e.g. {field.sample_values.join(", ")}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}
