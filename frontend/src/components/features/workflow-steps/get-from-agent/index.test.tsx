import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/hooks/use-api";

import { GetFromAgentPlugin } from "./index";

const h = vi.hoisted(() => ({
  push: vi.fn(),
  agents: { value: [] as unknown[], loading: false, error: null as unknown },
}));

vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: h.push }) }));
vi.mock("@/hooks/queries/use-agent-sources-query", () => ({
  useAgentSourcesQuery: () => ({
    data: { sources: h.agents.value, total: h.agents.value.length },
    isLoading: h.agents.loading,
    error: h.agents.error,
    isError: h.agents.error !== null,
  }),
}));
vi.mock("@/components/features/settings/components/agent-status-panel", () => ({
  AgentStatusPanel: ({ sourceId }: { sourceId: string }) => <div>status of {sourceId}</div>,
}));

const AGENTS = [
  { source_id: "inv", transport: "http", agent_id: "inv-agent" },
  { source_id: "far", transport: "redis", agent_id: "far-agent" },
];

const Panel = GetFromAgentPlugin.ConfigPanel;

function mount(initial: Record<string, unknown> = {}) {
  const changes: Record<string, unknown>[] = [];
  function Harness() {
    const [config, setConfig] = useState(initial);
    return (
      <Panel
        nodeId="self"
        config={config}
        onPreview={() => undefined}
        onChange={(next) => {
          changes.push(next);
          setConfig(next);
        }}
      />
    );
  }
  render(<Harness />);
  return { last: () => changes[changes.length - 1] };
}

beforeEach(() => {
  h.push.mockReset();
  h.agents.value = AGENTS;
  h.agents.loading = false;
  h.agents.error = null;
});

describe("agent selection", () => {
  it("stores the chosen agent and shows its status", () => {
    const { last } = mount();
    fireEvent.change(screen.getByLabelText("agent_source_id"), { target: { value: "far" } });
    expect(last().agent_source_id).toBe("far");
    expect(screen.getByText("status of far")).toBeTruthy();
  });

  it("points at Settings when no agent exists", () => {
    h.agents.value = [];
    mount();
    fireEvent.click(screen.getByRole("button", { name: /Open Settings/ }));
    expect(h.push).toHaveBeenCalledWith("/settings/sources");
  });

  it("says the permission is missing on a 403", () => {
    h.agents.value = [];
    h.agents.error = new ApiError("Permission denied", 403);
    mount();
    expect(screen.getByText(/sources\.agent:read/)).toBeTruthy();
    expect(screen.queryByText("No agents configured yet.")).toBeNull();
  });
});

describe("handler and timeout", () => {
  it("stores the handler and the timeout", () => {
    const { last } = mount();
    fireEvent.change(screen.getByLabelText("handler"), { target: { value: "list_devices" } });
    expect(last().handler).toBe("list_devices");
    fireEvent.change(screen.getByLabelText("timeout_seconds"), { target: { value: "45" } });
    expect(last().timeout_seconds).toBe(45);
  });
});

describe("attributes", () => {
  it("adds, edits and removes rows", () => {
    const { last } = mount({ agent_source_id: "inv", handler: "list_devices" });
    fireEvent.click(screen.getByTitle("Add attribute"));
    expect(last().attributes).toEqual([{ name: "", value: "" }]);
    fireEvent.change(screen.getByLabelText("Attribute 1 name"), { target: { value: "site" } });
    fireEvent.change(screen.getByLabelText("Attribute 1 value"), { target: { value: "berlin" } });
    expect(last().attributes).toEqual([{ name: "site", value: "berlin" }]);
    fireEvent.click(screen.getByTitle("Remove attribute"));
    expect(last().attributes).toEqual([]);
  });

  it("lists configuration problems", () => {
    mount({ attributes: [{ name: "api_token", value: "x" }] });
    const list = screen.getByLabelText("Configuration problems");
    expect(list.textContent).toMatch(/secrets/);
    expect(list.textContent).toMatch(/Choose an agent/);
  });

  it("keeps the fan-out settings when other fields change", () => {
    const { last } = mount({ fan_out: { enabled: true, mode: "per_device", chunk_size: 2 } });
    fireEvent.change(screen.getByLabelText("handler"), { target: { value: "h" } });
    expect((last().fan_out as { enabled: boolean }).enabled).toBe(true);
  });
});
