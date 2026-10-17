"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import type { PendingGroupConnection } from "../hooks/use-workflow-canvas-core";
import type { GroupConnectionCandidate } from "../utils/group-connection-candidates";

interface GroupConnectionDialogProps {
  pending: PendingGroupConnection | null;
  onResolve: (candidate: GroupConnectionCandidate | null) => void;
}

/** Lets the user pick which step inside a collapsed group a new connection attaches to. */
export function GroupConnectionDialog({ pending, onResolve }: GroupConnectionDialogProps) {
  const isInput = pending?.side === "input";

  return (
    <Dialog open={pending !== null} onOpenChange={(open) => (open ? undefined : onResolve(null))}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Choose a step in the group</DialogTitle>
          <DialogDescription>
            {isInput
              ? "Connect to which step inside the group?"
              : "Connect from which step output inside the group?"}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          {pending?.candidates.map((candidate) => (
            <Button
              className="h-auto justify-start gap-2 py-2 text-left"
              key={`${candidate.nodeId}:${candidate.handle}`}
              onClick={() => onResolve(candidate)}
              variant="outline"
            >
              <span className="min-w-0 flex-1 truncate font-medium">{candidate.title}</span>
              <span className="shrink-0 text-xs text-muted-foreground">{candidate.kind}</span>
            </Button>
          ))}
        </div>
        <Button onClick={() => onResolve(null)} variant="ghost">
          Cancel
        </Button>
      </DialogContent>
    </Dialog>
  );
}
