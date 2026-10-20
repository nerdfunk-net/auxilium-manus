import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Testing Library only registers its own cleanup when vitest runs with `globals: true`.
// Without this, hooks and components from earlier tests stay mounted and keep reacting.
afterEach(() => {
  cleanup();
});

// jsdom has no ResizeObserver; Radix primitives (Switch, Select, Popover, ...) construct one.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
