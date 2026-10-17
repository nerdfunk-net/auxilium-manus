"use client";

import type { LucideIcon } from "lucide-react";
import { Pencil, Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";

export interface SourceListItem {
  sourceId: string;
  summary: string;
  detail?: string;
}

interface SourceListSectionProps {
  title: string;
  description: string;
  icon: LucideIcon;
  items: SourceListItem[];
  isLoading?: boolean;
  emptyLabel: string;
  addLabel: string;
  onAdd: () => void;
  onEdit: (sourceId: string) => void;
  onDelete: (sourceId: string) => void;
}

export function SourceListSection({
  title,
  description,
  icon: Icon,
  items,
  isLoading = false,
  emptyLabel,
  addLabel,
  onAdd,
  onEdit,
  onDelete,
}: SourceListSectionProps) {
  return (
    <section className="space-y-3">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Icon className="size-4" />
          </div>
          <div>
            <p className="text-sm font-medium">{title}</p>
            <p className="text-xs text-muted-foreground">{description}</p>
          </div>
        </div>
        <Button size="sm" type="button" variant="outline" onClick={onAdd}>
          <Plus className="size-4" />
          {addLabel}
        </Button>
      </div>

      {isLoading ? (
        <p className="text-xs text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-3 text-xs text-muted-foreground">
          {emptyLabel}
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li
              key={item.sourceId}
              className="flex items-center justify-between gap-3 rounded-lg border bg-background px-4 py-3"
            >
              <div className="min-w-0">
                <p className="font-mono text-sm font-medium">{item.sourceId}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {item.summary}
                </p>
                {item.detail ? (
                  <p className="truncate text-xs text-muted-foreground">
                    {item.detail}
                  </p>
                ) : null}
              </div>
              <div className="flex shrink-0 gap-1">
                <Button
                  aria-label={`Edit ${item.sourceId}`}
                  size="icon"
                  type="button"
                  variant="ghost"
                  onClick={() => onEdit(item.sourceId)}
                >
                  <Pencil className="size-4" />
                </Button>
                <Button
                  aria-label={`Delete ${item.sourceId}`}
                  size="icon"
                  type="button"
                  variant="ghost"
                  onClick={() => onDelete(item.sourceId)}
                >
                  <Trash2 className="size-4 text-destructive" />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
