import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkflowRunConfirmMutation } from "./use-workflow-run-confirm";

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
  apiCall.mockResolvedValue({ run_id: 42, workflow_id: 5 });
});

describe("useWorkflowRunConfirmMutation", () => {
  it("posts the token and the user's choices, and maps the answer", async () => {
    const { result } = renderHook(() => useWorkflowRunConfirmMutation(), {
      wrapper,
    });

    const mapped = await result.current.mutateAsync({
      token: "signed.token",
      credentials: { cred: "lab-ssh" },
      freeIpDriver: "cisco_xe",
    });

    const [endpoint, init] = apiCall.mock.calls[0];
    expect(endpoint).toBe("ai/exec/workflow-run");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      token: "signed.token",
      credentials: { cred: "lab-ssh" },
      free_ip_driver: "cisco_xe",
    });
    expect(mapped).toEqual({ runId: 42, workflowId: 5 });
  });

  it("leaves the device type out when none was chosen", async () => {
    const { result } = renderHook(() => useWorkflowRunConfirmMutation(), {
      wrapper,
    });

    await result.current.mutateAsync({ token: "t", credentials: {} });

    expect(JSON.parse(apiCall.mock.calls[0][1].body)).toEqual({
      token: "t",
      credentials: {},
    });
  });

  it("is not retried, because a retry would start a second run", async () => {
    apiCall.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useWorkflowRunConfirmMutation(), {
      wrapper,
    });

    await expect(
      result.current.mutateAsync({ token: "t", credentials: {} }),
    ).rejects.toThrow("boom");
    expect(apiCall).toHaveBeenCalledTimes(1);
  });
});
