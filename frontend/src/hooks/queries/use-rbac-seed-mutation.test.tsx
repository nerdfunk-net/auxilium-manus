import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query-keys";

import { useRbacSeedMutation } from "./use-rbac-seed-mutation";

const apiCall = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

describe("useRbacSeedMutation", () => {
  it("invalidates rbac keys after a seed", async () => {
    apiCall.mockResolvedValue({ success: true });
    const client = new QueryClient();
    client.setQueryData(queryKeys.rbac.roles(), [{ id: 1 }]);
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useRbacSeedMutation(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync(false);
    });

    await waitFor(() =>
      expect(client.getQueryState(queryKeys.rbac.roles())?.isInvalidated).toBe(true),
    );
  });
});
