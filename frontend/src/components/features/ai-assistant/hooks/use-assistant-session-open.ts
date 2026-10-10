import { useCallback } from "react";

import {
  EMPTY_SESSION,
  useAssistantSessionStore,
} from "../store/assistant-session-store";

/** Open/closed state of a surface's assistant panel, kept across navigation. */
export function useAssistantSessionOpen(sessionKey: string) {
  const open = useAssistantSessionStore(
    (state) => (state.sessions[sessionKey] ?? EMPTY_SESSION).open,
  );
  const setOpen = useCallback(
    (value: boolean) =>
      useAssistantSessionStore.getState().setOpen(sessionKey, value),
    [sessionKey],
  );
  const toggle = useCallback(
    () =>
      useAssistantSessionStore
        .getState()
        .setOpen(
          sessionKey,
          !(
            useAssistantSessionStore.getState().sessions[sessionKey] ??
            EMPTY_SESSION
          ).open,
        ),
    [sessionKey],
  );
  return { open, setOpen, toggle };
}
