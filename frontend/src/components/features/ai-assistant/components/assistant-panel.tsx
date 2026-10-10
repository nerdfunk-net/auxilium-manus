"use client";

import Link from "next/link";
import {
  FolderOpen,
  Loader2,
  Save,
  Send,
  Square,
  Trash2,
  Wrench,
} from "lucide-react";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useAiConversationsMutations } from "@/hooks/queries/use-ai-conversations-mutations";

import { dataClassLabel } from "../constants/data-classes";
import { useAssistantChat } from "../hooks/use-assistant-chat";
import {
  EMPTY_SESSION,
  useAssistantSessionStore,
} from "../store/assistant-session-store";
import type {
  AssistantContext,
  ConversationScope,
  DisplayMessage,
  SavedConversation,
  WorkflowProposal,
} from "../types/ai-assistant";
import {
  fromSavedMessages,
  toSavedMessages,
} from "../utils/conversation-mapping";
import { SavedConversationsDialog } from "./saved-conversations-dialog";
import { WorkflowProposalCard } from "./workflow-proposal-card";
import { TemplateProposalCard } from "./template-proposal-card";

/** Where a template proposal is applied: the editor's unsaved buffer. */
export interface TemplateProposalTarget {
  currentContent: string;
  onApply: (content: string) => void;
}

/** Where a workflow proposal is applied: the builder canvas, as unsaved state. */
export interface WorkflowProposalTarget {
  currentFingerprint: string;
  onApply: (proposal: WorkflowProposal) => void;
}

interface AssistantPanelProps {
  /** Stored conversation to show, for example `workflow_editor:12` (see the session store). */
  sessionKey: string;
  /** Enables Save and Saved conversations for this surface and subject. Omit to hide them. */
  conversationScope?: ConversationScope;
  /** Shown in the input; surfaces use it to say what the assistant can see. */
  placeholder?: string;
  /** Current surface state, sent with every turn (enables the surface's tools). */
  getContext?: () => AssistantContext | undefined;
  templateTarget?: TemplateProposalTarget;
  workflowTarget?: WorkflowProposalTarget;
}

const DEFAULT_PLACEHOLDER = "Ask the assistant…";

const TOOL_LABELS: Record<string, string> = {
  get_template_reference: "Reading the template reference",
  list_templates: "Looking through templates",
  get_template: "Reading a template",
  render_template: "Trial-rendering",
  propose_template: "Preparing a proposal",
  get_workflow_reference: "Reading the workflow guide",
  list_steps: "Looking through workflow steps",
  get_step_schema: "Reading a step's settings",
  list_references: "Looking up credentials, repositories and sources",
  validate_workflow: "Validating the workflow",
  propose_workflow: "Preparing a proposal",
  get_run: "Reading the run",
  get_step_result: "Reading a step's result",
  get_artifact: "Reading stored output",
  list_run_events: "Reading run events",
  get_run_workflow: "Reading the workflow definition",
  list_inventories: "Looking through inventories",
  resolve_inventory: "Resolving an inventory",
  search_devices: "Searching devices",
  get_device_attributes: "Reading device attributes",
};

function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name;
}

/**
 * Reusable chat panel. Callers must gate rendering on `useAiAssistantAvailable()` so that
 * nothing assistant-related is shown when the user has switched it off.
 */
