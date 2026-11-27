"use client";

import { useMutation } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";

import type {
  BatfishEditorQuestion,
  BatfishFactsQuestion,
  BatfishQueryConfig,
  BatfishQueryResult,
} from "../types";
import type { ParsedPath } from "../utils/parsed-path";
import type { useTemplateVariables } from "./use-template-variables";
import { boolField, stringField } from "@/components/features/workflow-steps/shared/config-field-helpers";

type TemplateVariablesManager = ReturnType<typeof useTemplateVariables>;

const QUESTION_ENDPOINT: Record<BatfishEditorQuestion, string> = {
  routes: "routes",
  reachability: "reachability",
  testFilters: "test-filters",
  generic: "generic",
  extractFacts: "extract-facts",
  ospfFacts: "ospf-facts",
  bgpFacts: "bgp-facts",
  nodeProperties: "node-properties",
  interfaceProperties: "interface-properties",
};

/** The 5 "facts" questions write into the real `parsed[node_id][output_key]`
 * entry the matching step writes at runtime, instead of the flat,
 * preview-only `batfish` variable -- see `BatfishFactsQuestion`'s own doc
 * comment in `../types`. */
const FACTS_QUESTIONS: readonly BatfishFactsQuestion[] = [
  "extractFacts",
  "ospfFacts",
  "bgpFacts",
  "nodeProperties",
  "interfaceProperties",
];

export function isFactsQuestion(
  question: BatfishEditorQuestion,
): question is BatfishFactsQuestion {
  return (FACTS_QUESTIONS as readonly string[]).includes(question);
}

/** Matches each facts step's own default `output_key` (see that step's
 * `config.py`), used when the "Output Key" field is left blank. */
export const DEFAULT_OUTPUT_KEY: Record<BatfishFactsQuestion, string> = {
  extractFacts: "batfish_extract_facts",
  ospfFacts: "batfish_ospf_facts",
  bgpFacts: "batfish_bgp_facts",
  nodeProperties: "batfish_node_properties",
  interfaceProperties: "batfish_interface_properties",
};

function outputKeyFor(question: BatfishFactsQuestion, params: Record<string, unknown>): string {
  return stringField(params, "output_key").trim() || DEFAULT_OUTPUT_KEY[question];
}

/** The canvas node id of the facts step whose output the template reads: a step writes
 * `parsed[node_id][output_key]` (W7-12), so the preview needs it too. */
function nodeIdFor(params: Record<string, unknown>): string {
  return stringField(params, "node_id").trim();
}

/** Where the preview writes, or `null` while the node id is missing. */
function factsPath(
  question: BatfishFactsQuestion,
  params: Record<string, unknown>,
): ParsedPath | null {
  const nodeId = nodeIdFor(params);
  return nodeId ? [nodeId, outputKeyFor(question, params)] : null;
}

/** The Jinja path of the preview's entry. Node ids contain dashes (`batfish-ospf-facts-2`),
 * so the node is subscripted. */
export function factsParsedPathLabel(
  question: BatfishFactsQuestion,
  params: Record<string, unknown>,
): string {
  return `parsed['${nodeIdFor(params) || "<node_id>"}'].${outputKeyFor(question, params)}`;
}

function samePath(a: ParsedPath | null, b: ParsedPath | null): boolean {
  if (a === null || b === null) return a === b;
  return a.length === b.length && a.every((part, index) => part === b[index]);
}

