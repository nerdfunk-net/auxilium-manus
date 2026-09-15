"use client";

import { Play, RefreshCw } from "lucide-react";
import { useCallback, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useBatfishNetworksQuery } from "@/hooks/queries/use-batfish-networks-query";
import { useBatfishSnapshotsQuery } from "@/hooks/queries/use-batfish-snapshots-query";
import { useBatfishSourcesQuery } from "@/hooks/queries/use-batfish-sources-query";

import { BATFISH_GENERIC_QUESTION_NAMES } from "@/components/features/workflow-steps/shared/batfish-generic-question-names";

import type { BatfishEditorQuestion, BatfishQueryResult } from "../types";

const QUESTION_OPTIONS: { value: BatfishEditorQuestion; label: string }[] = [
  { value: "routes", label: "Routing Table" },
  { value: "reachability", label: "Path Check" },
  { value: "testFilters", label: "ACL Check" },
  { value: "generic", label: "Custom Question…" },
];

const PREFIX_MATCH_TYPES = [
  "EXACT",
  "LONGEST_PREFIX_MATCH",
  "LONGER_PREFIXES",
  "SHORTER_PREFIXES",
] as const;

const RIBS = ["main", "bgp", "evpn"] as const;

function stringField(params: Record<string, unknown>, key: string): string {
  const raw = params[key];
  return typeof raw === "string" ? raw : "";
}

function numberField(params: Record<string, unknown>, key: string): string {
  const raw = params[key];
  return typeof raw === "number" ? String(raw) : typeof raw === "string" ? raw : "";
}

function boolField(params: Record<string, unknown>, key: string): boolean {
  return params[key] === true;
}

