"use client";

import { useEffect } from "react";

export interface UseWorkflowKeyboardShortcutsOptions {
  onSave: () => void;
  onSaveAs: () => void;
  onOpen: () => void;
}

/**
 * Global save/save-as/open shortcuts (Ctrl+S / Cmd+S, Ctrl+Shift+S / Cmd+Shift+S,
 * Ctrl+O / Cmd+O). Bound on window so they fire regardless of which canvas
 * element has focus; preventDefault stops the browser's own save/open dialogs.
 */
export function useWorkflowKeyboardShortcuts({
  onSave,
  onSaveAs,
  onOpen,
}: UseWorkflowKeyboardShortcutsOptions) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!event.metaKey && !event.ctrlKey) return;

      switch (event.key.toLowerCase()) {
        case "s":
          event.preventDefault();
          if (event.shiftKey) {
            onSaveAs();
          } else {
            onSave();
          }
          break;
        case "o":
          event.preventDefault();
          onOpen();
          break;
        default:
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onSave, onSaveAs, onOpen]);
}
