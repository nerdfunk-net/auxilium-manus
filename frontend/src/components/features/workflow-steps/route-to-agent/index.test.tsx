import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";
import { ApiError } from "@/hooks/use-api";

import { RouteToAgentPlugin } from "./index";

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
vi.mock("@/components/features/workflow-steps/shared/attribute-path-picker", () => ({
  AttributePathPicker: ({ open, onSelect }: { open: boolean; onSelect: (p: string) => void }) =>
    open ? <button onClick={() => onSelect("nautobot.site")}>pick site</button> : null,
}));

const AGENTS = [
  { source_id: "geo", transport: "http", agent_id: "geo-agent" },
  { source_id: "far", transport: "redis", agent_id: "far-agent" },
];

const VALID = {
  agent_source_id: "geo",
  handler: "resolve_location",
  params: {},
  input_paths: ["nautobot.location.name"],
  content_inputs: [],
  destination_path: "agent.geo",
  output_keys: ["location"],
};

const NODES = [
  { id: "run-1", data: { kind: "run-command", title: "Show version" } },
  { id: "other", data: { kind: "log-message", title: "Log" } },
  { id: "self", data: { kind: "route-to-agent", title: "Agent" } },
] as unknown as NonNullable<PluginConfigPanelProps["workflowNodes"]>;

const Panel = RouteToAgentPlugin.ConfigPanel;

function mount(initial: Record<string, unknown> = {}) {
  const changes: Record<string, unknown>[] = [];
  function Harness() {
    const [config, setConfig] = useState(initial);
    return (
      <Panel
        nodeId="self"
        config={config}
        workflowNodes={NODES}
        workflowEdges={[]}
        onPreview={() => undefined}
        onChange={(next) => {
          changes.push(next);
          setConfig(next);
        }}
      />
    );
  }
  render(<Harness />);
  return { last: () => changes[changes.length - 1], count: () => changes.length };
}

beforeEach(() => {
  h.push.mockReset();
  h.agents.value = AGENTS;
  h.agents.loading = false;
  h.agents.error = null;
});

