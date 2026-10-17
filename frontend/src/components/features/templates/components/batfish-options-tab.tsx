"use client";

import { Info, Play, RefreshCw, TriangleAlert } from "lucide-react";
import { useCallback, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { stringField } from "@/components/features/workflow-steps/shared/config-field-helpers";
import { useBatfishNetworksQuery } from "@/hooks/queries/use-batfish-networks-query";
import { useBatfishSnapshotsQuery } from "@/hooks/queries/use-batfish-snapshots-query";
import { useBatfishSourcesQuery } from "@/hooks/queries/use-batfish-sources-query";

import { DEFAULT_OUTPUT_KEY, isFactsQuestion } from "../hooks/use-template-editor-batfish";
import type { BatfishEditorQuestion, BatfishQueryResult } from "../types";
import { BatfishGenericFields } from "./batfish-generic-fields";
import { BatfishIncludeToggles } from "./batfish-include-toggles";
import { ParamFieldGrid } from "./batfish-param-fields";
import { QUESTION_FIELDS } from "./batfish-question-fields";
import { BatfishResultPanel } from "./batfish-result-panel";

const QUESTION_OPTIONS: { value: BatfishEditorQuestion; label: string }[] = [
  { value: "routes", label: "Routing Table" },
  { value: "reachability", label: "Path Check" },
  { value: "testFilters", label: "ACL Check" },
  { value: "extractFacts", label: "Extract Facts" },
  { value: "ospfFacts", label: "Get OSPF Facts" },
  { value: "bgpFacts", label: "Get BGP Facts" },
  { value: "nodeProperties", label: "Batfish Node Properties" },
  { value: "interfaceProperties", label: "Batfish Interface Properties" },
  { value: "generic", label: "Custom Question…" },
];


/** Shared "Output Key" field for the 5 facts questions -- the `parsed.*`
 * key their preview result gets written under, defaulting to the matching
 * canvas step's own `output_key` default. */
function OutputKeyField({
  placeholder,
  value,
  onChange,
}: {
  placeholder: string;
  value: string;
  onChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor="batfish-output-key">Output Key (Optional)</Label>
      <Input
        id="batfish-output-key"
        value={value}
        onChange={onChange}
        placeholder={placeholder}
      />
      <p className="text-[11px] text-muted-foreground">
        Written to <code>parsed.{value || placeholder}</code>.
      </p>
    </div>
  );
}

interface BatfishOptionsTabProps {
  targetConfig: Record<string, unknown>;
  onTargetConfigChange: (config: Record<string, unknown>) => void;
  question: BatfishEditorQuestion;
  onQuestionChange: (question: BatfishEditorQuestion) => void;
  genericQuestionName: string;
  onGenericQuestionNameChange: (name: string) => void;
  params: Record<string, unknown>;
  onParamsChange: (params: Record<string, unknown>) => void;
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  onRunQuery: () => void;
  isRunningQuery: boolean;
  canRunQuery: boolean;
  result: BatfishQueryResult | null;
}

export function BatfishOptionsTab({
  targetConfig,
  onTargetConfigChange,
  question,
  onQuestionChange,
  genericQuestionName,
  onGenericQuestionNameChange,
  params,
  onParamsChange,
  enabled,
  onEnabledChange,
  onRunQuery,
  isRunningQuery,
  canRunQuery,
  result,
}: BatfishOptionsTabProps) {
  const { data: sourcesData } = useBatfishSourcesQuery();
  const sources = sourcesData?.sources ?? [];

  const sourceId =
    typeof targetConfig.batfish_source_id === "string" ? targetConfig.batfish_source_id : "";
  const network = typeof targetConfig.network === "string" ? targetConfig.network : "";
  const snapshot = typeof targetConfig.snapshot === "string" ? targetConfig.snapshot : "";

  const { data: networksData } = useBatfishNetworksQuery(sourceId);
  const networks = networksData?.networks ?? [];
  const { data: snapshotsData } = useBatfishSnapshotsQuery(sourceId, network);
  const snapshots = snapshotsData?.snapshots ?? [];

  const [networkManual, setNetworkManual] = useState(false);
  const [snapshotManual, setSnapshotManual] = useState(false);
  const networkPickerAvailable = Boolean(sourceId) && networks.length > 0;
  const snapshotPickerAvailable = Boolean(sourceId) && Boolean(network) && snapshots.length > 0;
  const showNetworkPicker = networkPickerAvailable && !networkManual;
  const showSnapshotPicker = snapshotPickerAvailable && !snapshotManual;

  const handleSourceChange = useCallback(
    (value: string) => onTargetConfigChange({ ...targetConfig, batfish_source_id: value }),
    [targetConfig, onTargetConfigChange],
  );

  // Locks into manual mode on the first keystroke -- otherwise, if the
  // networks/snapshots list finishes loading mid-typing, the picker swaps
  // back in under the user's cursor (losing focus and, in some browsers,
  // triggering an autofill-suggestions dropdown of every partial value
  // typed so far).
  const handleNetworkInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      setNetworkManual(true);
      onTargetConfigChange({ ...targetConfig, network: event.target.value });
    },
    [targetConfig, onTargetConfigChange],
  );

  const handleSnapshotInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      setSnapshotManual(true);
      onTargetConfigChange({ ...targetConfig, snapshot: event.target.value });
    },
    [targetConfig, onTargetConfigChange],
  );

  const handleNetworkSelect = useCallback(
    (value: string) => onTargetConfigChange({ ...targetConfig, network: value, snapshot: "" }),
    [targetConfig, onTargetConfigChange],
  );

  const handleSnapshotSelect = useCallback(
    (value: string) => onTargetConfigChange({ ...targetConfig, snapshot: value }),
    [targetConfig, onTargetConfigChange],
  );

  const factsQuestion = isFactsQuestion(question);

  return (
    <div className="space-y-4">
      {factsQuestion ? (
        <Alert variant="info">
          <Info />
          <AlertDescription>
            This preview writes into <code>parsed.{stringField(params, "output_key") || DEFAULT_OUTPUT_KEY[question]}</code>,
            matching what a real workflow run of this step produces (see the
            Jinja help dialog). When the query matches more than one node,
            the full <code>{"{node: payload}"}</code> map is written instead
            of one node&apos;s flat shape — narrow <strong>Nodes</strong>{" "}
            to a single device to preview the exact per-device shape a real
            run always sees.
          </AlertDescription>
        </Alert>
      ) : (
        <Alert variant="warning">
          <TriangleAlert />
          <AlertDescription>
            <strong>Preview-only.</strong> This runs an ad-hoc query for
            exploration while you write the template — no workflow step ever
            populates a <code>batfish</code> variable. Routing Table, Path
            Check, and ACL Check store their results only as a workflow-level
            artifact, never on a device, so a template referencing{" "}
            <code>batfish.*</code> will render here but fail every device with
            &quot;Undefined template variable: &apos;batfish&apos; is undefined&quot; when
            the workflow actually runs. For real per-device Batfish data in a
            template, use <code>parsed.&lt;output_key&gt;</code> from Extract
            Facts, Get OSPF Facts, Get BGP Facts, or Batfish Node/Interface
            Properties instead (see the Jinja help dialog).
          </AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label>Batfish Source</Label>
          <Select value={sourceId} onValueChange={handleSourceChange}>
            <SelectTrigger>
              <SelectValue placeholder="Select source…" />
            </SelectTrigger>
            <SelectContent>
              {sources.length === 0 ? (
                <SelectItem value="__none__" disabled>
                  No Batfish sources configured
                </SelectItem>
              ) : (
                sources.map((source) => (
                  <SelectItem key={source.source_id} value={source.source_id}>
                    {source.source_id} ({source.host}:{source.port})
                  </SelectItem>
                ))
              )}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label>Question</Label>
          <Select
            value={question}
            onValueChange={(value) => onQuestionChange(value as BatfishEditorQuestion)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {QUESTION_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="batfish-network">Network</Label>
          {showNetworkPicker ? (
            <Select value={network || ""} onValueChange={handleNetworkSelect}>
              <SelectTrigger>
                <SelectValue placeholder="Choose a network…" />
              </SelectTrigger>
              <SelectContent>
                {networks.map((name) => (
                  <SelectItem key={name} value={name}>
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <Input
              id="batfish-network"
              value={network}
              onChange={handleNetworkInputChange}
              placeholder="e.g. manus-production"
              autoComplete="off"
            />
          )}
          {networkPickerAvailable ? (
            <button
              type="button"
              onClick={() => setNetworkManual((current) => !current)}
              className="text-[11px] text-muted-foreground underline hover:text-foreground"
            >
              {networkManual ? "Choose from list" : "Enter manually"}
            </button>
          ) : null}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="batfish-snapshot">Snapshot (Optional)</Label>
          {showSnapshotPicker ? (
            <Select value={snapshot || ""} onValueChange={handleSnapshotSelect}>
              <SelectTrigger>
                <SelectValue placeholder="(most recent)" />
              </SelectTrigger>
              <SelectContent>
                {snapshots.map((snap) => (
                  <SelectItem key={snap.name} value={snap.name}>
                    {snap.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <Input
              id="batfish-snapshot"
              value={snapshot}
              onChange={handleSnapshotInputChange}
              placeholder="(most recent)"
              autoComplete="off"
            />
          )}
          {snapshotPickerAvailable ? (
            <button
              type="button"
              onClick={() => setSnapshotManual((current) => !current)}
              className="text-[11px] text-muted-foreground underline hover:text-foreground"
            >
              {snapshotManual ? "Choose from list" : "Enter manually"}
            </button>
          ) : sourceId && !network ? (
            <p className="text-[11px] text-muted-foreground">Pick or enter a network first.</p>
          ) : null}
        </div>
      </div>


      {QUESTION_FIELDS[question] ? (
        <ParamFieldGrid
          fields={QUESTION_FIELDS[question]}
          params={params}
          onParamsChange={onParamsChange}
        >
          {factsQuestion ? (
            <OutputKeyField
              placeholder={DEFAULT_OUTPUT_KEY[question]}
              value={stringField(params, "output_key")}
              onChange={(event) =>
                onParamsChange({ ...params, output_key: event.target.value })
              }
            />
          ) : null}
          {question === "ospfFacts" || question === "bgpFacts" ? (
            <BatfishIncludeToggles
              question={question}
              params={params}
              onParamsChange={onParamsChange}
            />
          ) : null}
        </ParamFieldGrid>
      ) : null}

      {question === "generic" ? (
        <BatfishGenericFields
          questionName={genericQuestionName}
          onQuestionNameChange={onGenericQuestionNameChange}
          params={params}
          onParamsChange={onParamsChange}
        />
      ) : null}

      <div className="flex items-center gap-2 border-t pt-4">
        <label
          htmlFor="batfish-enable-result"
          className="flex h-9 flex-1 items-center gap-2 rounded-md border border-input bg-card px-3 text-xs"
        >
          <Checkbox
            id="batfish-enable-result"
            checked={enabled}
            onCheckedChange={(checked) => onEnabledChange(checked === true)}
          />
          <span>Enable Batfish Result</span>
        </label>
        {enabled ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!canRunQuery || isRunningQuery}
            onClick={onRunQuery}
          >
            {isRunningQuery ? (
              <RefreshCw className="size-3.5 animate-spin" />
            ) : (
              <Play className="size-3.5" />
            )}
            Run Query
          </Button>
        ) : null}
      </div>

      {result ? <BatfishResultPanel result={result} /> : null}
    </div>
  );
}
