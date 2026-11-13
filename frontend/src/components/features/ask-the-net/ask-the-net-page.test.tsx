import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAssistantSessionStore } from "@/components/features/ai-assistant/store/assistant-session-store";
import type {
  AiStatus,
  AssistantContext,
  ConversationScope,
} from "@/components/features/ai-assistant/types/ai-assistant";

import { AskTheNetPage } from "./ask-the-net-page";
import {
  ASK_THE_NET_DATA_PERMISSIONS,
  ASK_THE_NET_SESSION_KEY,
} from "./constants/ask-the-net";

let status: { data?: AiStatus; isLoading: boolean } = {
  data: { available: true, reason: "ok" },
  isLoading: false,
};
let panelProps: {
  sessionKey: string;
  conversationScope?: ConversationScope;
  getContext?: () => AssistantContext | undefined;
} | null = null;

let permissions: string[] = ["ai_assistant:use", "sources.batfish:query"];
vi.mock("@/lib/auth-store", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: { username: "tester", permissions, roles: [] } }),
}));
vi.mock("@/hooks/queries/use-ai-status-query", () => ({
  useAiStatusQuery: () => status,
}));
// `undefined` data: not known yet (loading or failed), like a query that has not answered.
let nautobotSources: { data?: { source_id: string }[] } = {};
vi.mock("@/hooks/queries/use-nautobot-configured-sources-query", () => ({
  useNautobotConfiguredSourcesQuery: () => nautobotSources,
}));
vi.mock(
  "@/components/features/ai-assistant/components/assistant-panel",
  () => ({
    AssistantPanel: (props: NonNullable<typeof panelProps>) => {
      panelProps = props;
      return <div data-testid="assistant-panel" />;
    },
  }),
);
vi.mock(
  "@/components/features/ai-assistant/components/data-sharing-notice",
  () => ({ DataSharingNotice: () => <div data-testid="sharing-notice" /> }),
);

afterEach(cleanup);

beforeEach(() => {
  useAssistantSessionStore.getState().resetAll();
  panelProps = null;
  nautobotSources = {};
  status = { data: { available: true, reason: "ok" }, isLoading: false };
  permissions = ["ai_assistant:use", "sources.batfish:query"];
});

