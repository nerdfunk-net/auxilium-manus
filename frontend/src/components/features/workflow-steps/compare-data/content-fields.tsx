"use client";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ContentSourcePicker } from "@/components/features/workflow-steps/shared/content-source-picker";
import {
  CONTENT_SOURCE_OPTIONS,
  type ContentSource,
} from "@/components/features/workflow-steps/shared/content-source-options";
import type { UpstreamSourceStep } from "@/components/features/workflow-steps/shared/upstream-source-steps";

export const VALID_COMPARE_SOURCES = new Set([
  "running_config",
  "startup_config",
  "command_output",
  "latest_command_output",
  "rendered_template",
  "merged_content",
  "filtered_output",
  "pyats_snapshot",
]);

// compare-data can't reference "comparison_diff" (itself) or "updated_content"
// (not an available upstream source for a comparison) — filtered from the
// shared master list rather than duplicating it with a smaller hand-picked set.
export const COMPARE_DATA_SOURCE_OPTIONS = CONTENT_SOURCE_OPTIONS.filter(
  (option) => option.value === "upstream_output" || VALID_COMPARE_SOURCES.has(option.value),
);

export interface CompareDataContentFieldsProps {
  contentSource: ContentSource;
  selectedHint: string | undefined;
  autoDetected: { stepTitle: string; stepKind: string } | null;
  upstreamAvailable: boolean;
  needsStepNodeId: boolean;
  needsParsedOutputKey: boolean;
  sourceSteps: UpstreamSourceStep[];
  sourceStepNodeId: string;
  selectedSourceStep: UpstreamSourceStep | null;
  parsedOutputKey: string;
  onContentSourceChange: (value: string) => void;
  onSourceStepSelect: (nodeId: string) => void;
  onSourceStepNodeIdChange: (value: string) => void;
  onParsedOutputKeyChange: (value: string) => void;
}

export function CompareDataContentFields({
  contentSource,
  selectedHint,
  autoDetected,
  upstreamAvailable,
  needsStepNodeId,
  needsParsedOutputKey,
  sourceSteps,
  sourceStepNodeId,
  selectedSourceStep,
  parsedOutputKey,
  onContentSourceChange,
  onSourceStepSelect,
  onSourceStepNodeIdChange,
  onParsedOutputKeyChange,
}: CompareDataContentFieldsProps) {
  return (
    <>
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">content_source</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <ContentSourcePicker
          value={contentSource}
          onChange={onContentSourceChange}
          options={COMPARE_DATA_SOURCE_OPTIONS}
          isOptionDisabled={(value) => value === "upstream_output" && !upstreamAvailable}
        />
        {autoDetected ? (
          <p className="text-[11px] text-step-muted-foreground">
            ↑ Auto-detected from &ldquo;{autoDetected.stepTitle}&rdquo; ({autoDetected.stepKind})
          </p>
        ) : selectedHint ? (
          <p className="text-[11px] text-muted-foreground">{selectedHint}</p>
        ) : null}
      </div>

      {needsStepNodeId ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">source_step</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              step
            </Badge>
          </div>
          {sourceSteps.length > 0 ? (
            <Select
              value={sourceStepNodeId || ""}
              onValueChange={onSourceStepSelect}
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue
                  placeholder={
                    contentSource === "rendered_template"
                      ? "Choose render step…"
                      : contentSource === "merged_content"
                        ? "Choose merge-content step…"
                        : contentSource === "filtered_output"
                          ? "Choose filter-output step…"
                          : contentSource === "pyats_snapshot"
                            ? "Choose get-pyats-snapshot step…"
                            : "Choose run-command step…"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {sourceSteps.map((step) => (
                  <SelectItem key={step.nodeId} value={step.nodeId}>
                    {step.title} ({step.nodeId})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <p className="text-[11px] text-warning-foreground">
              {contentSource === "rendered_template"
                ? "Add a Render Jinja Template step to this workflow first."
                : contentSource === "merged_content"
                  ? "Add a Merge Content step to this workflow first."
                  : contentSource === "filtered_output"
                    ? "Add a Filter Output step to this workflow first."
                    : contentSource === "pyats_snapshot"
                      ? "Add a Get Snapshot step to this workflow first."
                      : "Add a Run Command step to this workflow first."}
            </p>
          )}
          {selectedSourceStep ? (
            <p className="text-[11px] text-muted-foreground">
              Selected{" "}
              <span className="font-mono">{selectedSourceStep.nodeId}</span>
              {selectedSourceStep.outputKey
                ? ` · output_key ${selectedSourceStep.outputKey}`
                : ""}
            </p>
          ) : null}
          <Input
            value={sourceStepNodeId}
            onChange={(event) => onSourceStepNodeIdChange(event.target.value)}
            placeholder={
              contentSource === "pyats_snapshot" ? "get-pyats-snapshot-3" : "run-command-3"
            }
            className="h-8 font-mono text-xs"
          />
        </div>
      ) : null}

      {needsParsedOutputKey ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">parsed_output_key</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <Input
            value={parsedOutputKey}
            onChange={(event) => onParsedOutputKeyChange(event.target.value)}
            placeholder={contentSource === "pyats_snapshot" ? "pyats_snapshot" : "device_config"}
            className="h-8 font-mono text-xs"
          />
        </div>
      ) : null}
    </>
  );
}
