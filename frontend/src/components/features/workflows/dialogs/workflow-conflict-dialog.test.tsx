import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WorkflowConflictDialog } from "./workflow-conflict-dialog";

function setup(open = true) {
  const handlers = {
    onOpenChange: vi.fn(),
    onReload: vi.fn(),
    onSaveAsNew: vi.fn(),
    onOverwrite: vi.fn(),
  };
  render(<WorkflowConflictDialog open={open} {...handlers} />);
  return handlers;
}

describe("WorkflowConflictDialog", () => {
  it("renders nothing while closed", () => {
    setup(false);
    expect(screen.queryByText("This workflow changed")).toBeNull();
  });

  it("explains the conflict and offers all four choices", () => {
    setup();
    expect(screen.getByText("This workflow changed")).toBeTruthy();
    for (const name of [
      "Keep editing",
      "Save as new workflow",
      "Reload (discard my edits)",
      "Overwrite",
    ]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
  });

  it("wires each choice to its handler", () => {
    const handlers = setup();
    fireEvent.click(screen.getByRole("button", { name: "Save as new workflow" }));
    fireEvent.click(screen.getByRole("button", { name: "Reload (discard my edits)" }));
    fireEvent.click(screen.getByRole("button", { name: "Overwrite" }));
    expect(handlers.onSaveAsNew).toHaveBeenCalledTimes(1);
    expect(handlers.onReload).toHaveBeenCalledTimes(1);
    expect(handlers.onOverwrite).toHaveBeenCalledTimes(1);
    expect(handlers.onOpenChange).not.toHaveBeenCalled();
  });

  it("closes without choosing when the user keeps editing", () => {
    const handlers = setup();
    fireEvent.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(handlers.onOpenChange).toHaveBeenCalledWith(false);
    expect(handlers.onOverwrite).not.toHaveBeenCalled();
  });

  // Layout regression (found in the browser at 1200px): the four actions sit in a row inside a
  // fixed-width card; they must be allowed to wrap, or buttons overflow the card.
  it("lets the actions wrap instead of overflowing the card", () => {
    setup();
    const overwrite = screen.getByRole("button", { name: "Overwrite" });
    const group = overwrite.parentElement as HTMLElement;
    const footer = group.parentElement as HTMLElement;
    expect(group.className).toContain("flex-wrap");
    expect(footer.className).toContain("flex-wrap");
    expect(screen.getByRole("dialog").className).toContain("sm:max-w-2xl");
  });
});
