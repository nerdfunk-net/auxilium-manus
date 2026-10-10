"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { buildApiErrorMessage } from "@/hooks/use-api";
import { useAuthStore } from "@/lib/auth-store";

import type {
  AssistantContext,
  ChatMessage,
  DisplayMessage,
  ProposalState,
  ToolActivity,
  ToolStatus,
  WorkflowChanges,
  WorkflowProposalWarning,
} from "../types/ai-assistant";
import { canvasFingerprint } from "../utils/canvas-fingerprint";
import { parseSseBuffer } from "../utils/sse-parser";

const CHAT_ENDPOINT = "/api/proxy/ai/chat";
const GENERIC_ERROR = "The assistant request failed";
const INTERRUPTED_ERROR = "The response was interrupted";

interface TextPayload {
  text?: string;
}
interface ErrorPayload {
  message?: string;
}
interface ToolPayload {
  id?: string;
  name?: string;
  status?: ToolStatus;
  truncated?: boolean;
  withheld?: string[];
}
interface ProposalPayload {
  kind?: string;
  content?: string;
  summary?: string;
  warnings?: unknown[];
  canvas_nodes?: Record<string, unknown>[];
  canvas_edges?: Record<string, unknown>[];
  canvas_groups?: Record<string, unknown>[];
  static_attributes?: Record<string, unknown>[];
  changes?: WorkflowChanges;
}

export interface UseAssistantChatOptions {
  /** Current surface state, read fresh on every send (a ref keeps this stable). */
  getContext?: () => AssistantContext | undefined;
}

function upsertTool(
  tools: ToolActivity[] | undefined,
  next: ToolActivity,
): ToolActivity[] {
  const current = tools ?? [];
  return current.some((tool) => tool.id === next.id)
    ? current.map((tool) => (tool.id === next.id ? next : tool))
    : [...current, next];
}

let messageCounter = 0;
function nextId(): string {
  messageCounter += 1;
  return `m${messageCounter}`;
}

/**
 * Client-held chat (v1 is stateless on the server): the history is re-sent each turn and
 * is lost on reload. Streams the reply over SSE through the Next.js proxy.
 */
export function useAssistantChat({ getContext }: UseAssistantChatOptions = {}) {
  const router = useRouter();
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const messagesRef = useRef<DisplayMessage[]>([]);
  const getContextRef = useRef(getContext);

  useEffect(() => {
    getContextRef.current = getContext;
  }, [getContext]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const patchAssistant = useCallback(
    (id: string, update: (current: DisplayMessage) => DisplayMessage) => {
      setMessages((prev) => prev.map((m) => (m.id === id ? update(m) : m)));
    },
    [],
  );

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || abortRef.current) {
        return;
      }

      const history: ChatMessage[] = [
        ...messagesRef.current
          .filter((m) => !m.error && m.content)
          .map(({ role, content }) => ({ role, content })),
        { role: "user", content: trimmed },
      ];
      const assistantId = nextId();
      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: "user", content: trimmed },
        { id: assistantId, role: "assistant", content: "" },
      ]);

      const context = getContextRef.current?.();
      const controller = new AbortController();
      abortRef.current = controller;
      setIsStreaming(true);

      const fail = (message: string) =>
        patchAssistant(assistantId, (m) => ({ ...m, error: message }));

      try {
        const response = await fetch(CHAT_ENDPOINT, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            context ? { messages: history, context } : { messages: history },
          ),
          signal: controller.signal,
        });

        if (response.status === 401) {
          router.replace("/login");
          fail("Authentication required");
          return;
        }
        if (!response.ok || !response.body) {
          fail(
            await buildApiErrorMessage(response, () =>
              useAuthStore.getState().markPasswordChangeRequired(),
            ),
          );
          return;
        }

        const reader = response.body
          .pipeThrough(new TextDecoderStream())
          .getReader();
        let buffer = "";
        let sawDone = false;
        for (;;) {
          const { value, done } = await reader.read();
          if (done) {
            break;
          }
          const parsed = parseSseBuffer(buffer + value);
          buffer = parsed.rest;
          for (const { event, data } of parsed.events) {
            if (event === "text") {
              const delta = (data as TextPayload).text ?? "";
              patchAssistant(assistantId, (m) => ({
                ...m,
                content: m.content + delta,
              }));
            } else if (event === "tool") {
              const tool = data as ToolPayload;
              if (tool.id && tool.name && tool.status) {
                const activity: ToolActivity = {
                  id: tool.id,
                  name: tool.name,
                  status: tool.status,
                  truncated: tool.truncated === true,
                  withheld: Array.isArray(tool.withheld) ? tool.withheld : [],
                };
                patchAssistant(assistantId, (m) => ({
                  ...m,
                  tools: upsertTool(m.tools, activity),
                }));
              }
            } else if (event === "proposal") {
              const proposal = data as ProposalPayload;
              if (
                proposal.kind === "template" &&
                typeof proposal.content === "string"
              ) {
                const content = proposal.content;
                const baseContent =
                  context?.surface === "template_editor" ? context.content : "";
                patchAssistant(assistantId, (m) => ({
                  ...m,
                  proposal: {
                    kind: "template",
                    content,
                    summary: proposal.summary ?? "",
                    warnings: (proposal.warnings ?? []) as string[],
                    baseContent,
                    state: "pending",
                  },
                }));
              } else if (
                proposal.kind === "workflow" &&
                proposal.canvas_nodes &&
                proposal.changes
              ) {
                const { canvas_nodes, changes } = proposal;
                const baseFingerprint =
                  context?.surface === "workflow_editor"
                    ? canvasFingerprint(
                        context.canvas_nodes,
                        context.canvas_edges,
                      )
                    : "";
                patchAssistant(assistantId, (m) => ({
                  ...m,
                  proposal: {
                    kind: "workflow",
                    summary: proposal.summary ?? "",
                    canvas_nodes,
                    canvas_edges: proposal.canvas_edges ?? [],
                    canvas_groups: proposal.canvas_groups ?? [],
                    static_attributes: proposal.static_attributes ?? [],
                    changes,
                    warnings: (proposal.warnings ??
                      []) as WorkflowProposalWarning[],
                    baseFingerprint,
                    state: "pending",
                  },
                }));
              }
            } else if (event === "error") {
              fail((data as ErrorPayload).message ?? GENERIC_ERROR);
            } else if (event === "done") {
              sawDone = true;
            }
          }
        }
        // A proxy or network cut can end the body without `done`; don't leave a silent,
        // half-finished reply.
        if (!sawDone) {
          fail(INTERRUPTED_ERROR);
        }
      } catch (error) {
        if ((error as Error).name !== "AbortError") {
          fail(GENERIC_ERROR);
        }
      } finally {
        if (abortRef.current === controller || abortRef.current === null) {
          abortRef.current = null;
          setIsStreaming(false);
        }
      }
    },
    [patchAssistant, router],
  );

  // Null the ref synchronously so a send right after stop/clear is not dropped while the
  // aborted request's `finally` has not run yet.
  const setProposalState = useCallback(
    (messageId: string, state: ProposalState) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId && m.proposal
            ? { ...m, proposal: { ...m.proposal, state } }
            : m,
        ),
      );
    },
    [],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);
  const clear = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
    setMessages([]);
  }, []);

  return useMemo(
    () => ({ messages, isStreaming, send, stop, clear, setProposalState }),
    [messages, isStreaming, send, stop, clear, setProposalState],
  );
}
