import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BatfishEditorQuestion, BatfishQueryResult } from "../types";
import { BatfishOptionsTab } from "./batfish-options-tab";

const h = vi.hoisted(() => ({
  sourcesQuery: vi.fn(),
  networksQuery: vi.fn(),
  snapshotsQuery: vi.fn(),
  canRead: { value: true },
  canQuery: { value: false },
  sources: { value: [] as unknown[] },
  networks: { value: [] as string[] },
  snapshots: { value: [] as { name: string }[] },
}));

vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));
vi.mock("@/hooks/use-has-permission", () => ({
  useHasPermission: (resource: string, action: string) => {
    if (resource !== "sources.batfish") return false;
    if (action === "read") return h.canRead.value;
    if (action === "query") return h.canQuery.value;
    return false;
  },
}));
vi.mock("@/hooks/queries/use-batfish-sources-query", () => ({
  useBatfishSourcesQuery: (options: unknown) => {
    h.sourcesQuery(options);
    return { data: { sources: h.sources.value } };
  },
}));
vi.mock("@/hooks/queries/use-batfish-networks-query", () => ({
  useBatfishNetworksQuery: (sourceId: string) => {
    h.networksQuery(sourceId);
    return { data: { networks: h.networks.value } };
  },
}));
vi.mock("@/hooks/queries/use-batfish-snapshots-query", () => ({
  useBatfishSnapshotsQuery: (sourceId: string, network: string) => {
    h.snapshotsQuery(sourceId, network);
    return { data: { snapshots: h.snapshots.value } };
  },
}));
// The sub-panels have their own concerns; here they only mark that they were rendered.
vi.mock("./batfish-param-fields", () => ({
  ParamFieldGrid: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="param-grid">{children}</div>
  ),
}));
vi.mock("./batfish-generic-fields", () => ({
  BatfishGenericFields: () => <div data-testid="generic-fields" />,
}));
vi.mock("./batfish-include-toggles", () => ({
  BatfishIncludeToggles: () => <div data-testid="include-toggles" />,
}));
vi.mock("./batfish-result-panel", () => ({
  BatfishResultPanel: () => <div data-testid="result-panel" />,
}));

type Props = React.ComponentProps<typeof BatfishOptionsTab>;

function setup(over: Partial<Props> = {}) {
  const handlers = {
    onTargetConfigChange: vi.fn(),
    onQuestionChange: vi.fn(),
    onGenericQuestionNameChange: vi.fn(),
    onParamsChange: vi.fn(),
    onEnabledChange: vi.fn(),
    onRunQuery: vi.fn(),
  };
  const props: Props = {
    targetConfig: {},
    question: "routes",
    genericQuestionName: "",
    params: {},
    enabled: false,
    isRunningQuery: false,
    canRunQuery: true,
    result: null,
    ...handlers,
    ...over,
  };
  const view = render(<BatfishOptionsTab {...props} />);
  return { ...handlers, rerender: () => view.rerender(<BatfishOptionsTab {...props} />) };
}

const RESULT = { success: true, question: "routes", network: "n", snapshot: "s", rows: [] } as BatfishQueryResult;

beforeEach(() => {
  for (const fn of [h.sourcesQuery, h.networksQuery, h.snapshotsQuery]) fn.mockReset();
  h.canRead.value = true;
  h.canQuery.value = false;
  h.sources.value = [{ source_id: "bf1", host: "bf.local", port: 9996 }];
  h.networks.value = [];
  h.snapshots.value = [];
});

describe("BatfishOptionsTab notices", () => {
  it("warns that the preview of a non-facts question is not a workflow variable", () => {
    setup({ question: "routes" });
    expect(screen.getByText(/Preview-only/)).toBeTruthy();
  });

  it.each([
    ["extractFacts", "batfish_extract_facts"],
    ["ospfFacts", "batfish_ospf_facts"],
    ["bgpFacts", "batfish_bgp_facts"],
    ["nodeProperties", "batfish_node_properties"],
    ["interfaceProperties", "batfish_interface_properties"],
  ] as const)("names the parsed key a %s preview writes", (question, key) => {
    setup({ question });
    expect(screen.queryByText(/Preview-only/)).toBeNull();
    expect(screen.getByRole("alert").textContent).toContain(`parsed.${key}`);
  });

  it("names the custom output key instead of the default", () => {
    setup({ question: "extractFacts", params: { output_key: "my_facts" } });
    expect(screen.getByRole("alert").textContent).toContain("parsed.my_facts");
  });
});

