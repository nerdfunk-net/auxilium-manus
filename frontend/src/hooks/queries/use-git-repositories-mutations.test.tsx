import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query-keys";
import { createQueryWrapper } from "@/test/query-wrapper";

import {
  useGitRepositoriesMutations,
  type GitConnectionTestPayload,
  type GitRepositoryUpsertPayload,
} from "./use-git-repositories-mutations";

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
  const { result } = renderHook(() => useGitRepositoriesMutations(), { wrapper });
  return { result, invalidate };
}

const upsert: GitRepositoryUpsertPayload = {
  name: "configs",
  category: "device_configs",
  url: "https://git.example.com/a.git",
  branch: "main",
  auth_type: "token",
  verify_ssl: true,
};

const invalidatedKeys = (spy: { mock: { calls: unknown[][] } }) =>
  spy.mock.calls.map(([filters]) => (filters as { queryKey: unknown }).queryKey);

const ALL = queryKeys.gitRepositories.all;

describe("useGitRepositoriesMutations", () => {
  describe.each([
    {
      name: "createRepository",
      run: (r: ReturnType<typeof setup>["result"]) => r.current.createRepository.mutateAsync(upsert),
      endpoint: "git-repositories",
      init: { method: "POST", body: JSON.stringify(upsert) },
      toast: { title: "Saved", description: "Git repository configured." },
    },
    {
      name: "updateRepository",
      run: (r: ReturnType<typeof setup>["result"]) =>
        r.current.updateRepository.mutateAsync({ id: 4, data: { branch: "dev" } }),
      endpoint: "git-repositories/4",
      init: { method: "PUT", body: JSON.stringify({ branch: "dev" }) },
      toast: { title: "Saved", description: "Git repository updated." },
    },
    {
      name: "deleteRepository",
      run: (r: ReturnType<typeof setup>["result"]) => r.current.deleteRepository.mutateAsync(4),
      endpoint: "git-repositories/4",
      init: { method: "DELETE" },
      toast: { title: "Removed", description: "Git repository deleted." },
    },
    {
      name: "syncRepository",
      run: (r: ReturnType<typeof setup>["result"]) => r.current.syncRepository.mutateAsync(4),
      endpoint: "git/4/sync",
      init: { method: "POST" },
      toast: { title: "Synced", description: "Repository cloned or pulled." },
    },
    {
      name: "removeAndSyncRepository",
      run: (r: ReturnType<typeof setup>["result"]) =>
        r.current.removeAndSyncRepository.mutateAsync(4),
      endpoint: "git/4/remove-and-sync",
      init: { method: "POST" },
      toast: { title: "Re-cloned", description: "Local copy removed and cloned fresh." },
    },
  ])("$name", ({ run, endpoint, init, toast: expectedToast }) => {
    it("calls the endpoint, invalidates the repository list and toasts", async () => {
      apiCall.mockResolvedValue({});
      const { result, invalidate } = setup();

      await act(async () => {
        await run(result);
      });

      expect(apiCall).toHaveBeenCalledWith(endpoint, init);
      expect(invalidatedKeys(invalidate)).toEqual([ALL]);
      expect(toast).toHaveBeenCalledWith(expectedToast);
    });

    it("toasts the error and leaves the cache alone on failure", async () => {
      apiCall.mockRejectedValue(new Error("boom"));
      const { result, invalidate } = setup();

      await act(async () => {
        await expect(run(result)).rejects.toThrow("boom");
      });

      expect(invalidate).not.toHaveBeenCalled();
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({ description: "boom", variant: "destructive" }),
      );
    });
  });

  describe("testConnection", () => {
    const payload: GitConnectionTestPayload = {
      url: "https://git.example.com/a.git",
      branch: "main",
      auth_type: "token",
      verify_ssl: false,
    };

    it("posts the payload and never invalidates the repository list", async () => {
      apiCall.mockResolvedValue({ success: true, message: "ok" });
      const { result, invalidate } = setup();

      await act(async () => {
        await result.current.testConnection.mutateAsync(payload);
      });

      expect(apiCall).toHaveBeenCalledWith("git-repositories/test-connection", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      expect(invalidate).not.toHaveBeenCalled();
      expect(toast).toHaveBeenCalledWith({
        title: "Connection successful",
        description: "ok",
        variant: "default",
      });
    });

    it("shows a failed test (HTTP 200, success=false) as a destructive toast", async () => {
      apiCall.mockResolvedValue({ success: false, message: "bad credentials" });
      const { result } = setup();

      await act(async () => {
        await result.current.testConnection.mutateAsync(payload);
      });

      expect(toast).toHaveBeenCalledWith({
        title: "Connection failed",
        description: "bad credentials",
        variant: "destructive",
      });
    });

    it("shows a request error as a destructive toast", async () => {
      apiCall.mockRejectedValue(new Error("timeout"));
      const { result } = setup();

      await act(async () => {
        await expect(result.current.testConnection.mutateAsync(payload)).rejects.toThrow();
      });

      expect(toast).toHaveBeenCalledWith({
        title: "Connection failed",
        description: "timeout",
        variant: "destructive",
      });
    });
  });

  it("uses a distinct error title for sync failures", async () => {
    apiCall.mockRejectedValue(new Error("merge conflict"));
    const { result } = setup();

    await act(async () => {
      await expect(result.current.syncRepository.mutateAsync(4)).rejects.toThrow();
    });

    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: "Sync failed" }));
  });
});
