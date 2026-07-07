"use client";

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
  const [isRendering, setIsRendering] = useState(false);
  const [result, setResult] = useState<TemplateRenderResponse | null>(null);
  const [showDialog, setShowDialog] = useState(false);

  const render = useCallback(
    async (content: string, variables: EditorVariable[]) => {
      setIsRendering(true);
      try {
        const response = await apiCall<TemplateRenderResponse>("templates/render", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            template_content: content,
            variables: buildVariablesContext(variables),
          }),
        });
        setResult(response);
        setShowDialog(true);
      } catch (error) {
        toast({
          title: "Render failed",
          description: error instanceof Error ? error.message : "Unknown error",
          variant: "destructive",
        });
      } finally {
        setIsRendering(false);
      }
    },
    [apiCall, toast],
  );

  return useMemo(
    () => ({ render, isRendering, result, showDialog, setShowDialog }),
    [render, isRendering, result, showDialog],
  );
}