function buildRequestBody(
  question: BatfishEditorQuestion,
  network: string,
  snapshot: string,
  params: Record<string, unknown>,
  genericQuestionName: string,
): Record<string, unknown> {
  const base: Record<string, unknown> = { network };
  if (snapshot.trim()) {
    base.snapshot = snapshot.trim();
  }

  if (question === "generic") {
    return {
      ...base,
      question: genericQuestionName.trim(),
      params,
    };
  }

  if (question === "routes") {
    return {
      ...base,
      nodes: stringField(params, "nodes") || undefined,
      network_prefix: stringField(params, "network_prefix") || undefined,
      prefix_match_type: stringField(params, "prefix_match_type") || undefined,
      protocols: stringField(params, "protocols") || undefined,
      vrfs: stringField(params, "vrfs") || undefined,
      rib: stringField(params, "rib") || undefined,
    };
  }

  if (question === "reachability") {
    return {
      ...base,
      start_node: stringField(params, "start_node"),
      end_node: stringField(params, "end_node") || undefined,
      dst_ips: stringField(params, "dst_ips") || undefined,
      src_ips: stringField(params, "src_ips") || undefined,
      applications: Array.isArray(params.applications) ? params.applications : undefined,
      ip_protocols: stringField(params, "ip_protocols") || undefined,
      max_traces: typeof params.max_traces === "number" ? params.max_traces : undefined,
      invert_search: params.invert_search === true,
      ignore_filters: params.ignore_filters === true,
    };
  }

  if (question === "testFilters") {
    return {
      ...base,
      node: stringField(params, "node"),
      filter_name: stringField(params, "filter_name"),
      dst_ips: stringField(params, "dst_ips"),
      src_ips: stringField(params, "src_ips") || undefined,
      applications: Array.isArray(params.applications) ? params.applications : undefined,
      ip_protocols: stringField(params, "ip_protocols") || undefined,
      start_location: stringField(params, "start_location") || undefined,
    };
  }

  if (question === "extractFacts") {
    return {
      ...base,
      nodes_filter: stringField(params, "nodes_filter") || undefined,
    };
  }

  if (question === "ospfFacts") {
    return {
      ...base,
      nodes: stringField(params, "nodes") || undefined,
      include_process: boolField(params, "include_process", true),
      include_areas: boolField(params, "include_areas", true),
      include_interfaces: boolField(params, "include_interfaces", true),
      include_edges: boolField(params, "include_edges", true),
    };
  }

  if (question === "bgpFacts") {
    return {
      ...base,
      nodes: stringField(params, "nodes") || undefined,
      include_process: boolField(params, "include_process", true),
      include_peers: boolField(params, "include_peers", true),
      include_sessions: boolField(params, "include_sessions", true),
      include_edges: boolField(params, "include_edges", true),
    };
  }

  if (question === "nodeProperties") {
    return {
      ...base,
      nodes: stringField(params, "nodes") || undefined,
      properties: stringField(params, "properties") || undefined,
    };
  }

  // interfaceProperties
  return {
    ...base,
    nodes: stringField(params, "nodes") || undefined,
    interfaces: stringField(params, "interfaces") || undefined,
    properties: stringField(params, "properties") || undefined,
  };
}

function isQuestionReady(
  question: BatfishEditorQuestion,
  params: Record<string, unknown>,
  genericQuestionName: string,
): boolean {
  if (question === "generic") {
    return Boolean(genericQuestionName.trim());
  }
  if (question === "reachability") {
    return Boolean(stringField(params, "start_node").trim());
  }
  if (question === "testFilters") {
    return (
      Boolean(stringField(params, "node").trim()) &&
      Boolean(stringField(params, "filter_name").trim()) &&
      Boolean(stringField(params, "dst_ips").trim())
    );
  }
  if (isFactsQuestion(question) && !nodeIdFor(params)) {
    return false;
  }
  if (question === "ospfFacts") {
    return (
      boolField(params, "include_process", true) ||
      boolField(params, "include_areas", true) ||
      boolField(params, "include_interfaces", true) ||
      boolField(params, "include_edges", true)
    );
  }
  if (question === "bgpFacts") {
    return (
      boolField(params, "include_process", true) ||
      boolField(params, "include_peers", true) ||
      boolField(params, "include_sessions", true) ||
      boolField(params, "include_edges", true)
    );
  }
  return true;
}

/** How many nodes matched, and what to write into `parsed[node_id][output_key]`.
 *
 * A real workflow run always sees exactly one node per device, so when the
 * ad-hoc query also matches exactly one node, unwrap it to the identical
 * `{parsed, error}` shape `device.parsed[node_id][output_key]` holds at runtime. When
 * more than one node matches, fall back to the full `{node: payload}` dict
 * (still useful to inspect, but not the real per-device shape -- callers
 * should tell the user this differs from a real run). Zero matches mirrors
 * the workflow steps' own non-fatal "no facts found" error convention.
 */
export function pickFactsPayload(
  factsByNode: Record<string, unknown> | null | undefined,
): { parsed: unknown; error: string | null; nodeCount: number } {
  const entries = Object.entries(factsByNode ?? {});
  if (entries.length === 0) {
    return { parsed: null, error: "no facts found for this filter in this Batfish snapshot", nodeCount: 0 };
  }
  if (entries.length === 1) {
    return { parsed: entries[0][1], error: null, nodeCount: 1 };
  }
  return { parsed: factsByNode, error: null, nodeCount: entries.length };
}

interface UseTemplateEditorBatfishOptions {
  setBatfishResult: TemplateVariablesManager["setBatfishResult"];
  setParsedNamespaceEntry: TemplateVariablesManager["setParsedNamespaceEntry"];
  clearParsedNamespaceEntry: TemplateVariablesManager["clearParsedNamespaceEntry"];
}

