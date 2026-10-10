import { describe, expect, it } from "vitest";

import type { DisplayMessage, SavedMessage } from "../types/ai-assistant";
import { fromSavedMessages, toSavedMessages } from "./conversation-mapping";

describe("toSavedMessages", () => {
  it("keeps a proposal as kind and summary only", () => {
    const messages: DisplayMessage[] = [
      { id: "1", role: "user", content: "shorten it" },
      {
        id: "2",
        role: "assistant",
        content: "done",
        proposal: {
          kind: "template",
          content: "FULL BODY",
          summary: "shorter",
          warnings: [],
          baseContent: "old",
          state: "pending",
        },
      },
    ];

    const saved = toSavedMessages(messages);

    expect(saved[1].proposal).toEqual({ kind: "template", summary: "shorter" });
    expect(JSON.stringify(saved)).not.toContain("FULL BODY");
  });

  it("stores a running tool chip as done and drops empty cancelled turns", () => {
    const messages: DisplayMessage[] = [
      {
        id: "1",
        role: "assistant",
        content: "x",
        tools: [{ id: "t", name: "get_run", status: "running" }],
      },
      { id: "2", role: "assistant", content: "" },
    ];

    const saved = toSavedMessages(messages);

    expect(saved).toHaveLength(1);
    expect(saved[0].tools[0]).toMatchObject({
      name: "get_run",
      status: "done",
    });
  });

  it("round-trips a resumed proposal summary", () => {
    const restored = fromSavedMessages([
      {
        role: "assistant",
        content: "a",
        tools: [],
        proposal: { kind: "workflow", summary: "adds a step" },
      },
    ]);
    expect(toSavedMessages(restored)[0].proposal).toEqual({
      kind: "workflow",
      summary: "adds a step",
    });
  });
});

describe("fromSavedMessages", () => {
  it("builds display messages with fresh unique ids", () => {
    const saved: SavedMessage[] = [
      { role: "user", content: "hi", tools: [] },
      {
        role: "assistant",
        content: "yo",
        error: "boom",
        tools: [
          {
            id: "t",
            name: "list_steps",
            status: "done",
            truncated: false,
            withheld: [],
          },
        ],
      },
    ];

    const messages = fromSavedMessages(saved);

    expect(new Set(messages.map((m) => m.id)).size).toBe(2);
    expect(messages[1]).toMatchObject({ error: "boom" });
    expect(messages[1].tools).toHaveLength(1);
    expect(messages[0].tools).toBeUndefined();
    expect(messages[0].savedProposal).toBeUndefined();
  });
});