function applicationsField(params: Record<string, unknown>): string {
  const raw = params.applications;
  return Array.isArray(raw)
    ? raw.filter((item): item is string => typeof item === "string").join(", ")
    : "";
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

  const handleFieldChange = useCallback(
    (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
      onParamsChange({ ...params, [key]: event.target.value });
    },
    [params, onParamsChange],
  );

  const handleSelectFieldChange = useCallback(
    (key: string) => (value: string) => onParamsChange({ ...params, [key]: value }),
    [params, onParamsChange],
  );

  const handleSwitchFieldChange = useCallback(
    (key: string) => (checked: boolean) => onParamsChange({ ...params, [key]: checked }),
    [params, onParamsChange],
  );

  const handleApplicationsChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const applications = event.target.value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      onParamsChange({ ...params, applications });
    },
    [params, onParamsChange],
  );

  const handleMaxTracesChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const value = event.target.value;
      const parsed = Number.parseInt(value, 10);
      onParamsChange({ ...params, max_traces: Number.isNaN(parsed) ? value : parsed });
    },
    [params, onParamsChange],
  );

  const handleGenericQuestionNameChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => onGenericQuestionNameChange(event.target.value),
    [onGenericQuestionNameChange],
  );

  // Buffered locally so invalid-mid-typing JSON doesn't get discarded --
  // only re-synced from `params` when the question just switched *into*
  // "generic" (loadFromConfig already resets `params` at the same time it
  // sets `question`, so this still picks up a freshly loaded template).
  // Adjusted during render (React's documented pattern for resetting state
  // on a prop change) rather than in a useEffect, which would set state one
  // render late and trigger an extra cascading render.
  const [genericParamsText, setGenericParamsText] = useState(() => JSON.stringify(params, null, 2));
  const [genericParamsError, setGenericParamsError] = useState<string | null>(null);
  const [prevQuestion, setPrevQuestion] = useState(question);
  if (question !== prevQuestion) {
    setPrevQuestion(question);
    if (question === "generic") {
      setGenericParamsText(JSON.stringify(params, null, 2));
      setGenericParamsError(null);
    }
  }

  const handleGenericParamsChange = useCallback(
    (event: React.ChangeEvent<HTMLTextAreaElement>) => {
      const text = event.target.value;
      setGenericParamsText(text);
      if (!text.trim()) {
        setGenericParamsError(null);
        onParamsChange({});
        return;
      }
      try {
        const parsed: unknown = JSON.parse(text);
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          throw new Error("Params must be a JSON object");
        }
        setGenericParamsError(null);
        onParamsChange(parsed as Record<string, unknown>);
      } catch (error) {
        setGenericParamsError(error instanceof Error ? error.message : "Invalid JSON");
      }
    },
    [onParamsChange],
  );

  return (
    <div className="space-y-4">
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

      {question === "routes" ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="batfish-nodes">Nodes (Optional)</Label>
            <Input
              id="batfish-nodes"
              value={stringField(params, "nodes")}
              onChange={handleFieldChange("nodes")}
              placeholder="e.g. R1"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-network-prefix">Network Prefix (Optional)</Label>
            <Input
              id="batfish-network-prefix"
              value={stringField(params, "network_prefix")}
              onChange={handleFieldChange("network_prefix")}
              placeholder="e.g. 192.168.1.0/24"
            />
          </div>
          <div className="space-y-1.5">
            <Label>Prefix Match Type</Label>
            <Select
              value={stringField(params, "prefix_match_type") || "EXACT"}
              onValueChange={handleSelectFieldChange("prefix_match_type")}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PREFIX_MATCH_TYPES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-protocols">Protocols (Optional)</Label>
            <Input
              id="batfish-protocols"
              value={stringField(params, "protocols")}
              onChange={handleFieldChange("protocols")}
              placeholder="e.g. static, bgp"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-vrfs">VRFs (Optional)</Label>
            <Input
              id="batfish-vrfs"
              value={stringField(params, "vrfs")}
              onChange={handleFieldChange("vrfs")}
              placeholder="e.g. default"
            />
          </div>
          <div className="space-y-1.5">
            <Label>RIB</Label>
            <Select
              value={stringField(params, "rib") || "main"}
              onValueChange={handleSelectFieldChange("rib")}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RIBS.map((value) => (
                  <SelectItem key={value} value={value}>
                    {value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      ) : null}

      {question === "reachability" ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="batfish-start-node">Start Node</Label>
            <Input
              id="batfish-start-node"
              value={stringField(params, "start_node")}
              onChange={handleFieldChange("start_node")}
              placeholder="e.g. R1"
            />
            {stringField(params, "start_node").trim() ? null : (
              <p className="text-xs text-destructive">Required</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-end-node">End Node (Optional)</Label>
            <Input
              id="batfish-end-node"
              value={stringField(params, "end_node")}
              onChange={handleFieldChange("end_node")}
              placeholder="e.g. R2 (any destination if blank)"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-dst-ips">Destination IPs (Optional)</Label>
            <Input
              id="batfish-dst-ips"
              value={stringField(params, "dst_ips")}
              onChange={handleFieldChange("dst_ips")}
              placeholder="e.g. 192.168.1.1"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-src-ips">Source IPs (Optional)</Label>
            <Input
              id="batfish-src-ips"
              value={stringField(params, "src_ips")}
              onChange={handleFieldChange("src_ips")}
              placeholder="e.g. 10.0.0.1"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-applications">Applications (Optional)</Label>
            <Input
              id="batfish-applications"
              value={applicationsField(params)}
              onChange={handleApplicationsChange}
              placeholder="e.g. SSH, HTTPS"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-ip-protocols">IP Protocols (Optional)</Label>
            <Input
              id="batfish-ip-protocols"
              value={stringField(params, "ip_protocols")}
              onChange={handleFieldChange("ip_protocols")}
              placeholder="e.g. tcp"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-max-traces">Max Traces (Optional)</Label>
            <Input
              id="batfish-max-traces"
              type="number"
              min={1}
              value={numberField(params, "max_traces")}
              onChange={handleMaxTracesChange}
            />
          </div>
          <div className="flex items-center justify-between rounded-md border px-3 py-2">
            <Label htmlFor="batfish-invert-search">Invert Search</Label>
            <Switch
              id="batfish-invert-search"
              checked={boolField(params, "invert_search")}
              onCheckedChange={handleSwitchFieldChange("invert_search")}
            />
          </div>
          <div className="flex items-center justify-between rounded-md border px-3 py-2">
            <Label htmlFor="batfish-ignore-filters">Ignore Filters</Label>
            <Switch
              id="batfish-ignore-filters"
              checked={boolField(params, "ignore_filters")}
              onCheckedChange={handleSwitchFieldChange("ignore_filters")}
            />
          </div>
        </div>
      ) : null}

      {question === "testFilters" ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="batfish-node">Node</Label>
            <Input
              id="batfish-node"
              value={stringField(params, "node")}
              onChange={handleFieldChange("node")}
              placeholder="e.g. R1"
            />
            {stringField(params, "node").trim() ? null : (
              <p className="text-xs text-destructive">Required</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-filter-name">Filter Name</Label>
            <Input
              id="batfish-filter-name"
              value={stringField(params, "filter_name")}
              onChange={handleFieldChange("filter_name")}
              placeholder="e.g. TEST-ACL"
            />
            {stringField(params, "filter_name").trim() ? null : (
              <p className="text-xs text-destructive">Required</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-tf-dst-ips">Destination IPs</Label>
            <Input
              id="batfish-tf-dst-ips"
              value={stringField(params, "dst_ips")}
              onChange={handleFieldChange("dst_ips")}
              placeholder="e.g. 192.168.1.1"
            />
            {stringField(params, "dst_ips").trim() ? null : (
              <p className="text-xs text-destructive">Required</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-tf-src-ips">Source IPs (Optional)</Label>
            <Input
              id="batfish-tf-src-ips"
              value={stringField(params, "src_ips")}
              onChange={handleFieldChange("src_ips")}
              placeholder="e.g. 8.8.8.8"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-tf-applications">Applications (Optional)</Label>
            <Input
              id="batfish-tf-applications"
              value={applicationsField(params)}
              onChange={handleApplicationsChange}
              placeholder="e.g. SSH, TELNET"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-tf-ip-protocols">IP Protocols (Optional)</Label>
            <Input
              id="batfish-tf-ip-protocols"
              value={stringField(params, "ip_protocols")}
              onChange={handleFieldChange("ip_protocols")}
              placeholder="e.g. tcp"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-start-location">Start Location (Optional)</Label>
            <Input
              id="batfish-start-location"
              value={stringField(params, "start_location")}
              onChange={handleFieldChange("start_location")}
              placeholder="optional"
            />
          </div>
        </div>
      ) : null}

      {question === "generic" ? (
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="batfish-generic-question">Question Name</Label>
            <Input
              id="batfish-generic-question"
              value={genericQuestionName}
              onChange={handleGenericQuestionNameChange}
              placeholder="e.g. bgpPeerConfiguration"
              list="batfish-generic-question-names"
              autoComplete="off"
            />
            <datalist id="batfish-generic-question-names">
              {BATFISH_GENERIC_QUESTION_NAMES.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
            <p className="text-[11px] leading-4 text-muted-foreground">
              A suggestion list, not the full set of allowed questions --
              the backend rejects anything not on its own allow-list with a
              plain 400.
            </p>
            {genericQuestionName.trim() ? null : (
              <p className="text-xs text-destructive">Required</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batfish-generic-params">Params (JSON, Optional)</Label>
            <Textarea
              id="batfish-generic-params"
              value={genericParamsText}
              onChange={handleGenericParamsChange}
              placeholder={'{\n  "nodes": "R1"\n}'}
              className="min-h-24 font-mono text-xs"
            />
            {genericParamsError ? (
              <p className="text-xs text-destructive">{genericParamsError}</p>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="flex items-center gap-2 border-t pt-4">
        <label
          htmlFor="batfish-enable-result"
          className="flex h-9 flex-1 items-center gap-2 rounded-md border border-input bg-card px-3 text-xs"
        >
          <input
            id="batfish-enable-result"
            type="checkbox"
            checked={enabled}
            onChange={(event) => onEnabledChange(event.target.checked)}
            className="size-4 rounded border"
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

      {result ? (
        <div className="min-w-0 space-y-2 rounded-md border p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{result.question}</Badge>
            {typeof result.reachable === "boolean" ? (
              <Badge variant={result.reachable ? "secondary" : "destructive"}>
                {result.reachable ? "Reachable" : "Not reachable"}
              </Badge>
            ) : null}
            {result.action ? (
              <Badge variant={result.action === "PERMIT" ? "secondary" : "destructive"}>
                {result.action}
              </Badge>
            ) : null}
            <span className="text-xs text-muted-foreground">
              {result.rows.length} row(s) · network {result.network} · snapshot{" "}
              {result.snapshot}
            </span>
          </div>
          <pre className="max-h-48 min-w-0 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-2 text-xs">
            {JSON.stringify(result.rows, null, 2)}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
