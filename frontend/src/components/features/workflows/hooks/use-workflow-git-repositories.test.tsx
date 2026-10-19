import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/lib/auth-store";
import { createQueryWrapper } from "@/test/query-wrapper";

import { useWorkflowGitRepositories } from "./use-workflow-git-repositories";

const h = vi.hoisted(() => ({ apiCall: vi.fn() }));
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall: h.apiCall }) }));

const userWith = (...permissions: string[]) =>
  useAuthStore.setState({ user: { username: "me", permissions, roles: [] } as never });

beforeEach(() => {
  h.apiCall.mockReset().mockResolvedValue({ repositories: [{ id: 1 }] });
  useAuthStore.setState({ user: null });
});

describe("useWorkflowGitRepositories", () => {
  it("lists the active workflow repositories for a user who may read them", async () => {
    userWith("git.repositories:read");
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useWorkflowGitRepositories(), { wrapper });
    await waitFor(() => expect(result.current.hasConfiguredGitRepository).toBe(true));
    expect(h.apiCall).toHaveBeenCalledWith(
      "git-repositories?active_only=true&category=workflows",
      { method: "GET" },
    );
  });

  it("makes no request for a user without git.repositories:read", () => {
    userWith("workflows:read");
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useWorkflowGitRepositories(), { wrapper });
    expect(h.apiCall).not.toHaveBeenCalled();
    expect(result.current.hasConfiguredGitRepository).toBe(false);
  });

  it("makes no request before the user is known", () => {
    const { wrapper } = createQueryWrapper();
    renderHook(() => useWorkflowGitRepositories(), { wrapper });
    expect(h.apiCall).not.toHaveBeenCalled();
  });

  it("reports no repository when the list is empty", async () => {
    userWith("git.repositories:read");
    h.apiCall.mockResolvedValue({ repositories: [] });
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useWorkflowGitRepositories(), { wrapper });
    await waitFor(() => expect(h.apiCall).toHaveBeenCalled());
    expect(result.current.hasConfiguredGitRepository).toBe(false);
  });
});
