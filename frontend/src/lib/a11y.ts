import type { KeyboardEvent } from "react";

/**
 * Keyboard twin of an `onClick` on a non-button element that has `role="button"` (or similar):
 * Enter and Space run the action. Ignores keys that bubble up from a nested control, so typing in
 * an input inside the row does not trigger it.
 */
export function activateOnKey(action: () => void) {
  return (event: KeyboardEvent<HTMLElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      action();
    }
  };
}
