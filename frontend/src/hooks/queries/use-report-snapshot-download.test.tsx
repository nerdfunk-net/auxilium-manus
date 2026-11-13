import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useReportSnapshotDownload } from "./use-report-snapshot-download";

vi.mock("@/hooks/use-api", () => ({
  buildApiErrorMessage: vi.fn(async () => "Not allowed"),
}));
vi.mock("@/lib/auth-store", () => ({
  useAuthStore: { getState: () => ({ markPasswordChangeRequired: vi.fn() }) },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const fetchMock = vi.fn();
let clicked: HTMLAnchorElement | null = null;

beforeEach(() => {
  fetchMock.mockReset();
  clicked = null;
  vi.stubGlobal("fetch", fetchMock);
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
  // The hook clicks a link it just added to the page: note which one.
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {
    clicked = document.querySelector("a[download]");
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useReportSnapshotDownload", () => {
  it("fetches the csv of the snapshot and saves it under the server's name", async () => {
    fetchMock.mockResolvedValue(
      new Response("a,b", {
        headers: { "Content-Disposition": 'attachment; filename="Serials.csv"' },
      }),
    );
    const { result } = renderHook(() => useReportSnapshotDownload("csv"), {
      wrapper,
    });

    await act(async () => {
      await result.current.mutateAsync(7);
    });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/proxy/reports/snapshots/7/csv");
    expect(clicked?.download).toBe("Serials.csv");
  });

  it("falls back to a name with the format's extension", async () => {
    fetchMock.mockResolvedValue(new Response("%PDF"));
    const { result } = renderHook(() => useReportSnapshotDownload("pdf"), {
      wrapper,
    });

    await act(async () => {
      await result.current.mutateAsync(3);
    });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/proxy/reports/snapshots/3/pdf");
    expect(clicked?.download).toBe("report-3.pdf");
  });

  it("shows the server's reason when the download is refused", async () => {
    fetchMock.mockResolvedValue(new Response("no", { status: 422 }));
    const { result } = renderHook(() => useReportSnapshotDownload("csv"), {
      wrapper,
    });

    act(() => result.current.mutate(9));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Not allowed");
    expect(clicked).toBeNull();
  });
});
