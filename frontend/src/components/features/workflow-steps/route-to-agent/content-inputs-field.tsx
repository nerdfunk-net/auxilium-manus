"use client";

import { useMemo } from "react";

import type { PersistedCanvasNode } from "@/components/features/workflows/types/workflow-canvas";

import { CheckboxField } from "../shared/checkbox-field";
import { listUpstreamSourceSteps } from "../shared/upstream-source-steps";
import { COMMAND_OUTPUT_PREFIX, STATIC_CONTENT_INPUTS } from "./config";

interface ContentInputsFieldProps {
  nodeId: string;
  selected: string[];
  workflowNodes: PersistedCanvasNode[];
  onChange: (next: string[]) => void;
}

/** Which device content is sent as text: configs, the latest command output, or a Run Command step's. */
export function ContentInputsField({
  nodeId,
  selected,
  workflowNodes,
  onChange,
}: ContentInputsFieldProps) {
  const commandSteps = useMemo(
    () => listUpstreamSourceSteps(workflowNodes, "command_output", nodeId),
    [workflowNodes, nodeId],
  );
  const options = useMemo(
    () => [
      ...STATIC_CONTENT_INPUTS.map((item) => ({ value: item.value, label: item.label })),
      ...commandSteps.map((step) => ({
        value: `${COMMAND_OUTPUT_PREFIX}${step.nodeId}`,
        label: `Output of ${step.title}`,
      })),
    ],
    [commandSteps],
  );

  const toggle = (value: string, checked: boolean) =>
    onChange(checked ? [...selected, value] : selected.filter((item) => item !== value));

  return (
    <div className="space-y-2">
      <span className="font-mono text-xs font-medium">content_inputs</span>
      <div className="space-y-2">
        {options.map((option) => (
          <CheckboxField
            key={option.value}
            id={`route-to-agent-content-${option.value}`}
            label={option.label}
            checked={selected.includes(option.value)}
            onCheckedChange={(checked) => toggle(option.value, checked)}
          />
        ))}
      </div>
      <p className="text-[11px] text-muted-foreground">
        Sent as text under <span className="font-mono">inputs.content</span>. Content a device
        does not have is left out.
      </p>
    </div>
  );
}
