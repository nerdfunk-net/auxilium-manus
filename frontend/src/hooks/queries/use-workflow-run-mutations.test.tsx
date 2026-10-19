import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query-keys";
import { createQueryWrapper } from "@/test/query-wrapper";

import {
  useApproveAllMutation,
  useApproveBatchMutation,
  useBulkDeleteRunsMutation,
  useCancelRunMutation,
  useDeleteRunMutation,
  useTriggerRunMutation,
} from "./use-workflow-run-mutations";

const apiCall = vi.fn();
const toast = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast }) }));

beforeEach(() => {
  apiCall.mockReset();
  toast.mockReset();
});

function setup<T>(useHook: () => T) {
  const { client, wrapper } = createQueryWrapper();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const remove = vi.spyOn(client, "removeQueries");
  const { result } = renderHook(useHook, { wrapper });
  return { result, invalidate, remove };
}

const invalidatedKeys = (spy: { mock: { calls: unknown[][] } }) =>
  spy.mock.calls.map(([filters]) => (filters as { queryKey: unknown }).queryKey);

const LIST_KEY = queryKeys.workflowRuns.listPrefix(7);

describe("useTriggerRunMutation", () => {
  const body = { device_ids: ["d1"], trigger_type: "manual" as const };

  it("posts the body as JSON to the workflow's runs endpoint", async () => {
    apiCall.mockResolvedValue({ id: 1 });
    const { result } = setup(() => useTriggerRunMutation(7));

    await act(async () => {
      await result.current.mutateAsync(body);
    });

    expect(apiCall).toHaveBeenCalledWith("workflows/7/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  });

  it("lets the variables override the workflow id and keeps it out of the body", async () => {
    apiCall.mockResolvedValue({ id: 1 });
    const { result, invalidate } = setup(() => useTriggerRunMutation(7));

    await act(async () => {
      await result.current.mutateAsync({ ...body, workflowId: 9 });
    });

    const [endpoint, init] = apiCall.mock.calls[0];
    expect(endpoint).toBe("workflows/9/runs");
    expect(JSON.parse(init.body)).toEqual(body);
    expect(invalidatedKeys(invalidate)).toEqual([queryKeys.workflowRuns.listPrefix(9)]);
  });

  it("invalidates the run list and toasts on success", async () => {
    apiCall.mockResolvedValue({ id: 1 });
    const { result, invalidate } = setup(() => useTriggerRunMutation(7));

    await act(async () => {
      await result.current.mutateAsync(body);
    });

    expect(invalidatedKeys(invalidate)).toEqual([LIST_KEY]);
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: "Run queued" }));
  });

  it("refuses to run an unsaved workflow without calling the API", async () => {
    const { result } = setup(() => useTriggerRunMutation(null));

    await act(async () => {
      await expect(result.current.mutateAsync(body)).rejects.toThrow(
        "Workflow must be saved before running",
      );
    });

    expect(apiCall).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith({
      title: "Failed to start run",
      description: "Workflow must be saved before running",
      variant: "destructive",
    });
  });

  it("surfaces an API error as a destructive toast and does not invalidate", async () => {
    apiCall.mockRejectedValue(new Error("boom"));
    const { result, invalidate } = setup(() => useTriggerRunMutation(7));

    await act(async () => {
      await expect(result.current.mutateAsync(body)).rejects.toThrow("boom");
    });

    expect(invalidate).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ description: "boom", variant: "destructive" }),
    );
  });
});

describe.each([
  {
    name: "useCancelRunMutation",
    useHook: useCancelRunMutation,
    endpoint: "runs/3/cancel",
    successTitle: "Run cancelled",
    failureTitle: "Failed to cancel run",
  },
  {
    name: "useApproveBatchMutation",
    useHook: useApproveBatchMutation,
    endpoint: "runs/3/approve-batch",
    successTitle: "Batch released",
    failureTitle: "Failed to release batch",
  },
  {
    name: "useApproveAllMutation",
    useHook: useApproveAllMutation,
    endpoint: "runs/3/approve-all",
    successTitle: "Running all remaining batches",
    failureTitle: "Failed to run remaining batches",
  },
])("$name", ({ useHook, endpoint, successTitle, failureTitle }) => {
  it("posts to the run endpoint", async () => {
    apiCall.mockResolvedValue({ id: 3 });
    const { result } = setup(() => useHook(7));

    await act(async () => {
      await result.current.mutateAsync(3);
    });

    expect(apiCall).toHaveBeenCalledWith(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
  });

  it("invalidates the run list and the run detail, then toasts", async () => {
    apiCall.mockResolvedValue({ id: 3 });
    const { result, invalidate } = setup(() => useHook(7));

    await act(async () => {
      await result.current.mutateAsync(3);
    });

    expect(invalidatedKeys(invalidate)).toEqual([LIST_KEY, queryKeys.workflowRuns.detail(3)]);
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: successTitle }));
  });

  it("skips the list invalidation when there is no workflow id", async () => {
    apiCall.mockResolvedValue({ id: 3 });
    const { result, invalidate } = setup(() => useHook(null));

    await act(async () => {
      await result.current.mutateAsync(3);
    });

    expect(invalidatedKeys(invalidate)).toEqual([queryKeys.workflowRuns.detail(3)]);
  });

  it("toasts the error message on failure", async () => {
    apiCall.mockRejectedValue(new Error("conflict"));
    const { result } = setup(() => useHook(7));

    await act(async () => {
      await expect(result.current.mutateAsync(3)).rejects.toThrow("conflict");
    });

    expect(toast).toHaveBeenCalledWith({
      title: failureTitle,
      description: "conflict",
      variant: "destructive",
    });
  });
});

