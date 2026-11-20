import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/hooks/use-api";

import type { CompareResultProposal } from "../types/ai-assistant";
import { COMPARE_EXPIRED_MESSAGE, CompareExpiredError } from "../hooks/use-compare-result-query";
import { parseCompareResponse, type CompareResultData } from "../utils/compare-result";

const refetch = vi.fn();
const state: {
  data: CompareResultData | undefined;
  isLoading: boolean;
  error: Error | null;
  refetch: typeof refetch;
} = { data: undefined, isLoading: false, error: null, refetch };
vi.mock("../hooks/use-compare-result-query", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../hooks/use-compare-result-query")>()),
  useCompareResultQuery: () => state,
}));
const saveTextFile = vi.fn();
vi.mock("../utils/parsed-rows-export", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../utils/parsed-rows-export")>()),
  saveTextFile: (...args: unknown[]) => saveTextFile(...args),
}));

import { CompareResultCard } from "./compare-result-card";

function proposal(overrides: Partial<CompareResultProposal> = {}): CompareResultProposal {
  return {
    kind: "compare_result",
    summary: "",
    handle: "res_0123456789ab",
    repository: "Gitea CSV",
    file: "data/compare.csv",
    keyColumn: "serial",
    nautobotField: "serial",
    matchMode: "match",
    caseInsensitive: false,
    counts: { only_in_file: 2, only_in_nautobot: 1, matched_keys: 5, devices_without_value: 1 },
    partial: false,
    inlineLimit: 50,
    state: "pending",
    ...overrides,
  };
}

function data(
  file = 2,
  device = 1,
  without = 1,
  partial = false,
  both = 0,
): CompareResultData {
  const rows = [
    ...Array.from({ length: both }, (_, i) => ({
      side: "in_both", value: `B${i}`, device_name: `both${i}`, device_location: "Paris",
      device_id: `b${i}`, file_data: `bd${i}`,
    })),
    ...Array.from({ length: file }, (_, i) => ({
      side: "only_in_file", value: `F${i}`, device_name: "", device_location: "", device_id: "",
      file_data: `d${i}`,
    })),
    ...Array.from({ length: device }, (_, i) => ({
      side: "only_in_nautobot", value: `N${i}`, device_name: `dev${i}`, device_location: "Berlin",
      device_id: `id${i}`, file_data: "",
    })),
    ...Array.from({ length: without }, (_, i) => ({
      side: "without_value", value: "", device_name: `empty${i}`, device_location: "Rome",
      device_id: `e${i}`, file_data: "",
    })),
  ];
  return parseCompareResponse({
    repository: "Gitea CSV", file: "data/compare.csv", key_column: "serial",
    nautobot_field: "serial", match_mode: "match", case_insensitive: false, filters: {},
    counts: {}, columns: ["data"], partial, rows,
  })!;
}

afterEach(() => {
  cleanup();
  saveTextFile.mockReset();
  refetch.mockReset();
  state.data = undefined;
  state.isLoading = false;
  state.error = null;
});

