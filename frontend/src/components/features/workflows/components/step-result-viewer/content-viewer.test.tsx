"use client";

import { act } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ContentViewer } from "./content-viewer";

afterEach(() => {
  cleanup();
});

function openFind(label = "Result") {
  render(<ContentViewer content={"aaa beta aaa gamma aaa"} label={label} />);
  fireEvent.click(screen.getByRole("button", { name: "Find" }));
  return screen.getByRole("searchbox", { name: `Find in ${label}` });
}

describe("ContentViewer find", () => {
  it("uses an uncontrolled search input that keeps typed text without wrapping every match", () => {
    const content = `${"alpha ".repeat(50)}beta ${"alpha ".repeat(50)}`;
    render(<ContentViewer content={content} label="Result" />);

    fireEvent.click(screen.getByRole("button", { name: "Find" }));
    const input = screen.getByRole("searchbox", { name: "Find in Result" });
    expect(input).toHaveProperty("type", "search");

    act(() => {
      fireEvent.change(input, { target: { value: "beta" } });
    });
    expect(input).toHaveProperty("value", "beta");

    const marks = document.querySelectorAll("mark");
    expect(marks).toHaveLength(1);
    expect(marks[0]?.textContent).toBe("beta");
  });

  it("moves to the next match with Enter and the previous match with Shift+Enter", () => {
    const input = openFind();
    act(() => {
      fireEvent.change(input, { target: { value: "aaa" } });
    });

    expect(document.querySelector("mark")?.textContent).toBe("aaa");
    expect(document.querySelector("mark")?.previousSibling?.textContent ?? "").toBe("");

    act(() => {
      fireEvent.keyDown(input, { key: "Enter" });
    });
    expect(document.querySelector("mark")?.previousSibling?.textContent).toBe("aaa beta ");

    act(() => {
      fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    });
    expect(document.querySelector("mark")?.previousSibling?.textContent ?? "").toBe("");
  });

  it("advances a single match for Cmd+G even when the find field is focused", () => {
    const input = openFind();
    act(() => {
      fireEvent.change(input, { target: { value: "aaa" } });
    });

    act(() => {
      fireEvent.keyDown(input, { key: "g", metaKey: true, bubbles: true });
    });

    expect(document.querySelector("mark")?.previousSibling?.textContent).toBe("aaa beta ");
  });

  it("closes find on Escape from anywhere inside the viewer", () => {
    const input = openFind();
    act(() => {
      fireEvent.keyDown(input, { key: "Escape", bubbles: true });
    });
    expect(screen.queryByRole("searchbox", { name: "Find in Result" })).toBeNull();
  });
});
