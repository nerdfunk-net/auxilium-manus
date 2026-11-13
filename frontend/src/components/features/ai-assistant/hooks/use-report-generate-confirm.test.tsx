import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useReportGenerateConfirmMutation } from "./use-report-generate-confirm";

const apiCall = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  apiCall.mockReset();
  apiCall.mockResolvedValue({
    snapshot_id: 9,
    name: "Serials - now",
    status: "partial",
    sections_failed: 1,
  });
});

describe("useReportGenerateConfirmMutation", () => {
  it("posts only the token and maps the answer", async () => {
    const { result } = renderHook(() => useReportGenerateConfirmMutation(), {
      wrapper,
    });

    const mapped = await result.current.mutateAsync("signed.token");

    const [endpoint, init] = apiCall.mock.calls[0];
    expect(endpoint).toBe("ai/exec/report-generate");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ token: "signed.token" });
    expect(mapped).toEqual({
      snapshotId: 9,
      name: "Serials - now",
      status: "partial",
      sectionsFailed: 1,
    });
  });

  it("is not retried, because a retry would make a second snapshot", async () => {
    apiCall.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useReportGenerateConfirmMutation(), {
      wrapper,
    });

    await expect(result.current.mutateAsync("t")).rejects.toThrow("boom");
    expect(apiCall).toHaveBeenCalledTimes(1);
  });
});
