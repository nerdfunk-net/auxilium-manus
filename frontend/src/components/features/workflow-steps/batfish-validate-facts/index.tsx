"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { EMPTY_WORKFLOW_NODES } from "@/components/features/workflows/constants/empty-canvas";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { BatfishDirectTargetFields } from "../shared/batfish-direct-target-fields";
import { BATFISH_FACT_KEYS } from "../shared/batfish-fact-keys";
import { listUpstreamSourceSteps } from "../shared/upstream-source-steps";
import { BatfishValidateFactsHelpPanel } from "./help-panel";

const FACTS_SOURCE_KEY = "facts_source";
const DEFAULT_FACTS_SOURCE = "rendered_yaml";
const FACTS_SOURCES = ["rendered_yaml", "field"] as const;

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function BatfishValidateFactsConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes = EMPTY_WORKFLOW_NODES,
}: PluginConfigPanelProps) {
  const factsSource = stringFromConfig(config, FACTS_SOURCE_KEY) || DEFAULT_FACTS_SOURCE;
  const sourceStepNodeId = stringFromConfig(config, "source_step_node_id");
  const parsedOutputKey = stringFromConfig(config, "parsed_output_key");
  const factKey = stringFromConfig(config, "fact_key");
  const factValue = stringFromConfig(config, "fact_value");
  const outputKey = stringFromConfig(config, "output_key");

  const sourceSteps = useMemo(
    () => listUpstreamSourceSteps(workflowNodes, "rendered_template", nodeId),
    [workflowNodes, nodeId],
  );
  const selectedSourceStep = useMemo(
    () => sourceSteps.find((step) => step.nodeId === sourceStepNodeId) ?? null,
    [sourceSteps, sourceStepNodeId],
  );
  const [sourceStepManual, setSourceStepManual] = useState(false);
  const sourceStepPickerAvailable = sourceSteps.length > 0;
  const showSourceStepPicker = sourceStepPickerAvailable && !sourceStepManual;

  const handleFactsSourceChange = useCallback(
    (value: string) => onChange({ ...config, [FACTS_SOURCE_KEY]: value }),
    [config, onChange],
  );

  const handleFieldChange = useCallback(
    (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [key]: event.target.value });
    },
    [config, onChange],
  );

  // Locks into manual mode on the first keystroke -- otherwise, if the
  // upstream-step list changes mid-typing, the picker swaps back in under
  // the user's cursor (losing focus and, in some browsers, triggering an
  // autofill-suggestions dropdown of every partial value typed so far).
  const handleSourceStepInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      setSourceStepManual(true);
      onChange({ ...config, source_step_node_id: event.target.value });
    },
    [config, onChange],
  );

  const handleSourceStepSelect = useCallback(
    (selectedNodeId: string) => {
      const step = sourceSteps.find((candidate) => candidate.nodeId === selectedNodeId);
      const patch: Record<string, unknown> = { source_step_node_id: selectedNodeId };
      if (step?.outputKey && !parsedOutputKey) {
        patch.parsed_output_key = step.outputKey;
      }
      onChange({ ...config, ...patch });
    },
    [config, onChange, parsedOutputKey, sourceSteps],
  );

  // Auto-select the source step once it's unambiguous, mirroring
  // compare-pyats-snapshot's own source_step picker behavior.
  useEffect(() => {
    if (factsSource !== "rendered_yaml" || sourceSteps.length !== 1 || sourceStepNodeId) {
      return;
    }
    handleSourceStepSelect(sourceSteps[0].nodeId);
  }, [factsSource, sourceStepNodeId, sourceSteps, handleSourceStepSelect]);

  const handleFactKeyChange = useCallback(
    (value: string) => onChange({ ...config, fact_key: value }),
    [config, onChange],
  );

  const handleFactValueChange = useCallback(
    (value: string) => onChange({ ...config, fact_value: value }),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{FACTS_SOURCE_KEY}</span>
        <Select value={factsSource} onValueChange={handleFactsSourceChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder={DEFAULT_FACTS_SOURCE} />
          </SelectTrigger>
          <SelectContent>
            {FACTS_SOURCES.map((value) => (
              <SelectItem key={value} value={value}>
                {value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[11px] leading-4 text-muted-foreground">
          rendered_yaml reads an upstream Render Jinja Template step&apos;s output; field builds
          one fact inline, per device.
        </p>
      </div>

      {factsSource === "rendered_yaml" ? (
        <>
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">source_step_node_id</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                step
              </Badge>
            </div>
            {showSourceStepPicker ? (
              <Select value={sourceStepNodeId || ""} onValueChange={handleSourceStepSelect}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue placeholder="Choose Render Jinja Template step…" />
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
              <Input
                value={sourceStepNodeId}
                onChange={handleSourceStepInputChange}
                placeholder="e.g. render-facts-1"
                className="h-8 font-mono text-xs"
                autoComplete="off"
              />
            )}
            {sourceStepPickerAvailable ? (
              <button
                type="button"
                onClick={() => setSourceStepManual((current) => !current)}
                className="text-[11px] text-muted-foreground underline hover:text-foreground"
              >
                {sourceStepManual ? "Choose from list" : "Enter manually"}
              </button>
            ) : (
              <p className="text-[11px] text-warning-foreground">
                Add a Render Jinja Template step to this workflow first.
              </p>
            )}
            {selectedSourceStep ? (
              <p className="text-[11px] text-muted-foreground">
                Selected <span className="font-mono">{selectedSourceStep.nodeId}</span>
                {selectedSourceStep.outputKey
                  ? ` · output_key ${selectedSourceStep.outputKey}`
                  : ""}
              </p>
            ) : null}
            {sourceStepNodeId ? null : (
              <p className="text-[11px] text-warning-foreground">Required</p>
            )}
            <p className="text-[11px] leading-4 text-muted-foreground">
              Its rendered YAML must have a top-level &quot;nodes&quot; mapping keyed by each
              device&apos;s own name.
            </p>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">parsed_output_key</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={parsedOutputKey}
              onChange={handleFieldChange("parsed_output_key")}
              placeholder="(any output_key)"
              className="h-8 font-mono text-xs"
            />
          </div>
        </>
      ) : (
        <>
          <div className="space-y-1.5">
            <span className="font-mono text-xs font-medium">fact_key</span>
            <Select value={factKey} onValueChange={handleFactKeyChange}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue placeholder="Choose a fact key" />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {BATFISH_FACT_KEYS.map((value) => (
                  <SelectItem key={value} value={value}>
                    {value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {factKey ? null : <p className="text-[11px] text-warning-foreground">Required</p>}
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">fact_value</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                jinja
              </Badge>
            </div>
            <Textarea
              value={factValue}
              onChange={(event) => handleFactValueChange(event.target.value)}
              placeholder="e.g. {{ nautobot.custom_fields.tacacs_servers }}"
              className="min-h-16 font-mono text-xs focus-visible:ring-step/40"
            />
            {factValue ? null : <p className="text-[11px] text-warning-foreground">Required</p>}
            <p className="text-[11px] leading-4 text-muted-foreground">
              Rendered per device. May resolve to a scalar (10.0.0.1) or a YAML/JSON list
              ([10.0.0.1, 10.0.0.2]).
            </p>
          </div>
        </>
      )}

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">output_key</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={outputKey}
          onChange={handleFieldChange("output_key")}
          placeholder="batfish_validate_facts"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          The aggregate result is stored under this key in the run&apos;s metadata; each
          device&apos;s own mismatch detail (if any) is also written under this key.
        </p>
      </div>

      <BatfishDirectTargetFields config={config} onChange={onChange} />
    </div>
  );
}

export const BatfishValidateFactsPlugin: PluginUIComponent = {
  ConfigPanel: BatfishValidateFactsConfigPanel,
  HelpPanel: BatfishValidateFactsHelpPanel,
};
