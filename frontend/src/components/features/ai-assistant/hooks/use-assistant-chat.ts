"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { buildApiErrorMessage } from "@/hooks/use-api";
import { useAuthStore } from "@/lib/auth-store";

import type { ChatMessage, DisplayMessage } from "../types/ai-assistant";
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

let messageCounter = 0;
function nextId(): string {
  messageCounter += 1;
  return `m${messageCounter}`;
}

/**
 * Client-held chat (v1 is stateless on the server): the history is re-sent each turn and
 * is lost on reload. Streams the reply over SSE through the Next.js proxy.
 */
export function useAssistantChat() {
  const router = useRouter();
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const messagesRef = useRef<DisplayMessage[]>([]);

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
          body: JSON.stringify({ messages: history }),
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

        const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
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
              patchAssistant(assistantId, (m) => ({ ...m, content: m.content + delta }));
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
    () => ({ messages, isStreaming, send, stop, clear }),
    [messages, isStreaming, send, stop, clear],
  );
}
