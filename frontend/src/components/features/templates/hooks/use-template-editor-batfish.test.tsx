import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryWrapper } from "@/test/query-wrapper";

import type { BatfishQueryConfig } from "../types";
import {
  DEFAULT_OUTPUT_KEY,
  isFactsQuestion,
  pickFactsPayload,
  useTemplateEditorBatfish,
} from "./use-template-editor-batfish";

const apiCall = vi.fn();
const toast = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast }) }));

const setBatfishResult = vi.fn();
const setParsedNamespaceEntry = vi.fn();
const clearParsedNamespaceEntry = vi.fn();

beforeEach(() => {
  for (const spy of [apiCall, toast, setBatfishResult, setParsedNamespaceEntry, clearParsedNamespaceEntry]) {
    spy.mockReset();
  }
});

function setup() {
  const { wrapper } = createQueryWrapper();
  return renderHook(
    () => useTemplateEditorBatfish({ setBatfishResult, setParsedNamespaceEntry, clearParsedNamespaceEntry }),
    { wrapper },
  );
}

type Hook = ReturnType<typeof setup>["result"];

const target = { batfish_source_id: "bf1", network: " net ", snapshot: " snap " };

function configure(result: Hook, question: Parameters<Hook["current"]["setQuestion"]>[0], params = {}) {
  act(() => {
    result.current.setEnabled(true);
    result.current.setTargetConfig(target);
    result.current.setQuestion(question);
    result.current.setParams(params);
  });
}

async function run(result: Hook) {
  await act(async () => {
    result.current.handleRunQuery();
  });
}

const lastRequest = () => {
  const [endpoint, init] = apiCall.mock.calls.at(-1)!;
  return { endpoint: endpoint as string, body: JSON.parse(init.body) as Record<string, unknown> };
};

describe("isFactsQuestion", () => {
  it.each(["extractFacts", "ospfFacts", "bgpFacts", "nodeProperties", "interfaceProperties"] as const)(
    "%s is a facts question",
    (question) => expect(isFactsQuestion(question)).toBe(true),
  );

  it.each(["routes", "reachability", "testFilters", "generic"] as const)(
    "%s is a preview-only question",
    (question) => expect(isFactsQuestion(question)).toBe(false),
  );
});

describe("pickFactsPayload", () => {
  it.each([[null], [undefined], [{}]])("reports no facts for %j", (input) => {
    expect(pickFactsPayload(input)).toEqual({
      parsed: null,
      error: "no facts found for this filter in this Batfish snapshot",
      nodeCount: 0,
    });
  });

  it("unwraps a single node to the per-device shape", () => {
    expect(pickFactsPayload({ sw1: { asn: 65000 } })).toEqual({
      parsed: { asn: 65000 },
      error: null,
      nodeCount: 1,
    });
  });

  it("keeps the full dict when several nodes matched", () => {
    const facts = { sw1: { a: 1 }, sw2: { a: 2 } };
    expect(pickFactsPayload(facts)).toEqual({ parsed: facts, error: null, nodeCount: 2 });
  });
});

describe("canRunQuery", () => {
  it("needs a source and a network", () => {
    const { result } = setup();
    expect(result.current.canRunQuery).toBe(false);
    act(() => result.current.setTargetConfig({ batfish_source_id: "bf1" }));
    expect(result.current.canRunQuery).toBe(false);
    act(() => result.current.setTargetConfig({ batfish_source_id: "bf1", network: "   " }));
    expect(result.current.canRunQuery).toBe(false);
    act(() => result.current.setTargetConfig(target));
    expect(result.current.canRunQuery).toBe(true);
  });

  it.each([
    ["generic", {}, false],
    ["reachability", {}, false],
    ["reachability", { start_node: "sw1" }, true],
    ["testFilters", { node: "sw1", filter_name: "acl" }, false],
    ["testFilters", { node: "sw1", filter_name: "acl", dst_ips: "10.0.0.1" }, true],
    ["ospfFacts", { include_process: false, include_areas: false, include_interfaces: false, include_edges: false }, false],
    ["ospfFacts", { include_process: false, include_areas: false, include_interfaces: false }, true],
    ["bgpFacts", { include_process: false, include_peers: false, include_sessions: false, include_edges: false }, false],
    ["bgpFacts", {}, true],
    ["routes", {}, true],
    ["extractFacts", {}, true],
  ] as const)("%s with %j -> %s", (question, params, expected) => {
    const { result } = setup();
    configure(result, question, params);
    expect(result.current.canRunQuery).toBe(expected);
  });

  it("is ready for a generic question once it has a name", () => {
    const { result } = setup();
    configure(result, "generic");
    act(() => result.current.setGenericQuestionName("  myQuestion "));
    expect(result.current.canRunQuery).toBe(true);
  });
});

