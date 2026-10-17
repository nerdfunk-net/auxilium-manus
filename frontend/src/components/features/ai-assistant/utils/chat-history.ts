import type { ChatMessage } from "../types/ai-assistant";

/**
 * The server's limits for one chat turn. Mirrors `ChatRequest.messages` (max 50) and
 * `ChatMessageIn.content` (max 20 000 characters) in `backend/models/ai_assistant.py`;
 * `backend/tests/unit/test_ai_chat_limits_contract.py` fails when the two drift apart.
 */
export const CHAT_LIMITS = { maxMessages: 50, maxMessageChars: 20_000 } as const;

/**
 * The history to send with the next question: every earlier message plus the new one, shortened
 * to what the server accepts. A long answer keeps its end (the latest part), the oldest turns are
 * dropped beyond 50 messages, and the first message is always the user's.
 */
export function buildChatHistory(previous: ChatMessage[], next: ChatMessage): ChatMessage[] {
  let history = [...previous, next].map((message) =>
    message.content.length > CHAT_LIMITS.maxMessageChars
      ? { ...message, content: message.content.slice(-CHAT_LIMITS.maxMessageChars) }
      : message,
  );
  while (history.length > CHAT_LIMITS.maxMessages || history[0]?.role === "assistant") {
    history = history.slice(1);
  }
  return history;
}
