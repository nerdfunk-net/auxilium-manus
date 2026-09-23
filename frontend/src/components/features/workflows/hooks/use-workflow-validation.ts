"use client";

import { useCallback, useMemo, useState } from "react";

import { useWorkflowValidateMutation } from "@/hooks/queries/use-workflow-validate-mutation";

import type { PersistedCanvasNode } from "../types/workflow-canvas";
import type { WorkflowValidationResult } from "../types/workflow-validation";

export interface NodeValidationSummary {
  errorCount: number;
  warningCount: number;
}

interface UseWorkflowValidationOptions {
  workflowId: number | null;
  allNodes: PersistedCanvasNode[];
}

interface ValidationState {
  workflowId: number | null;
  result: WorkflowValidationResult;
}

export function useWorkflowValidation({ workflowId, allNodes }: UseWorkflowValidationOptions) {
  const [validationState, setValidationState] = useState<ValidationState | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const validateMutation = useWorkflowValidateMutation(workflowId);

  // A result recorded for a different (or no longer current) workflow says
  // nothing about the one now open — derived during render (not reset via an
  // effect) so it never lags a workflow switch by a frame.
  const result = validationState?.workflowId === workflowId ? validationState.result : null;

  const handleValidate = useCallback(() => {
    if (workflowId == null) return;
    validateMutation.mutate(allNodes as unknown as Record<string, unknown>[], {
      onSuccess: (data) => {
        setValidationState({ workflowId, result: data });
        setIsDialogOpen(true);
      },
    });
  }, [workflowId, allNodes, validateMutation]);

  const validationByNodeId = useMemo(() => {
    const map: Record<string, NodeValidationSummary> = {};
    if (!result) return map;
    for (const finding of result.findings) {
      if (!finding.node_id) continue;
      const entry = map[finding.node_id] ?? { errorCount: 0, warningCount: 0 };
      if (finding.severity === "error") {
        entry.errorCount += 1;
      } else {
        entry.warningCount += 1;
      }
      map[finding.node_id] = entry;
    }
    return map;
  }, [result]);

  return {
    result,
    validationByNodeId,
    isValidating: validateMutation.isPending,
    validateError: validateMutation.error,
    isDialogOpen,
    setIsDialogOpen,
    handleValidate,
  };
}
