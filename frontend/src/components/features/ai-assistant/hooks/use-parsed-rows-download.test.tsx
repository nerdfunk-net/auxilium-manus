import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useParsedRowsDownload } from "./use-parsed-rows-download";

const apiCall = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));

const saveTextFile = vi.fn();
vi.mock("../utils/parsed-rows-export", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../utils/parsed-rows-export")>()),
  saveTextFile: (...args: unknown[]) => saveTextFile(...args),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const HANDLE = "res_0123456789ab";

beforeEach(() => {
  apiCall.mockReset();
  saveTextFile.mockReset();
  apiCall.mockResolvedValue({
    parser: "textfsm",
    rows: [{ _command: "show version", hostname: "r1" }],
  });
});

describe("useParsedRowsDownload", () => {
  it("fetches the rows by handle and saves them as CSV", async () => {
    const { result } = renderHook(() => useParsedRowsDownload(), { wrapper });

    await result.current.mutateAsync({
      handle: HANDLE,
      format: "csv",
      deviceName: "LAB.local.zz",
    });

    expect(apiCall).toHaveBeenCalledWith(`ai/results/${HANDLE}/rows`, {
      method: "GET",
    });
    expect(saveTextFile).toHaveBeenCalledWith(
      "lab-local-zz-parsed.csv",
      "_command,hostname\r\nshow version,r1",
      "text/csv;charset=utf-8",
    );
  });

  it("saves JSON when asked", async () => {
    const { result } = renderHook(() => useParsedRowsDownload(), { wrapper });

    await result.current.mutateAsync({
      handle: HANDLE,
      format: "json",
      deviceName: "LAB",
    });

    const [name, text, mime] = saveTextFile.mock.calls[0];
    expect(name).toBe("lab-parsed.json");
    expect(JSON.parse(text)).toEqual([
      { _command: "show version", hostname: "r1" },
    ]);
    expect(mime).toBe("application/json");
  });

  it("refuses a handle that is not shaped like one, without a request", async () => {
    const { result } = renderHook(() => useParsedRowsDownload(), { wrapper });

    await expect(
      result.current.mutateAsync({
        handle: "../etc/passwd",
        format: "json",
        deviceName: "LAB",
      }),
    ).rejects.toThrow(/cannot be downloaded/);
    expect(apiCall).not.toHaveBeenCalled();
  });

  it("saves nothing when the server refuses", async () => {
    apiCall.mockRejectedValue(new Error("Unknown or expired result"));
    const { result } = renderHook(() => useParsedRowsDownload(), { wrapper });

    await expect(
      result.current.mutateAsync({
        handle: HANDLE,
        format: "json",
        deviceName: "LAB",
      }),
    ).rejects.toThrow("Unknown or expired result");
    expect(saveTextFile).not.toHaveBeenCalled();
  });
});
