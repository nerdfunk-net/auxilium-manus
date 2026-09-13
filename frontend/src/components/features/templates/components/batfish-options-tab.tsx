"use client";

import { Play, RefreshCw } from "lucide-react";
import { useCallback } from "react";

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
import { useBatfishSourcesQuery } from "@/hooks/queries/use-batfish-sources-query";

import type { BatfishQueryQuestion, BatfishQueryResult } from "../types";

const QUESTION_OPTIONS: { value: BatfishQueryQuestion; label: string }[] = [
  { value: "routes", label: "Routing Table" },
  { value: "reachability", label: "Path Check" },
  { value: "testFilters", label: "ACL Check" },
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
  question: BatfishQueryQuestion;
  onQuestionChange: (question: BatfishQueryQuestion) => void;
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

  const handleSourceChange = useCallback(
    (value: string) => onTargetConfigChange({ ...targetConfig, batfish_source_id: value }),
    [targetConfig, onTargetConfigChange],
  );

  const handleTargetFieldChange = useCallback(
    (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
      onTargetConfigChange({ ...targetConfig, [key]: event.target.value });
    },
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
            onValueChange={(value) => onQuestionChange(value as BatfishQueryQuestion)}
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
          <Input
            id="batfish-network"
            value={network}
            onChange={handleTargetFieldChange("network")}
            placeholder="e.g. manus-production"
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="batfish-snapshot">Snapshot (Optional)</Label>
          <Input
            id="batfish-snapshot"
            value={snapshot}
            onChange={handleTargetFieldChange("snapshot")}
            placeholder="(most recent)"
          />
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
        <div className="space-y-2 rounded-md border p-3">
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
          <pre className="max-h-48 overflow-auto rounded bg-muted p-2 text-xs">
            {JSON.stringify(result.rows, null, 2)}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
