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

export interface StoreArtifactContentFieldsProps {
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

export function StoreArtifactContentFields({
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
}: StoreArtifactContentFieldsProps) {
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
          options={CONTENT_SOURCE_OPTIONS}
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
              value={sourceStepNodeId || undefined}
              onValueChange={onSourceStepSelect}
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue
                  placeholder={
                    contentSource === "rendered_template"
                      ? "Choose render step…"
                      : contentSource === "merged_content"
                        ? "Choose merge-content step…"
                        : contentSource === "comparison_diff"
                          ? "Choose compare-data step…"
                          : contentSource === "filtered_output"
                            ? "Choose filter-output step…"
                            : contentSource === "pyats_snapshot"
                              ? "Choose get-pyats-snapshot step…"
                              : contentSource === "updated_content"
                                ? "Choose update-content step…"
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
                  : contentSource === "comparison_diff"
                    ? "Add a Compare Data step to this workflow first."
                    : contentSource === "filtered_output"
                      ? "Add a Filter Output step to this workflow first."
                      : contentSource === "pyats_snapshot"
                        ? "Add a Get Snapshot step to this workflow first."
                        : contentSource === "updated_content"
                          ? "Add an Update Content step to this workflow first."
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
          ) : sourceStepNodeId && sourceSteps.length > 0 ? (
            <p className="text-[11px] text-warning-foreground">
              Saved node id{" "}
              <span className="font-mono">{sourceStepNodeId}</span> is not on this
              canvas. Pick a step above or enter an id manually.
            </p>
          ) : null}
          <details className="rounded-lg border bg-muted/20 px-3 py-2">
            <summary className="cursor-pointer text-[11px] font-medium text-muted-foreground">
              Advanced: enter node id manually
            </summary>
            <div className="mt-2 space-y-1.5">
              <Input
                value={sourceStepNodeId}
                onChange={(event) => onSourceStepNodeIdChange(event.target.value)}
                placeholder={
                  contentSource === "rendered_template"
                    ? "render-jinja-template-3"
                    : contentSource === "merged_content"
                      ? "merge-content-3"
                      : contentSource === "comparison_diff"
                        ? "compare-data-3"
                        : contentSource === "pyats_snapshot"
                          ? "get-pyats-snapshot-3"
                          : contentSource === "updated_content"
                            ? "update-content-3"
                            : "run-command-3"
                }
                className="h-8 font-mono text-xs"
              />
              <p className="text-[11px] text-muted-foreground">
                Only needed when reusing an id from an older workflow or run results.
              </p>
            </div>
          </details>
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
          <p className="text-[11px] text-muted-foreground">
            {contentSource === "pyats_snapshot"
              ? "Optional output_key from the Get Snapshot step. Leave empty to export all snapshots produced by the selected step."
              : "Optional output_key from the render step. Leave empty to export all templates produced by the selected step."}
          </p>
        </div>
      ) : null}
    </>
  );
}
