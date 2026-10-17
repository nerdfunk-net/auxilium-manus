"use client";

import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useNautobotLocationTypesQuery } from "@/hooks/queries/use-nautobot-location-types-query";
import { cn } from "@/lib/utils";

interface LocationTypeSelectDialogProps {
  open: boolean;
  sourceId: string;
  selectedType: string;
  onClose: () => void;
  onSave: (locationType: string) => void;
}

export function LocationTypeSelectDialog({
  open,
  sourceId,
  selectedType,
  onClose,
  onSave,
}: LocationTypeSelectDialogProps) {
  const [chosen, setChosen] = useState(selectedType);
  const [prevOpen, setPrevOpen] = useState(open);
  const { data, isLoading, error } = useNautobotLocationTypesQuery({
    sourceId,
    enabled: open,
  });

  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setChosen(selectedType);
    }
  }

  const handleSave = useCallback(() => {
    if (!chosen) return;
    onSave(chosen);
    onClose();
  }, [chosen, onClose, onSave]);

  const types = data ?? [];

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="flex max-h-[80vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-md">
        <DialogHeader className="sr-only">
          <DialogTitle>Select location type</DialogTitle>
          <DialogDescription>
            Choose the Nautobot location type whose location is written to the
            target attribute.
          </DialogDescription>
        </DialogHeader>

        <div className="step-header px-4 py-2.5 text-sm font-semibold">
          Location type
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto bg-muted p-2">
          {isLoading ? (
            <p className="p-2 text-xs text-muted-foreground">
              Loading location types…
            </p>
          ) : error ? (
            <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
              Could not load location types from Nautobot.
            </p>
          ) : types.length === 0 ? (
            <p className="p-2 text-xs text-muted-foreground">
              No location types found.
            </p>
          ) : (
            <ul className="space-y-1" role="listbox" aria-label="Location types">
              {types.map((type) => {
                const selected = type.name === chosen;
                return (
                  <li key={type.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={selected}
                      className={cn(
                        "w-full rounded-lg px-3 py-2 text-left text-xs hover:bg-card",
                        selected && "bg-step-surface text-step-surface-foreground",
                      )}
                      onClick={() => setChosen(type.name)}
                      onDoubleClick={() => {
                        onSave(type.name);
                        onClose();
                      }}
                    >
                      <span className="block font-medium">
                        {type.name}
                        {type.nestable ? (
                          <span className="ml-1.5 text-[10px] font-normal text-muted-foreground">
                            nestable
                          </span>
                        ) : null}
                      </span>
                      {type.display !== type.name ? (
                        <span className="block text-[11px] text-muted-foreground">
                          {type.display}
                        </span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <DialogFooter className="shrink-0 border-t bg-card px-4 py-3">
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" size="sm" disabled={!chosen} onClick={handleSave}>
            Select
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
