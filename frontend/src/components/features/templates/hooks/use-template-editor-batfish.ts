"use client";

import { useMutation } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";

import type {
  BatfishEditorQuestion,
  BatfishQueryConfig,
  BatfishQueryResult,
} from "../types";
import type { useTemplateVariables } from "./use-template-variables";

type TemplateVariablesManager = ReturnType<typeof useTemplateVariables>;

const QUESTION_ENDPOINT: Record<BatfishEditorQuestion, string> = {
  routes: "routes",
  reachability: "reachability",
  testFilters: "test-filters",
  generic: "generic",
};

function stringField(params: Record<string, unknown>, key: string): string {
  const raw = params[key];
  return typeof raw === "string" ? raw : "";
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
  return true;
}

interface UseTemplateEditorBatfishOptions {
  setBatfishResult: TemplateVariablesManager["setBatfishResult"];
}

export function useTemplateEditorBatfish({ setBatfishResult }: UseTemplateEditorBatfishOptions) {
  const { toast } = useToast();
  const { apiCall } = useApi();

  const [enabled, setEnabled] = useState(false);
  const [targetConfig, setTargetConfig] = useState<Record<string, unknown>>({});
  const [question, setQuestion] = useState<BatfishEditorQuestion>("routes");
  const [genericQuestionName, setGenericQuestionName] = useState("");
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [result, setResult] = useState<BatfishQueryResult | null>(null);

  const sourceId =
    typeof targetConfig.batfish_source_id === "string" ? targetConfig.batfish_source_id : "";
  const network = typeof targetConfig.network === "string" ? targetConfig.network : "";
  const snapshot = typeof targetConfig.snapshot === "string" ? targetConfig.snapshot : "";

  const runQueryMutation = useMutation({
    mutationFn: async () => {
      if (!sourceId || !network.trim()) {
        throw new Error("Select a Batfish source and network first");
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
      setBatfishResult(response);
    },
    onError: (error) => {
      toast({
        title: "Batfish query failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
      setResult(null);
      setBatfishResult(null);
    },
  });

  const handleRunQuery = useCallback(() => {
    runQueryMutation.mutate();
  }, [runQueryMutation]);

  const canRunQuery =
    Boolean(sourceId) &&
    Boolean(network.trim()) &&
    isQuestionReady(question, params, genericQuestionName);

  const loadFromConfig = useCallback((config: BatfishQueryConfig | null) => {
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
      isRunningQuery: runQueryMutation.isPending,
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
      runQueryMutation.isPending,
      canRunQuery,
      handleRunQuery,
      loadFromConfig,
      toConfig,
    ],
  );
}
