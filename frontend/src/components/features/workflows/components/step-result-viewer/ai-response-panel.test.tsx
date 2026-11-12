import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  AI_RESPONSE_METADATA_SUFFIX,
  AiResponsePanel,
  extractAiResponses,
} from "./ai-response-panel";
import { metadataWithoutDebugPanels } from "./metadata-panel";

const OK = {
  status: "ok",
  response: "Backups finished: 5 ok, 1 failed.",
  provider: "anthropic",
  model: "m",
  output_attribute: "ai.response",
  prompt_chars: 1234,
};

describe("extractAiResponses", () => {
  it("returns only well-formed entries under the suffix", () => {
    const entries = extractAiResponses({
      [`node_1${AI_RESPONSE_METADATA_SUFFIX}`]: OK,
      [`node_2${AI_RESPONSE_METADATA_SUFFIX}`]: { nope: true },
      other: OK,
    });
    expect(entries).toHaveLength(1);
    expect(entries[0].response).toContain("Backups finished");
  });

  it("is hidden from the generic metadata list", () => {
    const rest = metadataWithoutDebugPanels({
      [`node_1${AI_RESPONSE_METADATA_SUFFIX}`]: OK,
      kept: 1,
    });
    expect(Object.keys(rest)).toEqual(["kept"]);
  });
});

describe("AiResponsePanel", () => {
  it("shows the answer and where it is stored", () => {
    render(<AiResponsePanel entries={[OK as never]} />);
    expect(screen.getByText("Backups finished: 5 ok, 1 failed.")).toBeTruthy();
    expect(screen.getByText("answered")).toBeTruthy();
    expect(screen.getByText("→ {ai.response}")).toBeTruthy();
  });

  it("shows the reason when the step failed", () => {
    render(<AiResponsePanel entries={[{ status: "failed", reason: "AI is not available" }]} />);
    expect(screen.getByText("failed")).toBeTruthy();
    expect(screen.getByText("AI is not available")).toBeTruthy();
  });

  it("shows a skipped step with its reason", () => {
    render(
      <AiResponsePanel
        entries={[{ status: "skipped", reason: "no device to attach the answer to" }]}
      />,
    );
    expect(screen.getByText("skipped")).toBeTruthy();
    expect(screen.getByText("no device to attach the answer to")).toBeTruthy();
  });

  it("renders nothing without entries", () => {
    const { container } = render(<AiResponsePanel entries={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
