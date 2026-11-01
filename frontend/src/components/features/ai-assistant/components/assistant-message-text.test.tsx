import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AssistantMessageText } from "./assistant-message-text";

afterEach(cleanup);

describe("AssistantMessageText line breaks", () => {
  it("keeps single newlines of an unfenced answer as line breaks", () => {
    const { container } = render(
      <AssistantMessageText markdown={"Ethernet0/0 is up\nLoopback0 is up"} />,
    );

    expect(container.querySelectorAll("br")).toHaveLength(1);
    expect(container.querySelector("p")?.innerHTML).toMatch(
      /Ethernet0\/0 is up<br>\s*Loopback0 is up/,
    );
  });

  it("does not touch a fenced block, a table or a blank-line paragraph split", () => {
    const { container } = render(
      <AssistantMessageText
        markdown={"one\n\ntwo\n\n```\na\nb\n```\n\n| h |\n|---|\n| c |"}
      />,
    );

    expect(container.querySelectorAll("br")).toHaveLength(0);
    expect(container.querySelector("pre")?.textContent).toBe("a\nb\n");
    expect(container.querySelector("table")).not.toBeNull();
  });
});
