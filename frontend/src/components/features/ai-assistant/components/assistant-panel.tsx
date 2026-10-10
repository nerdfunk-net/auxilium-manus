"use client";

import { Loader2, Send, Square, Trash2 } from "lucide-react";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

import { useAssistantChat } from "../hooks/use-assistant-chat";

interface AssistantPanelProps {
  /** Shown above the input; surfaces use it to say what the assistant can see. */
  placeholder?: string;
}

const DEFAULT_PLACEHOLDER = "Ask the assistant…";

/**
 * Reusable chat panel. Callers must gate rendering on `useAiAssistantAvailable()` so that
 * nothing assistant-related is shown when the user has switched it off.
 */
export function AssistantPanel({ placeholder = DEFAULT_PLACEHOLDER }: AssistantPanelProps) {
  const { messages, isStreaming, send, stop, clear } = useAssistantChat();
  const [draft, setDraft] = useState("");

  const handleSend = useCallback(() => {
    if (!draft.trim() || isStreaming) {
      return;
    }
    void send(draft);
    setDraft("");
  }, [draft, isStreaming, send]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-3" data-testid="assistant-panel">
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto" aria-live="polite">
        {messages.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Ask a question. Conversations are not saved and are cleared when you reload.
          </p>
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              className={
                message.role === "user"
                  ? "ml-8 rounded-md bg-primary/10 p-3 text-sm"
                  : "mr-8 rounded-md bg-muted p-3 text-sm"
              }
            >
              <p className="whitespace-pre-wrap break-words">{message.content}</p>
              {message.role === "assistant" && !message.content && !message.error && (
                <Loader2 className="size-4 animate-spin text-muted-foreground" />
              )}
              {message.error && <p className="mt-1 text-destructive">{message.error}</p>}
            </div>
          ))
        )}
      </div>
      <div className="flex items-end gap-2">
        <Textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={2}
          aria-label="Message the assistant"
          maxLength={20000}
        />
        <div className="flex flex-col gap-1">
          {isStreaming ? (
            <Button type="button" size="icon" variant="outline" onClick={stop} aria-label="Stop">
              <Square className="size-4" />
            </Button>
          ) : (
            <Button
              type="button"
              size="icon"
              onClick={handleSend}
              disabled={!draft.trim()}
              aria-label="Send"
            >
              <Send className="size-4" />
            </Button>
          )}
          <Button
            type="button"
            size="icon"
            variant="ghost"
            onClick={clear}
            disabled={messages.length === 0}
            aria-label="Clear conversation"
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
