"use client";

import { Lock, Play, Plus, RefreshCw, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import type { EditorVariable } from "../types";

interface VariablesPanelProps {
  variables: EditorVariable[];
  selectedId: string | null;
  canExecutePreRun: boolean;
  onSelect: (id: string) => void;
  onAdd: () => void;
  onRemove: (id: string) => void;
  onUpdateValue: (id: string, value: string) => void;
  onExecutePreRun: () => void;
}

export function VariablesPanel({
  variables,
  selectedId,
  canExecutePreRun,
  onSelect,
  onAdd,
  onRemove,
  onUpdateValue,
  onExecutePreRun,
}: VariablesPanelProps) {
  const selected = variables.find((variable) => variable.id === selectedId) ?? null;
  const isPreRun = selected?.name.startsWith("command.") ?? false;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Variables
        </span>
        <Button size="sm" type="button" variant="ghost" onClick={onAdd}>
          <Plus className="size-4" />
          Add
        </Button>
      </div>

      <ul className="max-h-56 flex-1 overflow-auto p-2">
        {variables.map((variable) => (
          <li key={variable.id}>
            <button
              type="button"
              onClick={() => onSelect(variable.id)}
              className={cn(
                "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted",
                selectedId === variable.id && "bg-muted",
              )}
            >
              <span className="flex min-w-0 items-center gap-2">
                {variable.isAutoFilled ? (
                  <Lock className="size-3 shrink-0 text-muted-foreground" />
                ) : null}
                <span className="truncate font-mono text-xs">{variable.name}</span>
              </span>
              {variable.isAutoFilled ? (
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  auto
                </span>
              ) : (
                <span
                  role="button"
                  tabIndex={0}
                  aria-label={`Remove ${variable.name}`}
                  className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-destructive"
                  onClick={(event) => {
                    event.stopPropagation();
                    onRemove(variable.id);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.stopPropagation();
                      onRemove(variable.id);
                    }
                  }}
                >
                  <X className="size-3" />
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>

      <div className="flex flex-col gap-2 border-t p-4">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Variable Details
        </span>
        {selected ? (
          <>
            <p className="font-mono text-xs text-foreground">{selected.name}</p>
            {selected.description ? (
              <p className="text-xs text-muted-foreground">{selected.description}</p>
            ) : null}
            <Textarea
              className="min-h-[120px] font-mono text-xs"
              readOnly={selected.isAutoFilled}
              value={selected.value}
              placeholder={
                selected.isAutoFilled
                  ? "Auto-filled at render time"
                  : "Enter a value (text or JSON)"
              }
              onChange={(event) => onUpdateValue(selected.id, event.target.value)}
            />
            {isPreRun ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!canExecutePreRun || Boolean(selected.isExecuting)}
                onClick={onExecutePreRun}
              >
                {selected.isExecuting ? (
                  <RefreshCw className="size-4 animate-spin" />
                ) : (
                  <Play className="size-4" />
                )}
                Execute pre-run command
              </Button>
            ) : null}
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            Select a variable above to view its details.
          </p>
        )}
      </div>
    </div>
  );
}