describe("BatfishOptionsTab source", () => {
  it("lists the configured sources with host and port", () => {
    setup();
    expect(screen.getByRole("option", { name: "bf1 (bf.local:9996)" })).toBeTruthy();
  });

  it("says when no source is configured", () => {
    h.sources.value = [];
    setup();
    expect(screen.getByRole("option", { name: "No Batfish sources configured" })).toBeTruthy();
  });

  it("requests the source list only for a user who may read it", () => {
    h.canRead.value = false;
    setup();
    expect(h.sourcesQuery).toHaveBeenLastCalledWith({ enabled: false });
  });

  it("requests the source list for a user who may only run queries", () => {
    h.canRead.value = false;
    h.canQuery.value = true;
    setup();
    expect(h.sourcesQuery).toHaveBeenLastCalledWith({ enabled: true });
  });

  it("requests the source list for a user who may read it", () => {
    setup();
    expect(h.sourcesQuery).toHaveBeenLastCalledWith({ enabled: true });
  });

  it("clears the network and snapshot when the source changes", () => {
    h.sources.value = [
      { source_id: "bf1", host: "a", port: 1 },
      { source_id: "bf2", host: "b", port: 2 },
    ];
    const { onTargetConfigChange } = setup({
      targetConfig: { batfish_source_id: "bf1", network: "prod", snapshot: "s1", other: 1 },
    });
    fireEvent.change(screen.getAllByRole("combobox")[0]!, { target: { value: "bf2" } });
    expect(onTargetConfigChange).toHaveBeenCalledWith({
      other: 1,
      batfish_source_id: "bf2",
      network: "",
      snapshot: "",
    });
  });

  it("goes back to the network list after a source change", () => {
    h.sources.value = [
      { source_id: "bf1", host: "a", port: 1 },
      { source_id: "bf2", host: "b", port: 2 },
    ];
    h.networks.value = ["prod"];
    const { rerender } = setup({ targetConfig: { batfish_source_id: "bf1" } });
    fireEvent.click(screen.getByText("Enter manually"));
    expect(screen.getByLabelText("Network")).toBeTruthy();
    fireEvent.change(screen.getAllByRole("combobox")[0]!, { target: { value: "bf2" } });
    rerender();
    expect(screen.queryByLabelText("Network")).toBeNull();
  });

  it("changes the question", () => {
    const { onQuestionChange } = setup();
    fireEvent.change(screen.getByDisplayValue("Routing Table"), { target: { value: "reachability" } });
    expect(onQuestionChange).toHaveBeenCalledWith("reachability" satisfies BatfishEditorQuestion);
  });
});

describe("BatfishOptionsTab network and snapshot", () => {
  it("offers text fields until a source has networks", () => {
    setup({ targetConfig: { batfish_source_id: "bf1" } });
    expect(screen.getByLabelText("Network")).toBeTruthy();
    expect(screen.queryByText("Enter manually")).toBeNull();
    expect(screen.getByText("Pick or enter a network first.")).toBeTruthy();
  });

  it("queries networks and snapshots for the configured source and network", () => {
    setup({ targetConfig: { batfish_source_id: "bf1", network: "prod" } });
    expect(h.networksQuery).toHaveBeenLastCalledWith("bf1");
    expect(h.snapshotsQuery).toHaveBeenLastCalledWith("bf1", "prod");
  });

  it("ignores target values that are not strings", () => {
    setup({ targetConfig: { batfish_source_id: 5, network: null, snapshot: 3 } });
    expect(h.networksQuery).toHaveBeenLastCalledWith("");
    expect(h.snapshotsQuery).toHaveBeenLastCalledWith("", "");
  });

  it("shows a network picker once the source has networks, and picking one clears the snapshot", () => {
    h.networks.value = ["prod", "lab"];
    const { onTargetConfigChange } = setup({
      targetConfig: { batfish_source_id: "bf1", network: "prod", snapshot: "old" },
    });
    expect(screen.queryByLabelText("Network")).toBeNull();
    fireEvent.change(screen.getByDisplayValue("prod"), { target: { value: "lab" } });
    expect(onTargetConfigChange).toHaveBeenCalledWith({
      batfish_source_id: "bf1",
      network: "lab",
      snapshot: "",
    });
  });

  it("switches to manual entry and back", () => {
    h.networks.value = ["prod"];
    setup({ targetConfig: { batfish_source_id: "bf1", network: "prod" } });
    fireEvent.click(screen.getByText("Enter manually"));
    expect(screen.getByLabelText("Network")).toBeTruthy();
    fireEvent.click(screen.getByText("Choose from list"));
    expect(screen.queryByLabelText("Network")).toBeNull();
  });

  it("keeps the text field under the cursor when the network list arrives mid-typing", () => {
    const { rerender } = setup({ targetConfig: { batfish_source_id: "bf1", network: "pr" } });
    fireEvent.change(screen.getByLabelText("Network"), { target: { value: "pro" } });
    h.networks.value = ["prod"];
    rerender();
    expect(screen.getByLabelText("Network")).toBeTruthy();
    expect(screen.getByText("Choose from list")).toBeTruthy();
  });

  it("keeps the snapshot field when the snapshot list arrives mid-typing", () => {
    const { rerender } = setup({ targetConfig: { batfish_source_id: "bf1", network: "prod" } });
    fireEvent.change(screen.getByLabelText("Snapshot (Optional)"), { target: { value: "sn" } });
    h.snapshots.value = [{ name: "snap" }];
    rerender();
    expect(screen.getByLabelText("Snapshot (Optional)")).toBeTruthy();
  });

  it("offers a snapshot picker for a network with snapshots", () => {
    h.networks.value = ["prod"];
    h.snapshots.value = [{ name: "s2" }, { name: "s1" }];
    const { onTargetConfigChange } = setup({
      targetConfig: { batfish_source_id: "bf1", network: "prod" },
    });
    const snapshotSelect = screen
      .getAllByRole("combobox")
      .find((el) => within(el).queryByRole("option", { name: "s1" }))!;
    fireEvent.change(snapshotSelect, { target: { value: "s1" } });
    expect(onTargetConfigChange).toHaveBeenCalledWith({
      batfish_source_id: "bf1",
      network: "prod",
      snapshot: "s1",
    });
  });

  it("types a snapshot name until a network is chosen, even if snapshots exist", () => {
    h.snapshots.value = [{ name: "s1" }];
    setup({ targetConfig: { batfish_source_id: "bf1" } });
    expect(screen.getByLabelText("Snapshot (Optional)")).toBeTruthy();
    expect(screen.queryByText("Enter manually")).toBeNull();
  });

  it("does not ask for a network once one is entered", () => {
    setup({ targetConfig: { batfish_source_id: "bf1", network: "prod" } });
    expect(screen.queryByText("Pick or enter a network first.")).toBeNull();
  });

  it("types a snapshot name when there is no list", () => {
    const { onTargetConfigChange } = setup({
      targetConfig: { batfish_source_id: "bf1", network: "prod" },
    });
    fireEvent.change(screen.getByLabelText("Snapshot (Optional)"), { target: { value: "snap" } });
    expect(onTargetConfigChange).toHaveBeenCalledWith({
      batfish_source_id: "bf1",
      network: "prod",
      snapshot: "snap",
    });
  });
});

