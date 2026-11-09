import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ConfigDownloadProposal } from "../types/ai-assistant";

const mutate = vi.fn();
const state = { isPending: false, error: null as Error | null };
vi.mock("../hooks/use-config-download", () => ({
  useConfigDownload: () => ({ mutate, ...state }),
}));

import { ConfigDownloadCard } from "./config-download-card";

function proposal(
  overrides: Partial<ConfigDownloadProposal> = {},
): ConfigDownloadProposal {
  return {
    kind: "config_download",
    summary: "",
    handle: "res_0123456789ab",
    device: "LAB",
    configKind: "running",
    repository: "backups",
    committedAt: "2026-11-01T10:00:00+00:00",
    sizeChars: 40000,
    lineCount: 1500,
    partial: false,
    state: "pending",
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  mutate.mockReset();
  state.isPending = false;
  state.error = null;
});

describe("ConfigDownloadCard", () => {
  it("names the device, the size and the source", () => {
    render(<ConfigDownloadCard proposal={proposal()} />);

    expect(screen.getByText("LAB")).toBeTruthy();
    expect(screen.getByText("1,500 lines, 39 KB")).toBeTruthy();
    expect(screen.getByText(/backups/)).toBeTruthy();
  });

  it("downloads the stored handle on click", () => {
    render(<ConfigDownloadCard proposal={proposal()} />);

    fireEvent.click(screen.getByRole("button", { name: /download config/i }));

    expect(mutate).toHaveBeenCalledWith({ handle: "res_0123456789ab" });
  });

  it("disables the button while downloading", () => {
    state.isPending = true;
    render(<ConfigDownloadCard proposal={proposal()} />);

    expect(
      (
        screen.getByRole("button", {
          name: /download config/i,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });

  it("shows the error text", () => {
    state.error = new Error("Unknown or expired result");
    render(<ConfigDownloadCard proposal={proposal()} />);

    expect(screen.getByText("Unknown or expired result")).toBeTruthy();
  });

  it("warns when only the start of the file is included", () => {
    render(<ConfigDownloadCard proposal={proposal({ partial: true })} />);

    expect(screen.getByText(/only its start/i)).toBeTruthy();
  });
});
