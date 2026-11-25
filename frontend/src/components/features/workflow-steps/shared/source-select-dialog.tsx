"use client";

import { useCallback, useState } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export interface SourceChoice {
  id: string;
  /** What follows the id in the list (URL, host:port). */
  detail: string;
}

interface SourceSelectDialogProps {
  open: boolean;
  selectedSourceId: string;
  onClose: () => void;
  onSave: (sourceId: string) => void;
  title: string;
  description: string;
  /** The integration's name, for "No <label> sources configured yet." and the placeholder. */
  sourceLabel: string;
  /** Prefix of the select's DOM id: `<idPrefix>-source-select`. */
  idPrefix: string;
  sources: readonly SourceChoice[];
  isLoading: boolean;
  /** Optional text under the select, given the id that is currently chosen. */
  renderHint?: (sourceId: string) => ReactNode;
}

/** The dialog every source-bound step opens to pick one of the saved sources (Settings →
 * Sources). Only the id is stored on the step. The per-integration dialogs
 * (`ise-source-select-dialog.tsx` …) are thin wrappers that fetch their list. */
export function SourceSelectDialog({
  open,
  selectedSourceId,
  onClose,
  onSave,
  title,
  description,
  sourceLabel,
  idPrefix,
  sources,
  isLoading,
  renderHint,
}: SourceSelectDialogProps) {
  const router = useRouter();
  const [sourceId, setSourceId] = useState(selectedSourceId);
  const [prevOpen, setPrevOpen] = useState(open);

  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setSourceId(selectedSourceId);
    }
  }

  const handleSave = useCallback(() => {
    if (!sourceId) return;
    onSave(sourceId);
    onClose();
  }, [onClose, onSave, sourceId]);

  const selectId = `${idPrefix}-source-select`;

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading sources…</p>
          ) : sources.length === 0 ? (
            <div className="rounded-lg border border-dashed bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
              <p>No {sourceLabel} sources configured yet.</p>
              <Button
                className="mt-3 h-8"
                size="sm"
                type="button"
                variant="outline"
                onClick={() => {
                  onClose();
                  router.push("/settings/sources");
                }}
              >
                Open Settings → Sources
              </Button>
            </div>
          ) : (
            <div className="space-y-2">
              <Label htmlFor={selectId}>Source ID</Label>
              <Select value={sourceId || ""} onValueChange={setSourceId}>
                <SelectTrigger id={selectId}>
                  <SelectValue placeholder={`Select a ${sourceLabel} source`} />
                </SelectTrigger>
                <SelectContent>
                  {sources.map((source) => (
                    <SelectItem key={source.id} value={source.id}>
                      <span className="font-mono">{source.id}</span>
                      <span className="ml-2 text-muted-foreground">— {source.detail}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {renderHint ? renderHint(sourceId) : null}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!sourceId || sources.length === 0}
            type="button"
            onClick={handleSave}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
