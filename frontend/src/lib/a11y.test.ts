import type { KeyboardEvent } from "react";
import { describe, expect, it, vi } from "vitest";

import { activateOnKey } from "./a11y";

function keyEvent(key: string, sameTarget = true) {
  const target = {};
  const preventDefault = vi.fn();
  const event = {
    key,
    target,
    currentTarget: sameTarget ? target : {},
    preventDefault,
  } as unknown as KeyboardEvent<HTMLElement>;
  return { event, preventDefault };
}

describe("activateOnKey", () => {
  it("runs the action on Enter and Space and prevents the default scroll/submit", () => {
    const action = vi.fn();
    const handler = activateOnKey(action);
    for (const key of ["Enter", " "]) {
      const { event, preventDefault } = keyEvent(key);
      handler(event);
      expect(preventDefault).toHaveBeenCalled();
    }
    expect(action).toHaveBeenCalledTimes(2);
  });

  it("ignores other keys", () => {
    const action = vi.fn();
    activateOnKey(action)(keyEvent("a").event);
    activateOnKey(action)(keyEvent("Tab").event);
    expect(action).not.toHaveBeenCalled();
  });

  it("ignores keys that bubble from a nested control", () => {
    const action = vi.fn();
    activateOnKey(action)(keyEvent("Enter", false).event);
    expect(action).not.toHaveBeenCalled();
  });
});
