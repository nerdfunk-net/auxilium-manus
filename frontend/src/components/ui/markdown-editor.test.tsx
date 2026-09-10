import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";

import { MarkdownEditor } from "./markdown-editor";

afterEach(cleanup);

// Radix Tabs activates a trigger on pointer-down (jsdom's synthetic `click`
// alone doesn't switch it).
function selectTab(name: string) {
  const tab = screen.getByRole("tab", { name });
  fireEvent.mouseDown(tab);
  fireEvent.click(tab);
}

function Harness({
  initial = "",
  onChange,
}: {
  initial?: string;
  onChange?: (value: string) => void;
}) {
  const [value, setValue] = useState(initial);
  return (
    <MarkdownEditor
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
      placeholder="Write docs…"
    />
  );
}

describe("MarkdownEditor", () => {
  it("reports edits through onChange", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    fireEvent.change(screen.getByPlaceholderText("Write docs…"), {
      target: { value: "# Title" },
    });

    expect(onChange).toHaveBeenLastCalledWith("# Title");
  });

  it("renders the Markdown in the Preview tab", () => {
    render(<Harness initial={"# Heading\n\n- one\n- two"} />);

    selectTab("Preview");

    expect(
      screen.getByRole("heading", { level: 1, name: "Heading" }),
    ).toBeDefined();
    expect(screen.getByText("one")).toBeDefined();
  });

  it("shows an empty-state hint when there is nothing to preview", () => {
    render(<Harness initial="   " />);

    selectTab("Preview");

    expect(screen.getByText("Nothing to preview yet.")).toBeDefined();
  });
});
