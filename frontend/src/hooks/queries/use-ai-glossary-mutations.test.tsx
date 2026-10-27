import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query-keys";
import { createQueryWrapper } from "@/test/query-wrapper";

import { useAiGlossaryMutations } from "./use-ai-glossary-mutations";

const apiCall = vi.fn();
const toast = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast }) }));

const DATA = {
  kind: "inventory_filter" as const,
  term: "core",
  aliases: ["backbone"],
  note: null,
  source_id: "nb",
  filter: {
    logic: "AND" as const,
    conditions: [{ field: "role", operator: "equals", value: "Network" }],
    groups: [],
  },
};

function setup() {
  const { client, wrapper } = createQueryWrapper();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const { result } = renderHook(() => useAiGlossaryMutations(), { wrapper });
  return { result, invalidate };
}

beforeEach(() => {
  apiCall.mockReset();
  toast.mockReset();
});

describe("useAiGlossaryMutations", () => {
  it("creates a term and invalidates the glossary", async () => {
    apiCall.mockResolvedValue({ id: 1, warnings: [] });
    const { result, invalidate } = setup();

    await act(async () => {
      await result.current.createTerm.mutateAsync(DATA);
    });

    expect(apiCall).toHaveBeenCalledWith("ai/glossary", {
      method: "POST",
      body: JSON.stringify(DATA),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: queryKeys.ai.glossary(),
    });
  });

  it("shows the warnings of an unverified value in the toast", async () => {
    apiCall.mockResolvedValue({
      id: 1,
      warnings: ["role could not be verified"],
    });
    const { result } = setup();

    await act(async () => {
      await result.current.updateTerm.mutateAsync({ id: 1, data: DATA });
    });

    expect(apiCall).toHaveBeenCalledWith("ai/glossary/1", {
      method: "PUT",
      body: JSON.stringify(DATA),
    });
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ description: "role could not be verified" }),
    );
  });

  it("deletes and reports a failure as a destructive toast", async () => {
    apiCall
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("gone"));
    const { result } = setup();

    await act(async () => {
      await result.current.deleteTerm.mutateAsync(3);
    });
    expect(apiCall).toHaveBeenCalledWith("ai/glossary/3", { method: "DELETE" });

    await act(async () => {
      await result.current.deleteTerm.mutateAsync(4).catch(() => undefined);
    });
    expect(toast).toHaveBeenLastCalledWith(
      expect.objectContaining({ description: "gone", variant: "destructive" }),
    );
  });
});
