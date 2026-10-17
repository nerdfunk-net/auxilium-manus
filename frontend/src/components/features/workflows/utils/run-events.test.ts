import { describe, expect, it } from "vitest";

import type { WorkflowRunEvent } from "../types/workflow-runs";
import { eventsForStep, formatRunEvent, latestEventsByStep, mergeRunEvents } from "./run-events";

function event(id: number, overrides: Partial<WorkflowRunEvent> = {}): WorkflowRunEvent {
  return {
    id,
    step_node_id: "a",
    child_index: null,
    device_name: null,
    level: "info",
    kind: "connect_attempt",
    message: `event ${id}`,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("mergeRunEvents", () => {
  it("appends a page to the previous state and advances the cursor", () => {
    const merged = mergeRunEvents(
      { events: [event(1)], nextAfterId: 1 },
      { events: [event(2), event(3)], next_after_id: 3 },
    );
    expect(merged.events.map((e) => e.id)).toEqual([1, 2, 3]);
    expect(merged.nextAfterId).toBe(3);
  });

  it("returns the previous state object when the page is empty", () => {
    const previous = { events: [event(1)], nextAfterId: 1 };
    expect(mergeRunEvents(previous, { events: [], next_after_id: 1 })).toBe(previous);
  });

  it("starts from an empty state", () => {
    const merged = mergeRunEvents(undefined, { events: [event(5)], next_after_id: 5 });
    expect(merged).toEqual({ events: [event(5)], nextAfterId: 5 });
  });

  it("ignores events it already has (overlapping pages)", () => {
    const merged = mergeRunEvents(
      { events: [event(1), event(2)], nextAfterId: 2 },
      { events: [event(2), event(3)], next_after_id: 3 },
    );
    expect(merged.events.map((e) => e.id)).toEqual([1, 2, 3]);
  });
});

describe("eventsForStep / latestEventsByStep", () => {
  const events = [
    event(1, { step_node_id: "a" }),
    event(2, { step_node_id: "b" }),
    event(3, { step_node_id: "a", level: "error" }),
  ];

  it("filters by step node id, keeping order", () => {
    expect(eventsForStep(events, "a").map((e) => e.id)).toEqual([1, 3]);
    expect(eventsForStep(events, "zzz")).toEqual([]);
  });

  it("keeps the most recent event per step", () => {
    const latest = latestEventsByStep(events);
    expect(latest.get("a")?.id).toBe(3);
    expect(latest.get("b")?.id).toBe(2);
  });
});

describe("formatRunEvent", () => {
  it("prefixes the device name when present", () => {
    expect(formatRunEvent(event(1, { device_name: "r1", message: "timeout" }))).toBe(
      "r1: timeout",
    );
  });

  it("returns the bare message without a device", () => {
    expect(formatRunEvent(event(1, { message: "hello" }))).toBe("hello");
  });
});