describe("running a query", () => {
  it("does not call the API without a source and network, and reports why", async () => {
    const { result } = setup();
    await run(result);
    expect(apiCall).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith({
      title: "Batfish query failed",
      description: "Select a Batfish source and network first",
      variant: "destructive",
    });
  });

  it.each([
    ["routes", "routes"],
    ["reachability", "reachability"],
    ["testFilters", "test-filters"],
    ["generic", "generic"],
    ["extractFacts", "extract-facts"],
    ["ospfFacts", "ospf-facts"],
    ["bgpFacts", "bgp-facts"],
    ["nodeProperties", "node-properties"],
    ["interfaceProperties", "interface-properties"],
  ] as const)("posts %s to the %s endpoint with the trimmed network and snapshot", async (question, endpoint) => {
    apiCall.mockResolvedValue({ success: true, rows: [] });
    const { result } = setup();
    configure(result, question, { start_node: "sw1", node: "sw1", filter_name: "f", dst_ips: "1.1.1.1" });
    if (question === "generic") act(() => result.current.setGenericQuestionName("q"));

    await run(result);

    const request = lastRequest();
    expect(request.endpoint).toBe(`sources/batfish/bf1/query/${endpoint}`);
    expect(request.body).toMatchObject({ network: "net", snapshot: "snap" });
  });

  it("omits the snapshot when blank", async () => {
    apiCall.mockResolvedValue({});
    const { result } = setup();
    configure(result, "routes");
    act(() => result.current.setTargetConfig({ ...target, snapshot: "  " }));
    await run(result);
    expect(lastRequest().body).not.toHaveProperty("snapshot");
  });

  it("sends only filled-in route filters", async () => {
    apiCall.mockResolvedValue({});
    const { result } = setup();
    configure(result, "routes", { nodes: "sw1", protocols: "", vrfs: "default" });
    await run(result);
    expect(lastRequest().body).toEqual({ network: "net", snapshot: "snap", nodes: "sw1", vrfs: "default" });
  });

  it("sends reachability flags as booleans and numeric limits as numbers", async () => {
    apiCall.mockResolvedValue({});
    const { result } = setup();
    configure(result, "reachability", {
      start_node: "sw1",
      max_traces: 5,
      invert_search: true,
      applications: ["ssh"],
    });
    await run(result);
    expect(lastRequest().body).toMatchObject({
      start_node: "sw1",
      max_traces: 5,
      invert_search: true,
      ignore_filters: false,
      applications: ["ssh"],
    });
  });

  it("sends a generic question's trimmed name and raw params", async () => {
    apiCall.mockResolvedValue({});
    const { result } = setup();
    configure(result, "generic", { foo: 1 });
    act(() => result.current.setGenericQuestionName("  bgpEdges "));
    await run(result);
    expect(lastRequest().body).toMatchObject({ question: "bgpEdges", params: { foo: 1 } });
  });

  it("defaults OSPF/BGP include flags to true", async () => {
    apiCall.mockResolvedValue({});
    const { result } = setup();
    configure(result, "ospfFacts", { include_edges: false });
    await run(result);
    expect(lastRequest().body).toMatchObject({
      include_process: true,
      include_areas: true,
      include_interfaces: true,
      include_edges: false,
    });
  });
});

describe("preview-only questions", () => {
  it("store the response in the batfish variable", async () => {
    const response = { success: true, rows: [1] };
    apiCall.mockResolvedValue(response);
    const { result } = setup();
    configure(result, "routes");
    await run(result);
    await waitFor(() => expect(result.current.result).toEqual(response));
    expect(setBatfishResult).toHaveBeenCalledWith(response);
    expect(setParsedNamespaceEntry).not.toHaveBeenCalled();
  });

  it("clear the variable and the result when the query fails", async () => {
    apiCall.mockRejectedValue(new Error("boom"));
    const { result } = setup();
    configure(result, "routes");
    await run(result);
    await waitFor(() => expect(setBatfishResult).toHaveBeenCalledWith(null));
    expect(result.current.result).toBeNull();
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ description: "boom" }));
  });
});

describe("facts questions", () => {
  it("write the unwrapped payload into parsed.<default key> when output_key is blank", async () => {
    apiCall.mockResolvedValue({ facts_by_node: { sw1: { asn: 1 } } });
    const { result } = setup();
    configure(result, "ospfFacts");
    await run(result);
    await waitFor(() =>
      expect(setParsedNamespaceEntry).toHaveBeenCalledWith(DEFAULT_OUTPUT_KEY.ospfFacts, {
        parsed: { asn: 1 },
        error: null,
      }),
    );
    expect(setBatfishResult).not.toHaveBeenCalled();
  });

  it("use the configured output_key (trimmed)", async () => {
    apiCall.mockResolvedValue({ facts_by_node: { sw1: { a: 1 } } });
    const { result } = setup();
    configure(result, "bgpFacts", { output_key: " my_bgp " });
    await run(result);
    await waitFor(() => expect(setParsedNamespaceEntry).toHaveBeenCalledWith("my_bgp", expect.anything()));
  });

  it("clear the previously written key when the output_key changed before the next run", async () => {
    apiCall.mockResolvedValue({ facts_by_node: { sw1: { a: 1 } } });
    const { result } = setup();
    configure(result, "nodeProperties", { output_key: "first" });
    await run(result);
    await waitFor(() => expect(setParsedNamespaceEntry).toHaveBeenCalledWith("first", expect.anything()));

    act(() => result.current.setParams({ output_key: "second" }));
    await run(result);
    await waitFor(() => expect(setParsedNamespaceEntry).toHaveBeenCalledWith("second", expect.anything()));
    expect(clearParsedNamespaceEntry).toHaveBeenCalledWith("first");
  });

  it("clear their parsed entry when the query fails", async () => {
    apiCall.mockRejectedValue(new Error("nope"));
    const { result } = setup();
    configure(result, "extractFacts");
    await run(result);
    await waitFor(() => expect(clearParsedNamespaceEntry).toHaveBeenCalledWith(DEFAULT_OUTPUT_KEY.extractFacts));
  });
});