export function AssistantPanel({
  sessionKey,
  conversationScope,
  placeholder = DEFAULT_PLACEHOLDER,
  getContext,
  templateTarget,
  workflowTarget,
}: AssistantPanelProps) {
  const { messages, isStreaming, send, stop, clear, setProposalState } =
    useAssistantChat({
      sessionKey,
      getContext,
    });
  const draft = useAssistantSessionStore(
    (state) => (state.sessions[sessionKey] ?? EMPTY_SESSION).draft,
  );
  const savedId = useAssistantSessionStore(
    (state) => (state.sessions[sessionKey] ?? EMPTY_SESSION).savedId,
  );
  const [savedOpen, setSavedOpen] = useState(false);
  const { save } = useAiConversationsMutations();

  const handleSave = useCallback(() => {
    if (!conversationScope) {
      return;
    }
    save.mutate(
      {
        scope: conversationScope,
        messages: toSavedMessages(messages),
        savedId,
      },
      {
        onSuccess: (saved) =>
          useAssistantSessionStore.getState().setSavedId(sessionKey, saved.id),
      },
    );
  }, [conversationScope, messages, save, savedId, sessionKey]);

  const handleResume = useCallback(
    (conversation: SavedConversation) => {
      stop();
      useAssistantSessionStore
        .getState()
        .loadSaved(
          sessionKey,
          fromSavedMessages(conversation.messages),
          conversation.id,
        );
    },
    [sessionKey, stop],
  );

  const handleDeleted = useCallback(
    (id: number) => {
      if (id === savedId) {
        useAssistantSessionStore.getState().setSavedId(sessionKey, null);
      }
    },
    [savedId, sessionKey],
  );

  const setDraft = useCallback(
    (value: string) =>
      useAssistantSessionStore.getState().setDraft(sessionKey, value),
    [sessionKey],
  );

  const handleSend = useCallback(() => {
    if (!draft.trim() || isStreaming) {
      return;
    }
    void send(draft);
    setDraft("");
  }, [draft, isStreaming, send, setDraft]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const renderMessage = (message: DisplayMessage) => (
    <div
      key={message.id}
      className={
        message.role === "user"
          ? "ml-8 rounded-md bg-primary/10 p-3 text-sm"
          : "mr-2 space-y-2 rounded-md bg-muted p-3 text-sm"
      }
    >
      {message.tools && message.tools.length > 0 && (
        <ul className="space-y-1" aria-label="Assistant activity">
          {message.tools.map((tool) => (
            <li
              key={tool.id}
              className="flex items-center gap-1 text-xs text-muted-foreground"
            >
              {tool.status === "running" ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <Wrench className="size-3" />
              )}
              {toolLabel(tool.name)}
              {tool.status === "error" && " (failed)"}
              {tool.truncated && " (partial result)"}
              {tool.withheld && tool.withheld.length > 0 && (
                <span className="text-warning-foreground">
                  {" "}
                  – needs {tool.withheld.map(dataClassLabel).join(", ")}{" "}
                  <Link
                    href="/settings/ai-assistant"
                    className="underline underline-offset-2"
                  >
                    enable
                  </Link>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {message.content && (
        <p className="whitespace-pre-wrap break-words">{message.content}</p>
      )}
      {message.role === "assistant" &&
        !message.content &&
        !message.error &&
        !message.proposal &&
        !message.tools?.length && (
          <Loader2 className="size-4 animate-spin text-muted-foreground" />
        )}
      {message.proposal?.kind === "template" && templateTarget && (
        <TemplateProposalCard
          proposal={message.proposal}
          currentContent={templateTarget.currentContent}
          onApply={() => {
            if (message.proposal?.kind === "template") {
              templateTarget.onApply(message.proposal.content);
              setProposalState(message.id, "applied");
            }
          }}
          onReject={() => setProposalState(message.id, "rejected")}
        />
      )}
      {message.proposal?.kind === "workflow" && workflowTarget && (
        <WorkflowProposalCard
          proposal={message.proposal}
          currentFingerprint={workflowTarget.currentFingerprint}
          onApply={() => {
            if (message.proposal?.kind === "workflow") {
              workflowTarget.onApply(message.proposal);
              setProposalState(message.id, "applied");
            }
          }}
          onReject={() => setProposalState(message.id, "rejected")}
        />
      )}
      {message.savedProposal && (
        <p className="rounded border border-dashed p-2 text-xs text-muted-foreground">
          Earlier {message.savedProposal.kind} proposal (not applicable after
          resuming): {message.savedProposal.summary || "no summary"}
        </p>
      )}
      {message.error && <p className="text-destructive">{message.error}</p>}
    </div>
  );

  return (
    <div
      className="flex h-full min-h-0 flex-col gap-3"
      data-testid="assistant-panel"
    >
      {conversationScope && (
        <div className="flex items-center justify-end gap-1">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={handleSave}
            disabled={messages.length === 0 || isStreaming || save.isPending}
            title="Save this conversation on the server (secrets are redacted on a best-effort basis)"
          >
            <Save className="size-4" />
            {savedId === null ? "Save" : "Update saved"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => setSavedOpen(true)}
          >
            <FolderOpen className="size-4" />
            Saved
          </Button>
        </div>
      )}
      <div
        className="min-h-0 flex-1 space-y-3 overflow-y-auto"
        aria-live="polite"
      >
        {messages.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Ask a question. The conversation is kept while you use the app and
            cleared when you reload or sign out.
            {conversationScope && " Use Save to keep it for later."}
          </p>
        ) : (
          messages.map(renderMessage)
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
            <Button
              type="button"
              size="icon"
              variant="outline"
              onClick={stop}
              aria-label="Stop"
            >
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
      {conversationScope && (
        <SavedConversationsDialog
          scope={conversationScope}
          open={savedOpen}
          onOpenChange={setSavedOpen}
          hasCurrentMessages={messages.length > 0}
          currentSavedId={savedId}
          onResume={handleResume}
          onDeleted={handleDeleted}
        />
      )}
    </div>
  );
}