describe("approve mutations refresh a stale run after a failure", () => {
  it.each([
    ["useApproveBatchMutation", useApproveBatchMutation],
    ["useApproveAllMutation", useApproveAllMutation],
  ])("%s invalidates the run detail on error", async (_name, useHook) => {
    apiCall.mockRejectedValue(new Error("409"));
    const { result, invalidate } = setup(() => useHook(7));

    await act(async () => {
      await expect(result.current.mutateAsync(3)).rejects.toThrow();
    });

    expect(invalidatedKeys(invalidate)).toEqual([queryKeys.workflowRuns.detail(3)]);
  });

  it("useCancelRunMutation does not invalidate on error", async () => {
    apiCall.mockRejectedValue(new Error("nope"));
    const { result, invalidate } = setup(() => useCancelRunMutation(7));

    await act(async () => {
      await expect(result.current.mutateAsync(3)).rejects.toThrow();
    });

    expect(invalidate).not.toHaveBeenCalled();
  });
});

describe("useDeleteRunMutation", () => {
  it("deletes the run, refreshes the list and drops the cached detail", async () => {
    apiCall.mockResolvedValue(undefined);
    const { result, invalidate, remove } = setup(() => useDeleteRunMutation(7));

    await act(async () => {
      await result.current.mutateAsync(3);
    });

    expect(apiCall).toHaveBeenCalledWith("runs/3", { method: "DELETE" });
    expect(invalidatedKeys(invalidate)).toEqual([LIST_KEY]);
    expect(remove).toHaveBeenCalledWith({ queryKey: queryKeys.workflowRuns.detail(3) });
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: "Run deleted" }));
  });

  it("keeps the cached detail when the delete fails", async () => {
    apiCall.mockRejectedValue(new Error("forbidden"));
    const { result, remove } = setup(() => useDeleteRunMutation(7));

    await act(async () => {
      await expect(result.current.mutateAsync(3)).rejects.toThrow("forbidden");
    });

    expect(remove).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Failed to delete run", variant: "destructive" }),
    );
  });
});

describe("useBulkDeleteRunsMutation", () => {
  it("reports a per-run result and never rejects for partial failures", async () => {
    apiCall.mockImplementation(async (endpoint: string) => {
      if (endpoint === "runs/2") throw new Error("not yours");
      if (endpoint === "runs/3") throw "plain string";
    });
    const { result } = setup(() => useBulkDeleteRunsMutation(7));

    let results: unknown;
    await act(async () => {
      results = await result.current.mutateAsync([1, 2, 3]);
    });

    expect(results).toEqual([
      { runId: 1, success: true },
      { runId: 2, success: false, error: "not yours" },
      { runId: 3, success: false, error: "Unexpected error" },
    ]);
  });

  it("drops cached details only for the runs that were deleted", async () => {
    apiCall.mockImplementation(async (endpoint: string) => {
      if (endpoint === "runs/2") throw new Error("nope");
    });
    const { result, remove, invalidate } = setup(() => useBulkDeleteRunsMutation(7));

    await act(async () => {
      await result.current.mutateAsync([1, 2]);
    });

    expect(remove.mock.calls.map(([f]) => (f as { queryKey: unknown }).queryKey)).toEqual([
      queryKeys.workflowRuns.detail(1),
    ]);
    expect(invalidatedKeys(invalidate)).toEqual([LIST_KEY]);
  });

  it("toasts success, partial failure and the singular form", async () => {
    apiCall.mockResolvedValue(undefined);
    const { result } = setup(() => useBulkDeleteRunsMutation(7));

    await act(async () => {
      await result.current.mutateAsync([1, 2]);
    });
    expect(toast).toHaveBeenLastCalledWith({
      title: "Runs deleted",
      description: "2 of 2 runs deleted.",
      variant: undefined,
    });

    await act(async () => {
      await result.current.mutateAsync([1]);
    });
    expect(toast).toHaveBeenLastCalledWith(
      expect.objectContaining({ description: "1 of 1 run deleted." }),
    );

    apiCall.mockRejectedValueOnce(new Error("x"));
    await act(async () => {
      await result.current.mutateAsync([1, 2, 3]);
    });
    expect(toast).toHaveBeenLastCalledWith({
      title: "Some runs could not be deleted",
      description: "2 of 3 runs deleted, 1 failed.",
      variant: "destructive",
    });
  });

  it("handles an empty selection without calling the API", async () => {
    const { result } = setup(() => useBulkDeleteRunsMutation(7));

    await act(async () => {
      await result.current.mutateAsync([]);
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiCall).not.toHaveBeenCalled();
  });
});
