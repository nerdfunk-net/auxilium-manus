"use client";

import { useMutation } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";

import type { EditorVariable, TemplateRenderResponse } from "../types";

function parseVariableValue(value: string): unknown {
  if (value === "") {
    return "";
  }
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

/** Build a nested rendering context from the flat editor variable list. */
export function buildVariablesContext(
  variables: EditorVariable[],
): Record<string, unknown> {
  const context: Record<string, unknown> = {};
  for (const variable of variables) {
    if (!variable.name) {
      continue;
    }
    const parsed = parseVariableValue(variable.value);
    if (variable.name.includes(".")) {
      const parts = variable.name.split(".");
      let node = context as Record<string, unknown>;
      for (let index = 0; index < parts.length - 1; index += 1) {
        const key = parts[index];
        if (typeof node[key] !== "object" || node[key] === null) {
          node[key] = {};
        }
        node = node[key] as Record<string, unknown>;
      }
      node[parts[parts.length - 1]] = parsed;
    } else {
      context[variable.name] = parsed;
    }
  }
  return context;
}

export function useTemplateRender() {
  const { apiCall } = useApi();
  const { toast } = useToast();
  const [showDialog, setShowDialog] = useState(false);

  const renderMutation = useMutation({
    mutationFn: (input: { content: string; variables: EditorVariable[] }) =>
      apiCall<TemplateRenderResponse>("templates/render", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template_content: input.content,
          variables: buildVariablesContext(input.variables),
        }),
      }),
    onSuccess: () => setShowDialog(true),
    onError: (error) => {
      toast({
        title: "Render failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    },
  });

  const render = useCallback(
    (content: string, variables: EditorVariable[]) => {
      renderMutation.mutate({ content, variables });
    },
    [renderMutation],
  );

  return useMemo(
    () => ({
      render,
      isRendering: renderMutation.isPending,
      result: renderMutation.data ?? null,
      showDialog,
      setShowDialog,
    }),
    [render, renderMutation.isPending, renderMutation.data, showDialog],
  );
}