describe("AskTheNetPage", () => {
  it("shows the title and the chat when the assistant is available", () => {
    render(<AskTheNetPage />);

    expect(
      screen.getByRole("heading", { name: "Ask the Net" }),
    ).toBeTruthy();
    expect(screen.getByTestId("assistant-panel")).toBeTruthy();
    expect(screen.getByTestId("sharing-notice")).toBeTruthy();
  });

  it("starts the general surface, keeps its chat and can save conversations", () => {
    render(<AskTheNetPage />);

    expect(panelProps?.sessionKey).toBe(ASK_THE_NET_SESSION_KEY);
    expect(panelProps?.getContext?.()).toEqual({ surface: "general" });
    expect(panelProps?.conversationScope).toEqual({
      surface: "general",
      subjectKey: "ask-the-net",
    });
  });

  it("says the answers come from a snapshot, not from the live network", () => {
    render(<AskTheNetPage />);

    expect(screen.getByText(/snapshot/i)).toBeTruthy();
    expect(screen.getByText(/not the live network/i)).toBeTruthy();
  });

  it("puts a question from the help window into the message box without sending it", () => {
    render(<AskTheNetPage />);

    fireEvent.click(screen.getByRole("button", { name: /help/i }));
    expect(screen.getByText("Nautobot (documented inventory)")).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: /which route does/i }),
    );
    expect(screen.queryByText("What can I ask?")).toBeNull();

    const session =
      useAssistantSessionStore.getState().sessions[ASK_THE_NET_SESSION_KEY];
    expect(session?.draft).toMatch(/which route does/i);
    expect(session?.messages ?? []).toEqual([]);
  });

  it("lists the neighbour tools in the help window and lets a question be picked", () => {
    render(<AskTheNetPage />);

    fireEvent.click(screen.getByRole("button", { name: /help/i }));
    expect(screen.getByText("Neighbours (layer 2 and layer 3)")).toBeTruthy();
    for (const tool of [
      "propose_neighbor_discovery",
      "get_discovery_result",
      "get_modelled_neighbors",
      "get_neighbor_sources",
    ]) {
      expect(screen.getByText(tool)).toBeTruthy();
    }
    fireEvent.click(
      screen.getByRole("button", { name: /which routing protocols and vrfs/i }),
    );

    const session =
      useAssistantSessionStore.getState().sessions[ASK_THE_NET_SESSION_KEY];
    expect(session?.draft).toMatch(/routing protocols and vrfs/i);
    expect(session?.messages ?? []).toEqual([]);
  });

  it("shows nothing assistant-related while the status is loading", () => {
    status = { data: undefined, isLoading: true };
    render(<AskTheNetPage />);

    expect(screen.queryByTestId("assistant-panel")).toBeNull();
    expect(screen.getByText(/checking/i)).toBeTruthy();
  });

  it.each([
    ["operator_disabled", /switched off by the operator/i, null],
    ["no_permission", /do not have permission/i, null],
    ["disabled", /switched the assistant off/i, "/settings/ai-assistant"],
    ["not_configured", /not set up yet/i, "/settings/ai-assistant"],
    ["provider_not_allowed", /not allowed by the operator/i, "/settings/ai-assistant"],
  ] as const)(
    "explains why the assistant is unavailable: %s",
    (reason, message, settingsHref) => {
      status = { data: { available: false, reason }, isLoading: false };
      render(<AskTheNetPage />);

      expect(screen.getByText(message)).toBeTruthy();
      expect(screen.queryByTestId("assistant-panel")).toBeNull();
      const link = screen.queryByRole("link", { name: /assistant settings/i });
      if (settingsHref === null) {
        expect(link).toBeNull();
      } else {
        expect(link?.getAttribute("href")).toBe(settingsHref);
      }
    },
  );

  it("treats a failed status request as unavailable", () => {
    status = { data: undefined, isLoading: false };
    render(<AskTheNetPage />);

    expect(screen.queryByTestId("assistant-panel")).toBeNull();
    expect(screen.getByText(/could not check/i)).toBeTruthy();
  });

  it("offers no help button while the assistant is unavailable", () => {
    status = { data: { available: false, reason: "disabled" }, isLoading: false };
    render(<AskTheNetPage />);

    expect(screen.queryByRole("button", { name: /help/i })).toBeNull();
  });

  it("offers the chat to a user without Batfish access: the assistant is the door", () => {
    permissions = ["ai_assistant:use", "sources.nautobot:read"];
    render(<AskTheNetPage />);

    expect(screen.getByTestId("assistant-panel")).toBeTruthy();
    expect(screen.getByTestId("sharing-notice")).toBeTruthy();
    expect(screen.queryByTestId("no-data-permission")).toBeNull();
    expect(screen.queryByText(/permission to query batfish/i)).toBeNull();
  });

  it.each(ASK_THE_NET_DATA_PERMISSIONS)(
    "does not warn a user who holds %s",
    (resource, action) => {
      permissions = ["ai_assistant:use", `${resource}:${action}`];
      render(<AskTheNetPage />);

      expect(screen.getByTestId("assistant-panel")).toBeTruthy();
      expect(screen.queryByTestId("no-data-permission")).toBeNull();
    },
  );

  it("tells a user with the assistant but nothing to read what to expect", () => {
    permissions = ["ai_assistant:use"];
    render(<AskTheNetPage />);

    // Still usable (general knowledge, and tools that need no permission); not blocked.
    expect(screen.getByTestId("assistant-panel")).toBeTruthy();
    const note = screen.getByTestId("no-data-permission").textContent;
    expect(note).toMatch(/cannot look anything up/);
    // Not "general knowledge only": a DNS lookup has no permission and may be switched on.
    expect(note).toMatch(/DNS lookup/);
    expect(note).not.toMatch(/general knowledge/);
  });

  it.each([["git.files:read"], ["workflows:execute"], ["netmiko:execute"], ["reports:write"]])(
    "does not treat %s as data to read: held alone it gives no tool",
    (permission) => {
      permissions = ["ai_assistant:use", permission];
      render(<AskTheNetPage />);

      expect(screen.getByTestId("no-data-permission")).toBeTruthy();
    },
  );

  it("does not count sources.nautobot:read while no Nautobot source is configured", () => {
    permissions = ["ai_assistant:use", "sources.nautobot:read"];
    nautobotSources = { data: [] };
    render(<AskTheNetPage />);

    expect(screen.getByTestId("no-data-permission")).toBeTruthy();
  });

  it("counts sources.nautobot:read once a Nautobot source is configured", () => {
    permissions = ["ai_assistant:use", "sources.nautobot:read"];
    nautobotSources = { data: [{ source_id: "lab" }] };
    render(<AskTheNetPage />);

    expect(screen.queryByTestId("no-data-permission")).toBeNull();
  });

  it("gives sources.nautobot:read the benefit of the doubt while the sources are unknown", () => {
    permissions = ["ai_assistant:use", "sources.nautobot:read"];
    nautobotSources = {};
    render(<AskTheNetPage />);

    expect(screen.queryByTestId("no-data-permission")).toBeNull();
  });

  it("counts another permission even when no Nautobot source is configured", () => {
    permissions = ["ai_assistant:use", "sources.nautobot:read", "reports:read"];
    nautobotSources = { data: [] };
    render(<AskTheNetPage />);

    expect(screen.queryByTestId("no-data-permission")).toBeNull();
  });

  it("still explains an unavailable assistant instead of the permission note", () => {
    permissions = ["ai_assistant:use"];
    status = { data: { available: false, reason: "disabled" }, isLoading: false };
    render(<AskTheNetPage />);

    expect(screen.queryByTestId("assistant-panel")).toBeNull();
    expect(screen.queryByTestId("no-data-permission")).toBeNull();
    expect(screen.getByText(/switched the assistant off/i)).toBeTruthy();
  });

  it("tells every user who may use it where the answers come from", () => {
    for (const held of [["ai_assistant:use"], ["ai_assistant:use", "sources.batfish:query"]]) {
      cleanup();
      permissions = held;
      render(<AskTheNetPage />);

      const subtitle = screen.getByText(/ask questions about your network/i);
      expect(subtitle.textContent).toMatch(/Batfish/);
      expect(subtitle.textContent).toMatch(/Nautobot/);
      expect(subtitle.textContent).toMatch(/live read-only device commands/);
      expect(subtitle.textContent).toMatch(/write reports/);
      expect(subtitle.textContent).toMatch(/your permissions/);
      // The Batfish model is still said to be a snapshot, not the live network.
      expect(subtitle.textContent).toMatch(/not the live network/);
    }
  });
});
