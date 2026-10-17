import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query-keys";

import { useWorkflowNotesMutation } from "./use-workflow-notes-mutation";

const apiCall = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));

describe("useWorkflowNotesMutation", () => {
  it("invalidates the workflow detail without refetching it", async () => {
    apiCall.mockResolvedValue({ notes: "saved" });
    const client = new QueryClient();
    const queryFn = vi.fn().mockResolvedValue({ id: 7, notes: "old" });
    await client.fetchQuery({ queryKey: queryKeys.workflows.detail(7), queryFn });
    queryFn.mockClear();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useWorkflowNotesMutation(7), { wrapper });

    await act(async () => {
      await result.current.mutateAsync("saved");
    });

    await waitFor(() =>
      expect(client.getQueryState(queryKeys.workflows.detail(7))?.isInvalidated).toBe(true),
    );
    // The open canvas is rehydrated from this query: it must not refetch under the editor.
    expect(queryFn).not.toHaveBeenCalled();
  });
});
