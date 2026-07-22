"use client";

import { useCallback, useState } from "react";
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
import { SOURCE_KEY_PREFIXES } from "@/components/features/settings/constants/setting-keys";
import { useSettingsListQuery } from "@/hooks/queries/use-settings-query";
import { groupSourceSettings } from "@/components/features/settings/utils/parse-source-settings";

interface GitSourceSelectDialogProps {
  open: boolean;
  selectedSourceId: string;
  onClose: () => void;
  onSave: (sourceId: string) => void;
}

export function GitSourceSelectDialog({
  open,
  selectedSourceId,
  onClose,
  onSave,
}: GitSourceSelectDialogProps) {
  const router = useRouter();
  const [sourceId, setSourceId] = useState(selectedSourceId);
  const [prevOpen, setPrevOpen] = useState(open);
  const { data, isLoading } = useSettingsListQuery({
    keyPrefix: SOURCE_KEY_PREFIXES.git,
    enabled: open,
  });

  const { git: sources } = groupSourceSettings(data?.settings ?? []);

  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setSourceId(selectedSourceId);
    }
  }

  const handleSave = useCallback(() => {
    if (!sourceId) {
      return;
    }
    onSave(sourceId);
    onClose();
  }, [onClose, onSave, sourceId]);

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Git source</DialogTitle>
          <DialogDescription>
            A configured Git repository is required. Choose which saved source
            (from Settings → Sources) this step should read the defaults YAML
            file from. Only the source ID is stored on the step; URL and token
            are loaded from settings at runtime.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading sources…</p>
          ) : sources.length === 0 ? (
            <div className="rounded-lg border border-dashed bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
              <p>No Git sources configured yet.</p>
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
              <Label htmlFor="set-default-attributes-git-source-select">Source ID</Label>
              <Select value={sourceId || undefined} onValueChange={setSourceId}>
                <SelectTrigger id="set-default-attributes-git-source-select">
                  <SelectValue placeholder="Select a Git source" />
                </SelectTrigger>
                <SelectContent>
                  {sources.map((source) => (
                    <SelectItem key={source.sourceId} value={source.sourceId}>
                      <span className="font-mono">{source.sourceId}</span>
                      <span className="ml-2 text-muted-foreground">— {source.url}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!sourceId || sources.length === 0} type="button" onClick={handleSave}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
