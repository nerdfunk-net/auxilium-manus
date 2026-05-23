"use client";

import { FilterX } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type {
  WorkflowRunListFilters,
  WorkflowRunListStatusFilter,
} from "../types/workflow-run-filters";
import { hasActiveWorkflowRunFilters } from "../types/workflow-run-filters";

const STATUS_OPTIONS: { value: WorkflowRunListStatusFilter; label: string }[] = [
  { value: "success", label: "Success" },
  { value: "failed", label: "Failed" },
  { value: "skipped", label: "Skipped steps" },
];

interface WorkflowRunFiltersBarProps {
  filters: WorkflowRunListFilters;
  onChange: (filters: WorkflowRunListFilters) => void;
}

export function WorkflowRunFiltersBar({ filters, onChange }: WorkflowRunFiltersBarProps) {
  const toggleStatus = (status: WorkflowRunListStatusFilter) => {
    const next = filters.statuses.includes(status)
      ? filters.statuses.filter((s) => s !== status)
      : [...filters.statuses, status];
    onChange({ ...filters, statuses: next });
  };

  const clearFilters = () => {
    onChange({ statuses: [], createdFrom: null, createdTo: null });
  };

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b bg-background px-6 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-muted-foreground shrink-0">Status</span>
        {STATUS_OPTIONS.map(({ value, label }) => {
          const active = filters.statuses.includes(value);
          return (
            <button
              key={value}
              type="button"
              onClick={() => toggleStatus(value)}
              className="rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Badge variant={active ? "default" : "outline"} className="cursor-pointer">
                {label}
              </Badge>
            </button>
          );
        })}
      </div>

      <div className="flex items-center gap-2">
        <Label
          htmlFor="run-filter-from"
          className="text-xs text-muted-foreground shrink-0 font-normal"
        >
          From
        </Label>
        <Input
          id="run-filter-from"
          type="date"
          className="h-8 w-[9.5rem] text-xs"
          value={filters.createdFrom ?? ""}
          max={filters.createdTo ?? undefined}
          onChange={(e) =>
            onChange({
              ...filters,
              createdFrom: e.target.value || null,
            })
          }
        />
      </div>

      <div className="flex items-center gap-2">
        <Label
          htmlFor="run-filter-to"
          className="text-xs text-muted-foreground shrink-0 font-normal"
        >
          To
        </Label>
        <Input
          id="run-filter-to"
          type="date"
          className="h-8 w-[9.5rem] text-xs"
          value={filters.createdTo ?? ""}
          min={filters.createdFrom ?? undefined}
          onChange={(e) =>
            onChange({
              ...filters,
              createdTo: e.target.value || null,
            })
          }
        />
      </div>

      {hasActiveWorkflowRunFilters(filters) && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 gap-1 px-2 text-xs"
          onClick={clearFilters}
        >
          <FilterX className="size-3.5" />
          Clear
        </Button>
      )}
    </div>
  );
}
