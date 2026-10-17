import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MarkdownView } from "./markdown-view";

afterEach(cleanup);

describe("MarkdownView", () => {
  it("renders headings and GitHub-style tables", () => {
    render(<MarkdownView markdown={"# Fleet\n\n| a | n |\n| --- | --- |\n| x | 1 |\n"} />);

    expect(screen.getByRole("heading", { name: "Fleet" })).toBeTruthy();
    expect(screen.getByRole("table")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "a" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "x" })).toBeTruthy();
  });

  it("does not render raw HTML or script", () => {
    const { container } = render(
      <MarkdownView markdown={'<script>alert(1)</script><img src=x onerror=alert(1)>\n\ntext'} />,
    );

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("text")).toBeTruthy();
  });

  it("does not load images from the text", () => {
    const { container } = render(<MarkdownView markdown={"![x](https://evil.example/p.png)"} />);

    expect(container.querySelector("img")).toBeNull();
  });

  it("opens links in a new tab without leaking the opener", () => {
    const { container } = render(<MarkdownView markdown={"[docs](https://example.com)"} />);

    const link = container.querySelector("a");
    expect(link?.getAttribute("target")).toBe("_blank");
    expect(link?.getAttribute("rel")).toContain("noopener");
  });

  it("drops javascript: links", () => {
    const { container } = render(<MarkdownView markdown={"[click](javascript:alert(1))"} />);

    const link = container.querySelector("a");
    expect(link?.getAttribute("href") ?? "").not.toContain("javascript:");
  });
});
