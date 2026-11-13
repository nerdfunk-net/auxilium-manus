import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sources = {
  data: [
    { id: "report_data", label: "Report database" },
    { id: "nautobot", label: "Nautobot" },
  ] as { id: string; label: string }[] | undefined,
};
vi.mock("@/hooks/queries/use-report-sources-query", () => ({
  useReportSourcesQuery: () => sources,
}));
vi.mock(
  "@/components/features/ai-assistant/hooks/use-ai-assistant-available",
  () => ({ useAiAssistantAvailable: () => true }),
);

const openKeys: string[] = [];
vi.mock(
  "@/components/features/ai-assistant/hooks/use-assistant-session-open",
  () => ({
    useAssistantSessionOpen: (key: string) => {
      openKeys.push(key);
      return { open: true, setOpen: vi.fn(), toggle: vi.fn() };
    },
  }),
);

// The panel shows which source and conversation it was given.
vi.mock(
  "@/components/features/ai-assistant/components/assistant-panel",
  () => ({
    AssistantPanel: ({
      sessionKey,
      conversationScope,
      getContext,
    }: {
      sessionKey: string;
      conversationScope: { subjectKey: string };
      getContext: () => { surface: string; source_id?: string };
    }) => (
      <div data-testid="panel">
        {sessionKey}|{conversationScope.subjectKey}|{getContext().source_id}
      </div>
    ),
  }),
);
vi.mock(
  "@/components/features/ai-assistant/components/data-sharing-notice",
  () => ({ DataSharingNotice: () => null }),
);
vi.mock(
  "@/components/features/ai-assistant/components/resizable-assistant-aside",
  () => ({
    ResizableAssistantAside: ({ children }: { children: React.ReactNode }) => (
      <aside>{children}</aside>
    ),
  }),
);

// Explore stands in for the builder: a button picks a source like the dropdown does.
vi.mock("./explore-tab", () => ({
  ExploreTab: ({
    onSourceChange,
  }: {
    onSourceChange?: (id: string) => void;
  }) => (
    <div>
      <button onClick={() => onSourceChange?.("nautobot")}>pick nautobot</button>
      <button onClick={() => onSourceChange?.("report_data")}>pick database</button>
      <button onClick={() => onSourceChange?.("gone")}>pick unknown</button>
    </div>
  ),
}));
vi.mock("./reports-tab", () => ({ ReportsTab: () => null }));
vi.mock("./snapshots-tab", () => ({ SnapshotsTab: () => null }));

import { ReportsPage } from "./reports-page";

beforeEach(() => {
  openKeys.length = 0;
  sources.data = [
    { id: "report_data", label: "Report database" },
    { id: "nautobot", label: "Nautobot" },
  ];
});
afterEach(cleanup);

const panel = () => screen.getByTestId("panel").textContent;

describe("ReportsPage: the assistant follows the source picker", () => {
  it("starts on the first source", () => {
    render(<ReportsPage />);

    expect(panel()).toBe("reports:report_data|report_data|report_data");
  });

  it("switches the assistant to the source the user picks, and back", () => {
    render(<ReportsPage />);

    fireEvent.click(screen.getByText("pick nautobot"));
    expect(panel()).toBe("reports:nautobot|nautobot|nautobot");

    fireEvent.click(screen.getByText("pick database"));
    expect(panel()).toBe("reports:report_data|report_data|report_data");
  });

  it("ignores a source the server does not list", () => {
    render(<ReportsPage />);

    fireEvent.click(screen.getByText("pick unknown"));

    expect(panel()).toBe("reports:report_data|report_data|report_data");
  });

  it("keeps one open/closed state for the panel, so a switch does not close it", () => {
    render(<ReportsPage />);
    fireEvent.click(screen.getByText("pick nautobot"));

    expect(new Set(openKeys)).toEqual(new Set(["reports"]));
    expect(screen.getByTestId("panel")).toBeTruthy();
  });

  it("falls back to the report database before the sources are known", () => {
    sources.data = undefined;

    render(<ReportsPage />);

    expect(panel()).toBe("reports:report_data|report_data|report_data");
  });
});