describe("agent selection", () => {
  it("lists the configured agents and stores the chosen id", () => {
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

  describe("when the agents cannot be listed", () => {
    beforeEach(() => {
      h.agents.value = [];
    });

    it("says the permission is missing on a 403, not that no agents exist", () => {
      h.agents.error = new ApiError("Permission denied", 403);
      mount();
      expect(screen.getByText(/don't have permission to list agents/i)).toBeTruthy();
      expect(screen.getByText(/sources\.agent:read/)).toBeTruthy();
      expect(screen.queryByText("No agents configured yet.")).toBeNull();
      expect(screen.queryByRole("button", { name: /Open Settings/ })).toBeNull();
    });

    it("says the list could not be loaded on any other error", () => {
      h.agents.error = new ApiError("boom", 500);
      mount();
      expect(screen.getByText(/could not be loaded/i)).toBeTruthy();
      expect(screen.queryByText("No agents configured yet.")).toBeNull();
      expect(screen.queryByText(/permission/i)).toBeNull();
    });

    it("keeps the saved agent reference visible so the step is not silently cleared", () => {
      h.agents.error = new ApiError("Permission denied", 403);
      mount({ agent_source_id: "geo" });
      expect(screen.getByText("geo")).toBeTruthy();
      expect(screen.queryByText("status of geo")).toBeNull();
    });

    it("treats a failed refetch as an error even though the previous list is still cached", () => {
      h.agents.value = AGENTS; // react-query keeps the old data when a refetch fails
      h.agents.error = new ApiError("boom", 500);
      mount({ agent_source_id: "geo" });
      expect(screen.getByText(/could not be loaded/i)).toBeTruthy();
      expect(screen.queryByText("status of geo")).toBeNull();
      expect(screen.queryByLabelText("agent_source_id")).toBeNull();
    });

    it("does not offer the Settings shortcut for an empty list unless it really is empty", () => {
      mount();
      expect(screen.getByText("No agents configured yet.")).toBeTruthy();
      expect(screen.getByRole("button", { name: /Open Settings/ })).toBeTruthy();
    });
  });

  it("keeps a reference to an agent that no longer exists visible", () => {
    mount({ agent_source_id: "gone" });
    expect(screen.getByRole("option", { name: /gone \(not found\)/ })).toBeTruthy();
  });
});

describe("text fields", () => {
  it("stores the handler, destination and timeout", () => {
    const { last } = mount();
    fireEvent.change(screen.getByLabelText("handler"), { target: { value: "resolve_location" } });
    fireEvent.change(screen.getByLabelText("destination_path"), { target: { value: "agent.geo" } });
    fireEvent.change(screen.getByLabelText("timeout_seconds"), { target: { value: "12" } });
    expect(last()).toMatchObject({
      handler: "resolve_location",
      destination_path: "agent.geo",
      timeout_seconds: 12,
    });
  });

  it("turns one-per-line input paths and output keys into lists", () => {
    const { last } = mount();
    fireEvent.change(screen.getByLabelText("input_paths"), {
      target: { value: "a.b\n c.d \n\na.b" },
    });
    expect(last().input_paths).toEqual(["a.b", "c.d"]);
    fireEvent.change(screen.getByLabelText("output_keys"), { target: { value: "x\ny" } });
    expect(last().output_keys).toEqual(["x", "y"]);
  });

  it("adds a picked attribute path to the inputs", () => {
    const { last } = mount({ input_paths: ["first.path"] });
    fireEvent.click(screen.getByTitle("Browse attributes"));
    fireEvent.click(screen.getByText("pick site"));
    expect(last().input_paths).toEqual(["first.path", "nautobot.site"]);
    expect((screen.getByLabelText("input_paths") as HTMLTextAreaElement).value).toContain(
      "nautobot.site",
    );
  });

  it("shows where the answer will be available", () => {
    mount({ destination_path: "agent.geo", output_keys: ["location", "floor"] });
    expect(screen.getByText(/agent\.geo\.location, agent\.geo\.floor/)).toBeTruthy();
  });
});

describe("params", () => {
  it("stores valid JSON objects", () => {
    const { last } = mount();
    fireEvent.change(screen.getByLabelText("params"), { target: { value: '{"strict": true}' } });
    expect(last().params).toEqual({ strict: true });
  });

  it("reports invalid JSON without touching the configuration", () => {
    const { count } = mount();
    fireEvent.change(screen.getByLabelText("params"), { target: { value: "{broken" } });
    expect(screen.getByText("Params must be valid JSON.")).toBeTruthy();
    expect(count()).toBe(0);
    fireEvent.change(screen.getByLabelText("params"), { target: { value: "[1]" } });
    expect(screen.getByText("Params must be a JSON object.")).toBeTruthy();
  });

  it("starts from the saved params", () => {
    mount({ params: { a: 1 } });
    expect((screen.getByLabelText("params") as HTMLTextAreaElement).value).toContain('"a": 1');
  });
});

describe("content inputs", () => {
  it("offers the configs and the output of Run Command steps only", () => {
    mount();
    expect(screen.getByLabelText("Running config")).toBeTruthy();
    expect(screen.getByLabelText("Startup config")).toBeTruthy();
    expect(screen.getByLabelText("Latest command output")).toBeTruthy();
    expect(screen.getByLabelText("Output of Show version")).toBeTruthy();
    expect(screen.queryByLabelText(/Output of Log/)).toBeNull();
  });

  it("toggles an entry in and out of the selection", () => {
    const { last } = mount();
    fireEvent.click(screen.getByLabelText("Running config"));
    fireEvent.click(screen.getByLabelText("Output of Show version"));
    expect(last().content_inputs).toEqual(["running_config", "command_output:run-1"]);
    fireEvent.click(screen.getByLabelText("Running config"));
    expect(last().content_inputs).toEqual(["command_output:run-1"]);
  });
});

describe("options and problems", () => {
  it("stores allow_missing_outputs", () => {
    const { last } = mount();
    fireEvent.click(screen.getByLabelText("allow_missing_outputs"));
    expect(last().allow_missing_outputs).toBe(true);
  });

  it("lists what is still missing on a new step and nothing on a valid one", () => {
    mount();
    const list = screen.getByRole("list", { name: "Configuration problems" });
    expect(list.textContent).toMatch(/Choose an agent/);
    expect(list.textContent).toMatch(/Handler is required/);
  });

  it("shows no problems for a valid configuration", () => {
    mount(VALID);
    expect(screen.queryByRole("list", { name: "Configuration problems" })).toBeNull();
  });

  it("flags a destination that could rewrite the device", () => {
    mount({ ...VALID, destination_path: "device.name" });
    expect(screen.getByRole("list", { name: "Configuration problems" }).textContent).toMatch(
      /may not start with "device"/,
    );
  });
});

describe("help", () => {
  it("is provided", () => {
    expect(RouteToAgentPlugin.HelpPanel).toBeDefined();
  });
});
