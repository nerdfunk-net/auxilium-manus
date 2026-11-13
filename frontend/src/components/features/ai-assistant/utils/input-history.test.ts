import { describe, expect, it } from "vitest";

import {
  INITIAL_INPUT_HISTORY,
  caretOnFirstLine,
  caretOnLastLine,
  stepNewer,
  stepOlder,
} from "./input-history";

const ENTRIES = ["one", "two", "three"];

describe("caret position", () => {
  it("allows Up only on the first line", () => {
    expect(caretOnFirstLine("ab\ncd", 1, 1)).toBe(true);
    expect(caretOnFirstLine("ab\ncd", 2, 2)).toBe(true);
    expect(caretOnFirstLine("ab\ncd", 4, 4)).toBe(false);
  });

  it("allows Down only on the last line", () => {
    expect(caretOnLastLine("ab\ncd", 4, 4)).toBe(true);
    expect(caretOnLastLine("ab\ncd", 1, 1)).toBe(false);
  });

  it("never counts a selection", () => {
    expect(caretOnFirstLine("abc", 0, 2)).toBe(false);
    expect(caretOnLastLine("abc", 0, 2)).toBe(false);
  });
});

describe("stepping", () => {
  it("does nothing without history", () => {
    expect(stepOlder(INITIAL_INPUT_HISTORY, [], "x").value).toBeNull();
  });

  it("walks back, stops at the oldest, and returns to the draft", () => {
    const first = stepOlder(INITIAL_INPUT_HISTORY, ENTRIES, "draft");
    expect(first.value).toBe("three");
    const second = stepOlder(first.state, ENTRIES, "three");
    expect(second.value).toBe("two");
    const third = stepOlder(second.state, ENTRIES, "two");
    expect(third.value).toBe("one");
    expect(stepOlder(third.state, ENTRIES, "one").value).toBeNull();

    const back = stepNewer(third.state, ENTRIES);
    expect(back.value).toBe("two");
    const newest = stepNewer(stepNewer(back.state, ENTRIES).state, ENTRIES);
    expect(newest.value).toBe("draft");
    expect(newest.state).toEqual(INITIAL_INPUT_HISTORY);
  });

  it("ignores Down when not browsing", () => {
    expect(stepNewer(INITIAL_INPUT_HISTORY, ENTRIES).value).toBeNull();
  });
});
