import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAssistantSessionStore } from "../store/assistant-session-store";
import type {
  SavedConversation,
  SavedConversationSummary,
} from "../types/ai-assistant";
import { AssistantPanel } from "./assistant-panel";

const saveMutate = vi.fn();
const loadMutate = vi.fn();
const removeMutate = vi.fn();
let listData: SavedConversationSummary[] = [];

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/hooks/queries/use-ai-conversations-query", () => ({
  useAiConversationsQuery: () => ({
    data: listData,
    isLoading: false,
    isError: false,
  }),
}));
vi.mock("@/hooks/queries/use-ai-conversations-mutations", () => ({
  useAiConversationsMutations: () => ({
    save: { mutate: saveMutate, isPending: false },
    load: { mutate: loadMutate, isPending: false },
    remove: { mutate: removeMutate, isPending: false },
  }),
}));

const KEY = "workflow_editor:12";
const SCOPE = { surface: "workflow_editor", subjectKey: "12" } as const;

const state = () => useAssistantSessionStore.getState();
const seed = () =>
  state().updateMessages(KEY, () => [
    { id: "1", role: "user", content: "add a step" },
    { id: "2", role: "assistant", content: "ok" },
  ]);

afterEach(cleanup);

beforeEach(() => {
  state().resetAll();
  saveMutate.mockReset();
  loadMutate.mockReset();
  removeMutate.mockReset();
  listData = [];
});

describe("AssistantPanel saved conversations", () => {
  it("hides Save and Saved without a scope", () => {
    render(<AssistantPanel sessionKey={KEY} />);
    expect(screen.queryByRole("button", { name: /save/i })).toBeNull();
  });

  it("disables Save for an empty chat", () => {
    render(<AssistantPanel sessionKey={KEY} conversationScope={SCOPE} />);
    expect(
      (screen.getByRole("button", { name: /^save$/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("saves new, then remembers the id so the next save updates", () => {
    seed();
    render(<AssistantPanel sessionKey={KEY} conversationScope={SCOPE} />);

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    const [input, options] = saveMutate.mock.calls[0];
    expect(input.savedId).toBeNull();
    expect(input.scope).toEqual(SCOPE);
    expect(input.messages.map((m: { content: string }) => m.content)).toEqual([
      "add a step",
      "ok",
    ]);

    options.onSuccess({ id: 9 });
    expect(state().sessions[KEY].savedId).toBe(9);
  });

  it("resumes a saved conversation into the session", () => {
    listData = [
      {
        id: 5,
        surface: "workflow_editor",
        subject_key: "12",
        title: "Backup chat",
        message_count: 2,
        created_at: "2026-10-10T10:00:00Z",
        updated_at: "2026-10-10T10:00:00Z",
      },
    ];
    render(<AssistantPanel sessionKey={KEY} conversationScope={SCOPE} />);

    fireEvent.click(screen.getByRole("button", { name: /^saved$/i }));
    fireEvent.click(screen.getByRole("button", { name: /resume/i }));
    const [id, options] = loadMutate.mock.calls[0];
    expect(id).toBe(5);

    const conversation: SavedConversation = {
      ...listData[0],
      messages: [
        { role: "user", content: "earlier question", tools: [] },
        {
          role: "assistant",
          content: "earlier answer",
          tools: [],
          proposal: { kind: "workflow", summary: "adds backup" },
        },
      ],
    };
    options.onSuccess(conversation);

    expect(state().sessions[KEY].savedId).toBe(5);
    expect(state().sessions[KEY].messages.map((m) => m.content)).toEqual([
      "earlier question",
      "earlier answer",
    ]);
  });

  it("forgets the saved id when the open conversation is deleted", () => {
    state().loadSaved(KEY, [{ id: "1", role: "user", content: "x" }], 5);
    listData = [
      {
        id: 5,
        surface: "workflow_editor",
        subject_key: "12",
        title: "Backup chat",
        message_count: 1,
        created_at: "2026-10-10T10:00:00Z",
        updated_at: "2026-10-10T10:00:00Z",
      },
    ];
    render(<AssistantPanel sessionKey={KEY} conversationScope={SCOPE} />);

    fireEvent.click(screen.getByRole("button", { name: /^saved$/i }));
    fireEvent.click(
      screen.getByRole("button", { name: /delete backup chat/i }),
    );
    removeMutate.mock.calls[0][1].onSuccess();

    expect(state().sessions[KEY].savedId).toBeNull();
  });
});
