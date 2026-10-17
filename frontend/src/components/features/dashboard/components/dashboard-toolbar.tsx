"use client";

import { Pencil, Plus, RefreshCw, RotateCcw, Check } from "lucide-react";

import { Button } from "@/components/ui/button";

interface DashboardToolbarProps {
  isEditing: boolean;
  onToggleEditing: () => void;
  onAddCard: () => void;
  onReset: () => void;
  onRefresh: () => void;
  addDisabled: boolean;
}

export function DashboardToolbar({
  isEditing,
  onToggleEditing,
  onAddCard,
  onReset,
  onRefresh,
  addDisabled,
}: DashboardToolbarProps) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div>
        <h1 className="text-lg font-semibold">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Your workflow schedules and recent run activity.
        </p>
      </div>
      <div className="flex items-center gap-2">
        {isEditing ? (
          <>
            <Button
              disabled={addDisabled}
              onClick={onAddCard}
              size="sm"
              type="button"
              variant="outline"
            >
              <Plus className="size-4" />
              Add card
            </Button>
            <Button onClick={onReset} size="sm" type="button" variant="outline">
              <RotateCcw className="size-4" />
              Reset
            </Button>
          </>
        ) : (
          <Button onClick={onRefresh} size="sm" type="button" variant="outline">
            <RefreshCw className="size-4" />
            Refresh
          </Button>
        )}
        <Button onClick={onToggleEditing} size="sm" type="button" variant="default">
          {isEditing ? (
            <>
              <Check className="size-4" />
              Done
            </>
          ) : (
            <>
              <Pencil className="size-4" />
              Edit
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