describe("keeping parsed in step with the tab", () => {
  async function writeFacts(result: Hook, question: "ospfFacts" | "bgpFacts", params = {}) {
    apiCall.mockResolvedValue({ facts_by_node: { sw1: { a: 1 } } });
    configure(result, question, params);
    await run(result);
    await waitFor(() => expect(setParsedNamespaceEntry).toHaveBeenCalled());
    clearParsedNamespaceEntry.mockClear();
  }

  it("clears the entry when the tab is disabled", async () => {
    const { result } = setup();
    await writeFacts(result, "ospfFacts");
    act(() => result.current.setEnabled(false));
    expect(clearParsedNamespaceEntry).toHaveBeenCalledWith(DEFAULT_OUTPUT_KEY.ospfFacts);
  });

  it("clears the entry when switching to a preview-only question", async () => {
    const { result } = setup();
    await writeFacts(result, "ospfFacts");
    act(() => result.current.setQuestion("routes"));
    expect(clearParsedNamespaceEntry).toHaveBeenCalledWith(DEFAULT_OUTPUT_KEY.ospfFacts);
  });

  // The entry belongs to the question that wrote it; leaving it behind would show OSPF facts
  // under another question's name until the next run.
  it("clears the entry when switching to a different facts question", async () => {
    const { result } = setup();
    await writeFacts(result, "ospfFacts");
    act(() => result.current.setQuestion("bgpFacts"));
    expect(clearParsedNamespaceEntry).toHaveBeenCalledWith(DEFAULT_OUTPUT_KEY.ospfFacts);
  });

  it("clears the entry when the output_key is edited", async () => {
    const { result } = setup();
    await writeFacts(result, "ospfFacts", { output_key: "first" });
    act(() => result.current.setParams({ output_key: "second" }));
    expect(clearParsedNamespaceEntry).toHaveBeenCalledWith("first");
  });

  it("clears it only once", async () => {
    const { result } = setup();
    await writeFacts(result, "ospfFacts");
    act(() => result.current.setEnabled(false));
    act(() => result.current.setQuestion("routes"));
    expect(clearParsedNamespaceEntry).toHaveBeenCalledTimes(1);
  });

  it("leaves parsed alone when nothing was written", () => {
    const { result } = setup();
    configure(result, "ospfFacts");
    act(() => result.current.setQuestion("routes"));
    expect(clearParsedNamespaceEntry).not.toHaveBeenCalled();
  });
});

describe("loadFromConfig / toConfig", () => {
  const saved: BatfishQueryConfig = {
    enabled: true,
    source_id: "bf9",
    network: "prod",
    snapshot: "s1",
    question: "bgpFacts",
    generic_question_name: null,
    params: { nodes: "sw1" },
  };

  it("restores the tab state from a saved config", () => {
    const { result } = setup();
    act(() => result.current.loadFromConfig(saved));
    expect(result.current).toMatchObject({
      enabled: true,
      question: "bgpFacts",
      genericQuestionName: "",
      params: { nodes: "sw1" },
      targetConfig: { batfish_source_id: "bf9", network: "prod", snapshot: "s1" },
      result: null,
    });
  });

  it("resets to the defaults for a template without Batfish config", () => {
    const { result } = setup();
    act(() => result.current.loadFromConfig(saved));
    act(() => result.current.loadFromConfig(null));
    expect(result.current).toMatchObject({
      enabled: false,
      question: "routes",
      params: {},
      targetConfig: {},
    });
  });

  it("round-trips through toConfig", () => {
    const { result } = setup();
    act(() => result.current.loadFromConfig(saved));
    expect(result.current.toConfig()).toEqual(saved);
  });

  it("serialises blanks as null", () => {
    const { result } = setup();
    expect(result.current.toConfig()).toEqual({
      enabled: false,
      source_id: null,
      network: null,
      snapshot: null,
      question: "routes",
      generic_question_name: null,
      params: {},
    });
  });
});

describe("referential stability", () => {
  it("returns the same object when nothing changed", () => {
    const { result, rerender } = setup();
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
