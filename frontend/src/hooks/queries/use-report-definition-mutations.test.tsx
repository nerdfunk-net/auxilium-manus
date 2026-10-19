import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query-keys";
import { createQueryWrapper } from "@/test/query-wrapper";

import { useReportDefinitionMutations } from "./use-report-definition-mutations";

const apiCall = vi.fn();
const toast = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast }) }));

beforeEach(() => {
  apiCall.mockReset();
  toast.mockReset();
});

function setup() {
  const { client, wrapper } = createQueryWrapper();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const { result } = renderHook(() => useReportDefinitionMutations(), { wrapper });
  return { client, result, invalidate };
}

const invalidatedKeys = (spy: { mock: { calls: unknown[][] } }) =>
  spy.mock.calls.map(([filters]) => (filters as { queryKey: unknown }).queryKey);

const DEFINITIONS = queryKeys.reports.definitions();
const SNAPSHOTS = queryKeys.reports.snapshots();

describe("useReportDefinitionMutations", () => {
  it("createDefinition posts the input and refreshes the definitions", async () => {
    apiCall.mockResolvedValue({ id: 1 });
    const { result, invalidate } = setup();
    const input = { name: "Weekly" } as never;

    await act(async () => {
      await result.current.createDefinition.mutateAsync(input);
    });

    expect(apiCall).toHaveBeenCalledWith("reports/definitions", {
      method: "POST",
      body: JSON.stringify(input),
    });
    expect(invalidatedKeys(invalidate)).toEqual([DEFINITIONS]);
    expect(toast).toHaveBeenCalledWith({ title: "Saved", description: "Report created." });
  });

  it("updateDefinition puts a partial update to the report's URL", async () => {
    apiCall.mockResolvedValue({ id: 5 });
    const { result, invalidate } = setup();

    await act(async () => {
      await result.current.updateDefinition.mutateAsync({ id: 5, data: { name: "New" } });
    });

    expect(apiCall).toHaveBeenCalledWith("reports/definitions/5", {
      method: "PUT",
      body: JSON.stringify({ name: "New" }),
    });
    expect(invalidatedKeys(invalidate)).toEqual([DEFINITIONS]);
  });

  describe("addSection", () => {
    const existing = { id: "a" };
    const added = { id: "b" } as never;

    it("reads the report, then saves it back with the section appended", async () => {
      apiCall
        .mockResolvedValueOnce({ id: 5, name: "Weekly", sections: [existing] })
        .mockResolvedValueOnce({ id: 5, name: "Weekly" });
      const { result } = setup();

      await act(async () => {
        await result.current.addSection.mutateAsync({ id: 5, section: added });
      });

      expect(apiCall).toHaveBeenNthCalledWith(1, "reports/definitions/5", { method: "GET" });
      expect(apiCall).toHaveBeenNthCalledWith(2, "reports/definitions/5", {
        method: "PUT",
        body: JSON.stringify({ sections: [existing, added] }),
      });
      expect(toast).toHaveBeenCalledWith({
        title: "Section added",
        description: "Added to “Weekly”.",
      });
    });

    it("does not save anything when the read fails", async () => {
      apiCall.mockRejectedValueOnce(new Error("gone"));
      const { result, invalidate } = setup();

      await act(async () => {
        await expect(
          result.current.addSection.mutateAsync({ id: 5, section: added }),
        ).rejects.toThrow("gone");
      });

      expect(apiCall).toHaveBeenCalledTimes(1);
      expect(invalidate).not.toHaveBeenCalled();
      expect(toast).toHaveBeenCalledWith({
        title: "Error",
        description: "gone",
        variant: "destructive",
      });
    });
  });

  it("deleteDefinition refreshes definitions and snapshots (snapshots are kept, but orphaned)", async () => {
    apiCall.mockResolvedValue(undefined);
    const { result, invalidate } = setup();

    await act(async () => {
      await result.current.deleteDefinition.mutateAsync(5);
    });

    expect(apiCall).toHaveBeenCalledWith("reports/definitions/5", { method: "DELETE" });
    expect(invalidatedKeys(invalidate)).toEqual([DEFINITIONS, SNAPSHOTS]);
  });

  describe("generateSnapshot", () => {
    it("caches the new snapshot and announces success with its name", async () => {
      const snapshot = { id: 9, name: "Weekly 2026-10-19", status: "complete" };
      apiCall.mockResolvedValue(snapshot);
      const { client, result, invalidate } = setup();

      await act(async () => {
        await result.current.generateSnapshot.mutateAsync(5);
      });

      expect(apiCall).toHaveBeenCalledWith("reports/definitions/5/generate", { method: "POST" });
      expect(invalidatedKeys(invalidate)).toEqual([DEFINITIONS, SNAPSHOTS]);
      expect(client.getQueryData(queryKeys.reports.snapshot(9))).toEqual(snapshot);
      expect(toast).toHaveBeenCalledWith({
        title: "Report generated",
        description: "Weekly 2026-10-19",
      });
    });

    it("warns when a section failed (status is not 'complete')", async () => {
      apiCall.mockResolvedValue({ id: 9, name: "x", status: "partial" });
      const { result } = setup();

      await act(async () => {
        await result.current.generateSnapshot.mutateAsync(5);
      });

      expect(toast).toHaveBeenCalledWith({
        title: "Report generated with errors",
        description: "At least one section failed. Open the snapshot for details.",
      });
    });
  });

  it.each([
    ["createDefinition", (r: ReturnType<typeof setup>["result"]) =>
      r.current.createDefinition.mutateAsync({} as never)],
    ["updateDefinition", (r: ReturnType<typeof setup>["result"]) =>
      r.current.updateDefinition.mutateAsync({ id: 1, data: {} })],
    ["deleteDefinition", (r: ReturnType<typeof setup>["result"]) =>
      r.current.deleteDefinition.mutateAsync(1)],
    ["generateSnapshot", (r: ReturnType<typeof setup>["result"]) =>
      r.current.generateSnapshot.mutateAsync(1)],
  ])("%s toasts the error and does not invalidate on failure", async (_name, run) => {
    apiCall.mockRejectedValue(new Error("denied"));
    const { result, invalidate } = setup();

    await act(async () => {
      await expect(run(result)).rejects.toThrow("denied");
    });

    expect(invalidate).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith({
      title: "Error",
      description: "denied",
      variant: "destructive",
    });
  });
});
