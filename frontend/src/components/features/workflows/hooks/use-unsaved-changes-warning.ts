"use client";

import { useEffect } from "react";

/**
 * Warns before a hard browser navigation (reload, close tab, typed URL)
 * would silently discard unsaved canvas edits. Client-side route changes
 * within the app are unaffected — those already preserve the canvas via the
 * `canvasDraft` singleton in use-workflow-builder-store.ts.
 */
export function useUnsavedChangesWarning(isDirty: boolean) {
  useEffect(() => {
    if (!isDirty) return;

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Chrome requires returnValue to be set to show the native prompt.
      event.returnValue = "";
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isDirty]);
}
