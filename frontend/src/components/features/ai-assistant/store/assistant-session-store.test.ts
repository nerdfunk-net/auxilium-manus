import { beforeEach, describe, expect, it } from "vitest";

import {
  MAX_SESSIONS,
  useAssistantSessionStore,
} from "./assistant-session-store";

const state = () => useAssistantSessionStore.getState();
const msg = (id: string, content = "hi") => ({
  id,
  role: "user" as const,
  content,
});

beforeEach(() => state().resetAll());

describe("assistant session store", () => {
  it("keeps sessions isolated per key", () => {
    state().updateMessages("a", (m) => [...m, msg("1")]);
    state().setOpen("b", true);
    expect(state().sessions.a.messages).toHaveLength(1);
    expect(state().sessions.a.open).toBe(false);
    expect(state().sessions.b.messages).toHaveLength(0);
    expect(state().sessions.b.open).toBe(true);
  });

  it("stores the draft per session", () => {
    state().setDraft("a", "typing");
    expect(state().sessions.a.draft).toBe("typing");
    expect(state().sessions.b).toBeUndefined();
  });

  it("clearSession drops messages and draft but keeps the open state", () => {
    state().setOpen("a", true);
    state().setDraft("a", "x");
    state().updateMessages("a", () => [msg("1")]);
    state().clearSession("a");
    expect(state().sessions.a).toEqual({
      open: true,
      messages: [],
      draft: "",
      savedId: null,
    });
  });

  it("clearSession on an unknown key is a no-op", () => {
    state().clearSession("nope");
    expect(state().sessions).toEqual({});
  });

  it("evicts the least recently used session beyond the cap", () => {
    for (let i = 0; i < MAX_SESSIONS; i += 1) {
      state().setOpen(`k${i}`, true);
    }
    state().setDraft("k0", "touched"); // k0 becomes most recent
    state().setOpen("overflow", true);
    expect(Object.keys(state().sessions)).toHaveLength(MAX_SESSIONS);
    expect(state().sessions.k1).toBeUndefined();
    expect(state().sessions.k0).toBeDefined();
    expect(state().sessions.overflow).toBeDefined();
  });

  it("resetAll removes every session", () => {
    state().setOpen("a", true);
    state().resetAll();
    expect(state().sessions).toEqual({});
    expect(state().order).toEqual([]);
  });

  it("never mutates a previous messages array", () => {
    state().updateMessages("a", () => [msg("1")]);
    const before = state().sessions.a.messages;
    state().updateMessages("a", (m) => [...m, msg("2")]);
    expect(before).toHaveLength(1);
  });

  it("loadSaved replaces the chat, clears the draft and remembers the saved id", () => {
    state().setDraft("a", "typing");
    state().updateMessages("a", () => [msg("old")]);
    state().loadSaved("a", [msg("new1"), msg("new2")], 42);
    expect(state().sessions.a.messages.map((m) => m.id)).toEqual([
      "new1",
      "new2",
    ]);
    expect(state().sessions.a.draft).toBe("");
    expect(state().sessions.a.savedId).toBe(42);
  });

  it("clearSession forgets the saved id so the next save creates a new row", () => {
    state().loadSaved("a", [msg("1")], 7);
    state().clearSession("a");
    expect(state().sessions.a.savedId).toBeNull();
  });

  it("setSavedId only touches its own session", () => {
    state().setSavedId("a", 3);
    expect(state().sessions.a.savedId).toBe(3);
    expect(state().sessions.b).toBeUndefined();
  });
});
