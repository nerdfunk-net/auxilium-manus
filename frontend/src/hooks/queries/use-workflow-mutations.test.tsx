import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";
import { createQueryWrapper } from "@/test/query-wrapper";

import { useWorkflowMutations } from "./use-workflow-mutations";

const h = vi.hoisted(() => ({ apiCall: vi.fn() }));

vi.mock("@/hooks/use-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-api")>()),
  useApi: () => ({ apiCall: h.apiCall }),
}));

function setup() {
  const { wrapper, client } = createQueryWrapper();
  const spy = vi.spyOn(client, "invalidateQueries");
  const view = renderHook(() => useWorkflowMutations(), { wrapper });
  return { ...view, spy };
}

const LIST = { queryKey: queryKeys.workflows.list() };

beforeEach(() => {
  h.apiCall.mockReset();
});

describe("useWorkflowMutations deleteWorkflow", () => {
  it("deletes by id and refreshes the list", async () => {
    h.apiCall.mockResolvedValue(undefined);
    const { result, spy } = setup();
    await act(() => result.current.deleteWorkflow.mutateAsync(7));
    expect(h.apiCall).toHaveBeenCalledWith("workflows/7", { method: "DELETE" });
    expect(spy).toHaveBeenCalledWith(LIST);
  });

  it("refreshes the list when the workflow is already gone (404), so the row disappears", async () => {
    h.apiCall.mockRejectedValue(new ApiError("Workflow not found", 404));
    const { result, spy } = setup();
    await act(async () => {
      await expect(result.current.deleteWorkflow.mutateAsync(7)).rejects.toThrow("Workflow not found");
    });
    expect(spy).toHaveBeenCalledWith(LIST);
  });

  it.each([409, 500])("leaves the list alone on a %s (the workflow still exists)", async (status) => {
    h.apiCall.mockRejectedValue(new ApiError("nope", status));
    const { result, spy } = setup();
    await act(async () => {
      await expect(result.current.deleteWorkflow.mutateAsync(7)).rejects.toThrow("nope");
    });
    expect(spy).not.toHaveBeenCalled();
  });

  it("leaves the list alone on a plain network error", async () => {
    h.apiCall.mockRejectedValue(new Error("offline"));
    const { result, spy } = setup();
    await act(async () => {
      await expect(result.current.deleteWorkflow.mutateAsync(7)).rejects.toThrow("offline");
    });
    expect(spy).not.toHaveBeenCalled();
  });
});