export function useTemplateEditorBatfish({
  setBatfishResult,
  setParsedNamespaceEntry,
  clearParsedNamespaceEntry,
}: UseTemplateEditorBatfishOptions) {
  const { toast } = useToast();
  const { apiCall } = useApi();

  const [enabled, setEnabled] = useState(false);
  const [targetConfig, setTargetConfig] = useState<Record<string, unknown>>({});
  const [question, setQuestion] = useState<BatfishEditorQuestion>("routes");
  const [genericQuestionName, setGenericQuestionName] = useState("");
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [result, setResult] = useState<BatfishQueryResult | null>(null);
  // Tracks the `parsed[node_id][output_key]` entry this tab last wrote, if
  // any, so it can be cleared (rather than left stale) if the question,
  // node_id or output_key changes, or the tab is disabled/switched to a
  // non-facts question -- without waiting for the next "Run Query".
  const lastWrittenPathRef = useRef<ParsedPath | null>(null);

  const sourceId =
    typeof targetConfig.batfish_source_id === "string" ? targetConfig.batfish_source_id : "";
  const network = typeof targetConfig.network === "string" ? targetConfig.network : "";
  const snapshot = typeof targetConfig.snapshot === "string" ? targetConfig.snapshot : "";

  const runQueryMutation = useMutation({
    mutationFn: async () => {
      if (!sourceId || !network.trim()) {
        throw new Error("Select a Batfish source and network first");
      }
      if (isFactsQuestion(question) && !nodeIdFor(params)) {
        throw new Error("Enter the node id of the facts step first");
      }
      const endpoint = QUESTION_ENDPOINT[question];
      const body = buildRequestBody(question, network.trim(), snapshot, params, genericQuestionName);
      return apiCall<BatfishQueryResult>(`sources/batfish/${sourceId}/query/${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    },
    onSuccess: (response) => {
      setResult(response);
      // An entry written under another path was already cleared by the effect below when the
      // question, node id or output key changed.
      const path = isFactsQuestion(question)
        ? factsPath(question, params)
        : null;
      if (path) {
        const { parsed, error } = pickFactsPayload(response.facts_by_node);
        setParsedNamespaceEntry(path, { parsed, error });
        lastWrittenPathRef.current = path;
      } else {
        setBatfishResult(response);
      }
    },
    onError: (error) => {
      toast({
        title: "Batfish query failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
      setResult(null);
      if (isFactsQuestion(question)) {
        const path = factsPath(question, params);
        if (path) clearParsedNamespaceEntry(path);
        lastWrittenPathRef.current = null;
      } else {
        setBatfishResult(null);
      }
    },
  });

  // The `parsed[node_id][output_key]` entry belongs to the question, node id and key that wrote
  // it. When the tab is disabled, switched to another question, or its node id or output key is
  // edited, clear the entry instead of leaving it stale until the next "Run Query". The path is
  // compared part by part (two strings), so the effect depends on primitives only.
  const currentPath =
    enabled && isFactsQuestion(question) ? factsPath(question, params) : null;
  const currentNodeId = currentPath ? currentPath[0] : null;
  const currentOutputKey = currentPath ? currentPath[1] : null;
  useEffect(() => {
    const written = lastWrittenPathRef.current;
    const current: ParsedPath | null =
      currentNodeId !== null && currentOutputKey !== null
        ? [currentNodeId, currentOutputKey]
        : null;
    if (written && !samePath(written, current)) {
      clearParsedNamespaceEntry(written);
      lastWrittenPathRef.current = null;
    }
  }, [currentNodeId, currentOutputKey, clearParsedNamespaceEntry]);

  // `useMutation` returns a new object on every render; only `mutate` is stable.
  const { mutate: runQuery, isPending: isRunningQuery } = runQueryMutation;
  const handleRunQuery = useCallback(() => {
    runQuery();
  }, [runQuery]);

  const canRunQuery =
    Boolean(sourceId) &&
    Boolean(network.trim()) &&
    isQuestionReady(question, params, genericQuestionName);

  const loadFromConfig = useCallback((config: BatfishQueryConfig | null) => {
    lastWrittenPathRef.current = null;
    if (!config) {
      setEnabled(false);
      setTargetConfig({});
      setQuestion("routes");
      setGenericQuestionName("");
      setParams({});
      setResult(null);
      return;
    }
    setEnabled(config.enabled);
    setTargetConfig({
      batfish_source_id: config.source_id ?? "",
      network: config.network ?? "",
      snapshot: config.snapshot ?? "",
    });
    setQuestion(config.question ?? "routes");
    setGenericQuestionName(config.generic_question_name ?? "");
    setParams(config.params ?? {});
    setResult(null);
  }, []);

  const toConfig = useCallback((): BatfishQueryConfig => {
    return {
      enabled,
      source_id: sourceId || null,
      network: network.trim() || null,
      snapshot: snapshot.trim() || null,
      question,
      generic_question_name: genericQuestionName.trim() || null,
      params,
    };
  }, [enabled, sourceId, network, snapshot, question, genericQuestionName, params]);

  return useMemo(
    () => ({
      enabled,
      setEnabled,
      targetConfig,
      setTargetConfig,
      question,
      setQuestion,
      genericQuestionName,
      setGenericQuestionName,
      params,
      setParams,
      result,
      isRunningQuery,
      canRunQuery,
      handleRunQuery,
      loadFromConfig,
      toConfig,
    }),
    [
      enabled,
      targetConfig,
      question,
      genericQuestionName,
      params,
      result,
      isRunningQuery,
      canRunQuery,
      handleRunQuery,
      loadFromConfig,
      toConfig,
    ],
  );
}
