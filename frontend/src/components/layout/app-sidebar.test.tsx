import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthUser } from "@/lib/auth";

import { AppSidebar } from "./app-sidebar";

let user: Partial<AuthUser> | null = null;

vi.mock("next/navigation", () => ({
  usePathname: () => "/ask-the-net",
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("next/dynamic", () => ({ default: () => () => null }));
vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-query")>()),
  useQueryClient: () => ({ clear: vi.fn() }),
}));
vi.mock("@/lib/auth-store", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user, logout: vi.fn() }),
}));

function withPermissions(...permissions: string[]) {
  user = { username: "tester", permissions, roles: [] };
}

afterEach(() => {
  cleanup();
  user = null;
});

describe("AppSidebar: Ask the Net", () => {
  it.each([
    [["ai_assistant:use"]],
    [["ai_assistant:use", "sources.batfish:query"]],
    [["ai_assistant:use", "sources.nautobot:read", "reports:read"]],
  ])(
    "lists Ask the Net for a user who may use the assistant: %j",
    (permissions) => {
      withPermissions(...permissions);
      render(<AppSidebar />);

      const link = screen.getByRole("link", { name: "Ask the Net" });
      expect(link.getAttribute("href")).toBe("/ask-the-net");
      expect(link.getAttribute("aria-current")).toBe("page");
    },
  );

  it.each([
    [["sources.batfish:query"]],
    [["sources.nautobot:read", "reports:read"]],
    [["sources.batfish:read", "workflows:read"]],
    [[]],
  ])(
    "hides it without ai_assistant:use, whatever else the user holds: %j",
    (permissions) => {
      withPermissions(...permissions);
      render(<AppSidebar />);

      expect(screen.queryByRole("link", { name: "Ask the Net" })).toBeNull();
    },
  );
});
