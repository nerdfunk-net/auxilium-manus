"use client";

import { Loader2, Trash2 } from "lucide-react";
import { useCallback } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAiConversationsMutations } from "@/hooks/queries/use-ai-conversations-mutations";
import { useAiConversationsQuery } from "@/hooks/queries/use-ai-conversations-query";

import type {
  ConversationScope,
  SavedConversation,
} from "../types/ai-assistant";

interface SavedConversationsDialogProps {
  scope: ConversationScope;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The open chat has messages that resuming would replace. */
  hasCurrentMessages: boolean;
  /** Id of the saved conversation the open chat belongs to, if any. */
  currentSavedId: number | null;
  onResume: (conversation: SavedConversation) => void;
  onDeleted: (id: number) => void;
}

const formatDate = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });

/** Lists the user's saved conversations for one surface and subject; resume or delete. */
export function SavedConversationsDialog({
  scope,
  open,
  onOpenChange,
  hasCurrentMessages,
  currentSavedId,
  onResume,
  onDeleted,
}: SavedConversationsDialogProps) {
  const { data, isLoading, isError } = useAiConversationsQuery(scope, open);
  const { load, remove } = useAiConversationsMutations();

  const handleResume = useCallback(
    (id: number) => {
      load.mutate(id, {
        onSuccess: (conversation) => {
          onResume(conversation);
          onOpenChange(false);
        },
      });
    },
    [load, onOpenChange, onResume],
  );

  const handleDelete = useCallback(
    (id: number) => {
      remove.mutate(id, { onSuccess: () => onDeleted(id) });
    },
    [remove, onDeleted],
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Saved conversations</DialogTitle>
          <DialogDescription>
            Stored on the server and visible only to you. Secrets are redacted
            on a best-effort basis, and a proposal is kept as its summary only.
            {hasCurrentMessages &&
              " Resuming replaces the current conversation."}
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-80 space-y-2 overflow-y-auto">
          {isLoading && (
            <Loader2 className="mx-auto size-4 animate-spin text-muted-foreground" />
          )}
          {isError && (
            <p className="text-sm text-destructive">
              Could not load saved conversations.
            </p>
          )}
          {data && data.length === 0 && (
            <p className="text-sm text-muted-foreground">
              Nothing saved here yet.
            </p>
          )}
          {data?.map((item) => (
            <div
              key={item.id}
              className="flex items-center gap-2 rounded-md border p-2"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">
                  {item.title}
                  {item.id === currentSavedId && (
                    <span className="ml-2 text-xs text-muted-foreground">
                      (open)
                    </span>
                  )}
                </p>
                <p className="text-xs text-muted-foreground">
                  {item.message_count} messages · {formatDate(item.updated_at)}
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => handleResume(item.id)}
                disabled={load.isPending}
              >
                Resume
              </Button>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                onClick={() => handleDelete(item.id)}
                disabled={remove.isPending}
                aria-label={`Delete ${item.title}`}
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
