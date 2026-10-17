import { describe, expect, it } from "vitest";

import type { ChatMessage } from "../types/ai-assistant";
import { buildChatHistory, CHAT_LIMITS } from "./chat-history";

const user = (content: string): ChatMessage => ({ role: "user", content });
const assistant = (content: string): ChatMessage => ({ role: "assistant", content });

describe("buildChatHistory", () => {
  it("trims a 30 000-character answer to its last 20 000 characters", () => {
    const long = "a".repeat(10_000) + "b".repeat(20_000);
    const history = buildChatHistory([user("q"), assistant(long)], user("next"));
    expect(history[1].content).toHaveLength(CHAT_LIMITS.maxMessageChars);
    expect(history[1].content.endsWith("b")).toBe(true);
    expect(history[1].content.startsWith("b")).toBe(true);
  });

  it("drops the oldest turns beyond 50 messages", () => {
    const previous: ChatMessage[] = [];
    for (let i = 0; i < 40; i += 1) {
      previous.push(user(`q${i}`), assistant(`a${i}`));
    }
    const history = buildChatHistory(previous, user("last"));
    expect(history.length).toBeLessThanOrEqual(CHAT_LIMITS.maxMessages);
    expect(history[history.length - 1].content).toBe("last");
  });

  it("never starts with an assistant message", () => {
    const previous: ChatMessage[] = [];
    for (let i = 0; i < 26; i += 1) {
      previous.push(user(`q${i}`), assistant(`a${i}`));
    }
    const history = buildChatHistory(previous, user("last"));
    expect(history[0].role).toBe("user");
    expect(history.length).toBeLessThanOrEqual(CHAT_LIMITS.maxMessages);
  });

  it("leaves a short history alone", () => {
    const history = buildChatHistory([user("a"), assistant("b")], user("c"));
    expect(history.map((m) => m.content)).toEqual(["a", "b", "c"]);
  });
});
