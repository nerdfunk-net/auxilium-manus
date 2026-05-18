"use client";

import { useCallback, useMemo, useState } from "react";
import { Filter, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useDeviceSelectionPreviewMutation } from "@/hooks/queries/use-device-selection-preview-mutation";

import { ConditionBuilder } from "./condition-builder/condition-builder";
import { treeToOperations } from "./condition-builder/tree-to-operation";
import type { FilterTree } from "./condition-builder/types";

interface InventoryBuilderDialogProps {
  open: boolean;
  onClose: () => void;
  nautobot_url: string;
  nautobot_token: string;
  initialTree: FilterTree;
  onApply: (tree: FilterTree) => void;
}

export function InventoryBuilderDialog({
  open,
  onClose,
  nautobot_url,
  nautobot_token,
  initialTree,
  onApply,
}: InventoryBuilderDialogProps) {
  const [tree, setTree] = useState<FilterTree>(initialTree);
  const previewMutation = useDeviceSelectionPreviewMutation();

  const hasSource = Boolean(nautobot_url && nautobot_token);

  const handleOpen = useCallback(() => {
    setTree(initialTree);
    previewMutation.reset();
  }, [initialTree]); // eslint-disable-line react-hooks/exhaustive-deps

  const handlePreview = useCallback(() => {
    const operations = treeToOperations(tree);
    previewMutation.mutate({ nautobot_url, nautobot_token, operations });
  }, [tree, nautobot_url, nautobot_token, previewMutation]);

  const handleApply = useCallback(() => {
    onApply(tree);
    onClose();
  }, [tree, onApply, onClose]);

  const conditionCount = useMemo(() => {
    function count(group: FilterTree): number {
      let n = 0;
      for (const item of group.items) {
        if ("items" in item) {
          n += count(item);
        } else {
          n += 1;
        }
      }
      return n;
    }
    return count(tree);
  }, [tree]);

  return (
    <Dialog
      open={open}
      onOpenChange={(isOpen) => {
        if (isOpen) handleOpen();
        else onClose();
      }}
    >
      <DialogContent className="flex h-[80vh] max-w-4xl flex-col gap-0 p-0">
        {/* Header */}
        <DialogHeader className="shrink-0 border-b bg-primary px-6 py-3">
          <DialogDescription className="sr-only">Build filter conditions to select devices from the inventory.</DialogDescription>
          <DialogTitle className="flex items-center gap-2 text-primary-foreground">
            <Filter className="h-4 w-4" />
            Device Filter
            {conditionCount > 0 && (
              <Badge className="ml-2 bg-primary-foreground/20 text-primary-foreground">
                {conditionCount} condition{conditionCount !== 1 ? "s" : ""}
              </Badge>
            )}
          </DialogTitle>
        </DialogHeader>

        {/* Source warning */}
        {!hasSource && (
          <div className="shrink-0 border-b bg-amber-50 px-6 py-2 text-xs text-amber-700">
            Configure a Nautobot source first to enable value autocomplete and preview.
          </div>
        )}

        {/* Condition builder — scrollable */}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          <ConditionBuilder
            tree={tree}
            nautobot_url={nautobot_url}
            nautobot_token={nautobot_token}
            onChange={setTree}
          />
        </div>

        {/* Preview results */}
        {(previewMutation.isPending || previewMutation.data || previewMutation.isError) && (
          <div className="shrink-0 border-t">
            {previewMutation.isPending && (
              <div className="flex items-center gap-2 px-6 py-3 text-xs text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Querying Nautobot...
              </div>
            )}
            {previewMutation.isError && (
              <p className="px-6 py-3 text-xs text-destructive">
                {previewMutation.error.message ?? "Preview failed. Check Nautobot connectivity."}
              </p>
            )}
            {previewMutation.data && (
              <div className="px-6 py-3">
                <p className="mb-2 text-xs font-medium">
                  {previewMutation.data.total} device{previewMutation.data.total !== 1 ? "s" : ""} found
                </p>
                <div className="max-h-40 overflow-y-auto rounded border">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-muted">
                      <tr>
                        <th className="px-2 py-1 text-left font-medium">Name</th>
                        <th className="px-2 py-1 text-left font-medium">Location</th>
                        <th className="px-2 py-1 text-left font-medium">Role</th>
                        <th className="px-2 py-1 text-left font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previewMutation.data.devices.slice(0, 100).map((d) => (
                        <tr key={d.id} className="border-t">
                          <td className="px-2 py-1">{d.name ?? "—"}</td>
                          <td className="px-2 py-1 text-muted-foreground">{d.location ?? "—"}</td>
                          <td className="px-2 py-1 text-muted-foreground">{d.role ?? "—"}</td>
                          <td className="px-2 py-1 text-muted-foreground">{d.status ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {previewMutation.data.total > 100 && (
                    <p className="px-2 py-1 text-center text-[10px] text-muted-foreground">
                      Showing first 100 of {previewMutation.data.total}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <DialogFooter className="shrink-0 border-t px-6 py-3">
          <Button
            variant="outline"
            size="sm"
            onClick={handlePreview}
            type="button"
            disabled={!hasSource || previewMutation.isPending || conditionCount === 0}
          >
            {previewMutation.isPending ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : null}
            Preview Results
          </Button>
          <div className="flex-1" />
          <Button variant="outline" size="sm" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button size="sm" onClick={handleApply} type="button">
            Apply
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
