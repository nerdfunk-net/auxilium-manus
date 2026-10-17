"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { WIDGET_REGISTRY } from "@/components/features/dashboard/registry/widget-registry";
import type { WidgetId } from "@/components/features/dashboard/types/dashboard";

interface AddWidgetDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  activeWidgetIds: Set<WidgetId>;
  onAdd: (id: WidgetId) => void;
}

export function AddWidgetDialog({
  open,
  onOpenChange,
  activeWidgetIds,
  onAdd,
}: AddWidgetDialogProps) {
  const availableWidgets = Object.values(WIDGET_REGISTRY).filter(
    (widget) => !activeWidgetIds.has(widget.id),
  );

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add card</DialogTitle>
        </DialogHeader>
        {availableWidgets.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            All available cards are already on your dashboard.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {availableWidgets.map((widget) => (
              <div
                className="flex items-center justify-between gap-3 rounded-md border p-3"
                key={widget.id}
              >
                <div className="flex items-center gap-3">
                  <widget.icon className="size-5 shrink-0 text-muted-foreground" />
                  <div>
                    <p className="text-sm font-medium">{widget.title}</p>
                    <p className="text-xs text-muted-foreground">{widget.description}</p>
                  </div>
                </div>
                <Button
                  onClick={() => {
                    onAdd(widget.id);
                    onOpenChange(false);
                  }}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  Add
                </Button>
              </div>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
