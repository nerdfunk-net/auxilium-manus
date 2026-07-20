"use client";

import { useCallback, useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { listUpstreamSourceSteps } from "@/components/features/workflow-steps/store-artifact/upstream-source-steps";

import {
  buildRouteOnContentConfig,
  CONTENT_SOURCE_OPTIONS,
  contentSourceRequiresStepNodeId,
  MATCH_MODE_OPTIONS,
  parseRouteOnContentConfig,
} from "./config";
import { RouteOnContentHelpPanel } from "./help-panel";

function RouteOnContentConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes = [],
}: PluginConfigPanelProps) {
  const parsed = useMemo(() => parseRouteOnContentConfig(config), [config]);

  const needsStepNodeId = contentSourceRequiresStepNodeId(parsed.content_source);
  const needsParsedOutputKey = parsed.content_source === "rendered_template";

  const sourceSteps = useMemo(
    () => listUpstreamSourceSteps(workflowNodes, parsed.content_source, nodeId),
    [workflowNodes, parsed.content_source, nodeId],
  );

  const contentSourceHint = useMemo(
    () => CONTENT_SOURCE_OPTIONS.find((option) => option.value === parsed.content_source)?.hint,
    [parsed.content_source],
  );
  const matchModeHint = useMemo(
    () => MATCH_MODE_OPTIONS.find((option) => option.value === parsed.match_mode)?.hint,
    [parsed.match_mode],
  );

  const handleContentSourceChange = useCallback(
    (value: string) => {
      onChange(buildRouteOnContentConfig(config, { content_source: value }));
    },
    [config, onChange],
  );

  const handleSourceStepNodeIdChange = useCallback(
    (value: string) => {
      onChange(buildRouteOnContentConfig(config, { source_step_node_id: value }));
    },
    [config, onChange],
  );

  const handleParsedOutputKeyChange = useCallback(
    (value: string) => {
      onChange(buildRouteOnContentConfig(config, { parsed_output_key: value }));
    },
    [config, onChange],
  );

  const handleMatchModeChange = useCallback(
    (value: string) => {
      onChange(buildRouteOnContentConfig(config, { match_mode: value }));
    },
    [config, onChange],
  );

  const handlePatternChange = useCallback(
    (value: string) => {
      onChange(buildRouteOnContentConfig(config, { pattern: value }));
    },
    [config, onChange],
  );

  const handleCaseSensitiveChange = useCallback(
    (checked: boolean) => {
      onChange(buildRouteOnContentConfig(config, { case_sensitive: checked }));
    },
    [config, onChange],
  );

  const handleMultilineChange = useCallback(
    (checked: boolean) => {
      onChange(buildRouteOnContentConfig(config, { multiline: checked }));
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">content_source</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={parsed.content_source} onValueChange={handleContentSourceChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CONTENT_SOURCE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {contentSourceHint ? (
          <p className="text-[11px] text-muted-foreground">{contentSourceHint}</p>
        ) : null}
      </div>

      {needsStepNodeId ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">source_step_node_id</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              step
            </Badge>
          </div>
          {sourceSteps.length > 0 ? (
            <Select
              value={parsed.source_step_node_id || undefined}
              onValueChange={handleSourceStepNodeIdChange}
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue placeholder="Choose upstream step…" />
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
            <p className="text-[11px] text-amber-600">
              Add an upstream step that produces this content source first.
            </p>
          )}
          <Input
            value={parsed.source_step_node_id}
            onChange={(event) => handleSourceStepNodeIdChange(event.target.value)}
            placeholder="run-command-3"
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
            value={parsed.parsed_output_key}
            onChange={(event) => handleParsedOutputKeyChange(event.target.value)}
            placeholder="device_config"
            className="h-8 font-mono text-xs"
          />
        </div>
      ) : null}

      <div className="space-y-1.5 border-t pt-3">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">match_mode</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={parsed.match_mode} onValueChange={handleMatchModeChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {MATCH_MODE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {matchModeHint ? (
          <p className="text-[11px] text-muted-foreground">{matchModeHint}</p>
        ) : null}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">pattern</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={parsed.pattern}
          onChange={(event) => handlePatternChange(event.target.value)}
          placeholder={
            parsed.match_mode === "regex" ? "^tacacs-server" : "tacacs-server|tacacs server"
          }
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          {parsed.match_mode === "fixed_text"
            ? "Literal text to search for."
            : "Regular expression to search for."}{" "}
          Supports <span className="font-mono">{"{path.to.attribute}"}</span> placeholders
          resolved per device (e.g. <span className="font-mono">{"{nautobot.tacacs_ip}"}</span>
          ). In regex mode, resolved placeholder values are regex-escaped before being spliced
          into the pattern.
        </p>
      </div>

      <div className="flex items-start gap-2">
        <input
          id={`case-sensitive-${nodeId}`}
          type="checkbox"
          checked={parsed.case_sensitive}
          onChange={(event) => handleCaseSensitiveChange(event.target.checked)}
          className="mt-0.5 size-4 rounded border"
        />
        <div className="space-y-0.5">
          <Label htmlFor={`case-sensitive-${nodeId}`} className="font-mono text-xs font-medium">
            case_sensitive
          </Label>
          <p className="text-[11px] text-muted-foreground">
            When disabled, matching ignores letter case.
          </p>
        </div>
      </div>

      {parsed.match_mode === "regex" ? (
        <div className="flex items-start gap-2">
          <input
            id={`multiline-${nodeId}`}
            type="checkbox"
            checked={parsed.multiline}
            onChange={(event) => handleMultilineChange(event.target.checked)}
            className="mt-0.5 size-4 rounded border"
          />
          <div className="space-y-0.5">
            <Label htmlFor={`multiline-${nodeId}`} className="font-mono text-xs font-medium">
              multiline
            </Label>
            <p className="text-[11px] text-muted-foreground">
              When enabled, <span className="font-mono">^</span> and{" "}
              <span className="font-mono">$</span> match at line boundaries within the
              content instead of only the start/end of the whole text.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export const RouteOnContentPlugin: PluginUIComponent = {
  ConfigPanel: RouteOnContentConfigPanel,
  HelpPanel: RouteOnContentHelpPanel,
};