describe("BatfishOptionsTab question fields", () => {
  it("shows the parameter grid for a question that has fields", () => {
    setup({ question: "routes" });
    expect(screen.getByTestId("param-grid")).toBeTruthy();
    expect(screen.queryByTestId("generic-fields")).toBeNull();
  });

  it("shows the custom question fields for a generic question", () => {
    setup({ question: "generic" });
    expect(screen.getByTestId("generic-fields")).toBeTruthy();
  });

  it("writes the output key of a facts question", () => {
    const { onParamsChange } = setup({ question: "extractFacts", params: { nodes: "r1" } });
    fireEvent.change(screen.getByLabelText("Output Key (Optional)"), { target: { value: "facts" } });
    expect(onParamsChange).toHaveBeenCalledWith({ nodes: "r1", output_key: "facts" });
  });

  it("offers no output key for a question that does not write parsed data", () => {
    setup({ question: "routes" });
    expect(screen.queryByLabelText("Output Key (Optional)")).toBeNull();
  });

  it("shows the include toggles for OSPF and BGP facts only", () => {
    setup({ question: "ospfFacts" });
    expect(screen.getByTestId("include-toggles")).toBeTruthy();
  });

  it("shows the include toggles for BGP facts", () => {
    setup({ question: "bgpFacts" });
    expect(screen.getByTestId("include-toggles")).toBeTruthy();
  });

  it("shows no include toggles for other facts questions", () => {
    setup({ question: "extractFacts" });
    expect(screen.queryByTestId("include-toggles")).toBeNull();
  });
});

describe("BatfishOptionsTab run", () => {
  it("toggles the result", () => {
    const { onEnabledChange } = setup();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(onEnabledChange).toHaveBeenCalledWith(true);
  });

  it("hides Run Query while the result is disabled", () => {
    setup({ enabled: false });
    expect(screen.queryByRole("button", { name: /Run Query/ })).toBeNull();
  });

  it("runs the query when enabled", () => {
    const { onRunQuery } = setup({ enabled: true });
    fireEvent.click(screen.getByRole("button", { name: /Run Query/ }));
    expect(onRunQuery).toHaveBeenCalledTimes(1);
  });

  it("cannot run without a runnable target or while running", () => {
    setup({ enabled: true, canRunQuery: false });
    expect((screen.getByRole("button", { name: /Run Query/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("cannot run twice at once", () => {
    setup({ enabled: true, isRunningQuery: true });
    expect((screen.getByRole("button", { name: /Run Query/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the result when there is one", () => {
    setup({ result: RESULT });
    expect(screen.getByTestId("result-panel")).toBeTruthy();
  });

  it("shows no result panel before the first run", () => {
    setup({ result: null });
    expect(screen.queryByTestId("result-panel")).toBeNull();
  });
});
