"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import type { GitContentSearchPreviewMatch } from "@/hooks/queries/use-get-from-config-preview-mutation";

interface GetFromConfigPreviewDialogProps {
  open: boolean;
  onClose: () => void;
  matches: GitContentSearchPreviewMatch[];
  sourceId: string;
}

export function GetFromConfigPreviewDialog({
  open,
  onClose,
  matches,
  sourceId,
}: GetFromConfigPreviewDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Search Preview</DialogTitle>
          <DialogDescription>
            {matches.length} matching file{matches.length !== 1 ? "s" : ""} found in source{" "}
            <code className="rounded bg-muted px-1 font-mono text-xs">{sourceId}</code>
          </DialogDescription>
        </DialogHeader>

        {matches.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">
            No files matched the configured search.
          </p>
        ) : (
          <div className="overflow-hidden rounded-md border text-xs">
            <div className="grid grid-cols-4 border-b bg-muted/50 px-3 py-2 font-medium text-muted-foreground">
              <span>File</span>
              <span>Matched line</span>
              <span>Hostname</span>
              <span>Commit</span>
            </div>
            <div className="divide-y">
              {matches.map((match, index) => (
                <div key={index} className="grid grid-cols-4 px-3 py-2 hover:bg-muted/30">
                  <span className="truncate font-mono">{match.file_path}</span>
                  <span className="truncate text-muted-foreground">{match.line_content}</span>
                  <span className="font-mono">
                    {match.hostname ?? (
                      <span className="text-amber-600">unparseable</span>
                    )}
                  </span>
                  <span className="font-mono text-muted-foreground">
                    {match.commit ?? "current"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