describe("CompareResultCard", () => {
  it("shows what was compared and the counts, and says the model saw none of the values", () => {
    render(<CompareResultCard proposal={proposal()} />);
    expect(screen.getByText(/serial number in Nautobot compared with column/)).toBeTruthy();
    expect(screen.getByText("data/compare.csv")).toBeTruthy();
    const counts = within(screen.getByTestId("compare-counts"));
    expect(counts.getByText("In file only: 2")).toBeTruthy();
    expect(counts.getByText("In Nautobot only: 1")).toBeTruthy();
    expect(counts.getByText("In both: 5")).toBeTruthy();
    expect(counts.getByText("Without a value: 1")).toBeTruthy();
    expect(screen.getByText(/counts only, never the values/)).toBeTruthy();
  });

  it("shows a short result completely, with no download needed for the rest", () => {
    state.data = data();
    render(<CompareResultCard proposal={proposal()} />);
    const inFile = within(screen.getByTestId("compare-only-in-file"));
    expect(inFile.getByText("F0")).toBeTruthy();
    expect(inFile.getByText("d1")).toBeTruthy(); // a file column
    expect(within(screen.getByTestId("compare-only-in-nautobot")).getByText("dev0")).toBeTruthy();
    expect(screen.queryByText(/Showing the first/)).toBeNull();
    expect(screen.getByText(/Devices without a value in Nautobot/)).toBeTruthy();
  });

  it("lists the rows that are in the file and in Nautobot, with file columns and device", () => {
    state.data = data(1, 1, 0, false, 2);
    render(<CompareResultCard proposal={proposal()} />);
    const both = within(screen.getByTestId("compare-in-both"));
    expect(both.getByText("In the file and in Nautobot")).toBeTruthy();
    expect(both.getByText("B1")).toBeTruthy();
    expect(both.getByText("bd1")).toBeTruthy(); // a file column
    expect(both.getByText("both1")).toBeTruthy(); // the device
    expect(both.getAllByText("Paris").length).toBe(2);
  });

  it("shows only a sample of a long list and points to the download", () => {
    state.data = data(60, 1, 0);
    render(<CompareResultCard proposal={proposal()} />);
    const inFile = within(screen.getByTestId("compare-only-in-file"));
    expect(inFile.getByText("Showing the first 10 of 60. The download has all of them.")).toBeTruthy();
    expect(inFile.getByText("F9")).toBeTruthy();
    expect(inFile.queryByText("F10")).toBeNull();
    expect(screen.queryByText(/Devices without a value in Nautobot/)).toBeNull();
  });

  it("honours the inline limit of the server", () => {
    state.data = data(5, 0, 0);
    render(<CompareResultCard proposal={proposal({ inlineLimit: 3 })} />);
    expect(screen.getByText("Showing the first 3 of 5. The download has all of them.")).toBeTruthy();
  });

  it("downloads every row as a CSV with a byte order mark", () => {
    state.data = data(60, 2, 1);
    render(<CompareResultCard proposal={proposal()} />);
    fireEvent.click(screen.getByRole("button", { name: /Download CSV/ }));
    expect(saveTextFile).toHaveBeenCalledTimes(1);
    const [name, csv, mime] = saveTextFile.mock.calls[0] as [string, string, string];
    expect(name).toBe("compare-compare.csv");
    expect(mime).toBe("text/csv;charset=utf-8");
    expect(csv.startsWith("﻿side,value")).toBe(true);
    expect(csv.split("\r\n")).toHaveLength(1 + 63); // header + every row, not only the sample
  });

  it("has no download button before the lists are loaded", () => {
    state.isLoading = true;
    render(<CompareResultCard proposal={proposal()} />);
    expect(screen.getByText("Loading the lists…")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Download CSV/ })).toBeNull();
  });

  it("shows the reason when the lists cannot be read", () => {
    state.error = new Error("This comparison is no longer available");
    render(<CompareResultCard proposal={proposal()} />);
    expect(screen.getByText("This comparison is no longer available")).toBeTruthy();
  });

  it("says when the stored lists were cut", () => {
    state.data = data(1, 1, 0, true);
    render(<CompareResultCard proposal={proposal({ partial: true })} />);
    expect(screen.getByTestId("compare-partial")).toBeTruthy();
  });

  it("renders values as plain text, never as markup", () => {
    state.data = parseCompareResponse({
      counts: {}, columns: [], rows: [{ side: "only_in_file", value: "<b>bold</b>" }],
    })!;
    const { container } = render(<CompareResultCard proposal={proposal()} />);
    expect(screen.getByText("<b>bold</b>")).toBeTruthy();
    expect(container.querySelector("b")).toBeNull();
  });

  it("explains a contains match and ignoring case", () => {
    render(<CompareResultCard proposal={proposal({ matchMode: "contains", caseInsensitive: true })} />);
    expect(screen.getByText(/contains the file value, ignoring case/)).toBeTruthy();
  });

  it("shows a file column that is only filled in rows beyond the sample", () => {
    const rows = Array.from({ length: 60 }, (_, i) => ({
      side: "only_in_file",
      value: `F${i}`,
      device_name: "",
      device_location: "",
      device_id: "",
      file_data: "",
      file_late: i === 30 ? "late-value" : "",
    }));
    state.data = parseCompareResponse({
      counts: {},
      columns: ["data", "late"],
      rows,
    })!;
    render(<CompareResultCard proposal={proposal()} />);
    const inFile = within(screen.getByTestId("compare-only-in-file"));
    expect(inFile.getByRole("columnheader", { name: "late" })).toBeTruthy();
    expect(inFile.queryByRole("columnheader", { name: "data" })).toBeNull(); // empty everywhere
  });

  it("offers a retry after a transient failure and runs it on click", () => {
    state.error = new Error("Network error");
    render(<CompareResultCard proposal={proposal()} />);
    fireEvent.click(screen.getByRole("button", { name: /Try again/ }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("offers no retry when the lists are gone or the access was withdrawn", () => {
    state.error = new CompareExpiredError();
    const { unmount } = render(<CompareResultCard proposal={proposal()} />);
    expect(screen.getByText(COMPARE_EXPIRED_MESSAGE)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull();
    unmount();
    state.error = new ApiError("Forbidden", 403);
    render(<CompareResultCard proposal={proposal()} />);
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull();
  });
});
