import { create } from "zustand";

import type { DisplayMessage } from "../types/ai-assistant";

/** Sessions kept in memory; the least recently used one is dropped beyond this. */
export const MAX_SESSIONS = 10;

/**
 * One assistant conversation as the user left it. Keyed by surface and subject (for example
 * `workflow_editor:12`), so going back to a page restores its chat. Memory only: a reload,
 * logout or 401 clears everything, because the messages can hold device or run data.
 */
export interface AssistantSession {
  open: boolean;
  messages: DisplayMessage[];
  draft: string;
}

interface AssistantSessionState {
  sessions: Record<string, AssistantSession>;
  /** Keys from least to most recently used. */
  order: string[];
  setOpen: (key: string, open: boolean) => void;
  setDraft: (key: string, draft: string) => void;
  updateMessages: (
    key: string,
    update: (messages: DisplayMessage[]) => DisplayMessage[],
  ) => void;
  clearSession: (key: string) => void;
  resetAll: () => void;
}

export const EMPTY_SESSION: AssistantSession = Object.freeze({
  open: false,
  messages: [],
  draft: "",
}) as AssistantSession;

/** Writes `next` for `key`, marks it most recently used and evicts the oldest overflow. */
function withSession(
  state: Pick<AssistantSessionState, "sessions" | "order">,
  key: string,
  next: AssistantSession,
): Pick<AssistantSessionState, "sessions" | "order"> {
  const order = [...state.order.filter((k) => k !== key), key];
  const evicted = order.length > MAX_SESSIONS ? order.shift() : undefined;
  const sessions = { ...state.sessions, [key]: next };
  if (evicted !== undefined) {
    delete sessions[evicted];
  }
  return { sessions, order };
}

export const useAssistantSessionStore = create<AssistantSessionState>(
  (set) => ({
    sessions: {},
    order: [],
    setOpen: (key, open) =>
      set((state) =>
        withSession(state, key, {
          ...(state.sessions[key] ?? EMPTY_SESSION),
          open,
        }),
      ),
    setDraft: (key, draft) =>
      set((state) =>
        withSession(state, key, {
          ...(state.sessions[key] ?? EMPTY_SESSION),
          draft,
        }),
      ),
    updateMessages: (key, update) =>
      set((state) => {
        const current = state.sessions[key] ?? EMPTY_SESSION;
        return withSession(state, key, {
          ...current,
          messages: update(current.messages),
        });
      }),
    clearSession: (key) =>
      set((state) =>
        state.sessions[key]
          ? withSession(state, key, {
              ...state.sessions[key],
              messages: [],
              draft: "",
            })
          : state,
      ),
    resetAll: () => set({ sessions: {}, order: [] }),
  }),
);
