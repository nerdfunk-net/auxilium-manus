"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { AgentStatusPanel } from "@/components/features/settings/components/agent-status-panel";
import { AttributePathPicker } from "@/components/features/workflow-steps/shared/attribute-path-picker";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
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
import { Textarea } from "@/components/ui/textarea";
import { useAgentSourcesQuery } from "@/hooks/queries/use-agent-sources-query";
import { isForbiddenError } from "@/hooks/use-api";

import { CheckboxField } from "../shared/checkbox-field";
import {
  buildRouteToAgentConfig,
  configProblems,
  formatLines,
  parseLines,
  parseParamsText,
  parseRouteToAgentConfig,
  TIMEOUT_RANGE,
  type RouteToAgentConfig,
} from "./config";
import { ContentInputsField } from "./content-inputs-field";
import { RouteToAgentHelpPanel } from "./help-panel";

const EMPTY_NODES: NonNullable<PluginConfigPanelProps["workflowNodes"]> = [];
const EMPTY_EDGES: NonNullable<PluginConfigPanelProps["workflowEdges"]> = [];

function initialParamsText(params: Record<string, unknown>): string {
  return Object.keys(params).length > 0 ? JSON.stringify(params, null, 2) : "";
}

function RouteToAgentConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes = EMPTY_NODES,
  workflowEdges = EMPTY_EDGES,
}: PluginConfigPanelProps) {
  const router = useRouter();
  const parsed = useMemo(() => parseRouteToAgentConfig(config), [config]);
  const {
    data: agentData,
    isLoading: agentsLoading,
    error: agentsError,
  } = useAgentSourcesQuery();
  const agents = agentData?.sources ?? [];
  const agentsForbidden = isForbiddenError(agentsError);

  const [pickerOpen, setPickerOpen] = useState(false);
  const [paramsText, setParamsText] = useState(() => initialParamsText(parsed.params));
  const [paramsError, setParamsError] = useState<string | null>(null);
  const [inputPathsText, setInputPathsText] = useState(() => formatLines(parsed.input_paths));
  const [outputKeysText, setOutputKeysText] = useState(() => formatLines(parsed.output_keys));

  const patch = useCallback(
    (next: Partial<RouteToAgentConfig>) => onChange(buildRouteToAgentConfig(config, next)),
    [config, onChange],
  );

  const handleParams = useCallback(
    (text: string) => {
      setParamsText(text);
      const result = parseParamsText(text);
      if (result.ok) {
        setParamsError(null);
        patch({ params: result.value });
      } else {
        setParamsError(result.error);
      }
    },
    [patch],
  );

  const handleInputPaths = useCallback(
    (text: string) => {
      setInputPathsText(text);
      patch({ input_paths: parseLines(text) });
    },
    [patch],
  );

  const handleOutputKeys = useCallback(
    (text: string) => {
      setOutputKeysText(text);
      patch({ output_keys: parseLines(text) });
    },
    [patch],
  );

  const addPickedPath = useCallback(
    (path: string) => {
      const next = parseLines(`${inputPathsText}\n${path}`);
      setInputPathsText(formatLines(next));
      patch({ input_paths: next });
    },
    [inputPathsText, patch],
  );

  const problems = useMemo(() => configProblems(parsed), [parsed]);
  const resultPaths = useMemo(
    () =>
      parsed.destination_path && parsed.output_keys.length > 0
        ? parsed.output_keys.map((key) => `${parsed.destination_path}.${key}`)
        : [],
    [parsed.destination_path, parsed.output_keys],
  );
  const agentKnown = agents.some((agent) => agent.source_id === parsed.agent_source_id);

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="route-to-agent-source">
          agent_source_id
        </Label>
        {agentsLoading ? (
          <p className="text-[11px] text-muted-foreground">Loading agents…</p>
        ) : agentsError ? (
          // A failed request is not an empty list: say why the agents cannot be shown, and keep
          // the saved choice visible so the step is not mistaken for unconfigured.
          <div className="rounded-md border border-dashed bg-muted/40 p-2 text-[11px] text-muted-foreground">
            {agentsForbidden ? (
              <p>
                You don&apos;t have permission to list agents. Ask an administrator for the{" "}
                <span className="font-mono">sources.agent:read</span> permission.
              </p>
            ) : (
              <p>The list of agents could not be loaded. Try again or reload the page.</p>
            )}
            {parsed.agent_source_id ? (
              <p className="mt-1">
                Saved agent: <span className="font-mono">{parsed.agent_source_id}</span>
              </p>
            ) : null}
          </div>
        ) : agents.length === 0 ? (
          <div className="rounded-md border border-dashed bg-muted/40 p-2 text-[11px] text-muted-foreground">
            <p>No agents configured yet.</p>
            <Button
              className="mt-2 h-7 text-xs"
              size="sm"
              type="button"
              variant="outline"
              onClick={() => router.push("/settings/sources")}
            >
              Open Settings → Sources
            </Button>
          </div>
        ) : (
          <Select
            value={parsed.agent_source_id}
            onValueChange={(value) => patch({ agent_source_id: value })}
          >
            <SelectTrigger id="route-to-agent-source" className="h-8 text-xs">
              <SelectValue placeholder="Select an agent" />
            </SelectTrigger>
            <SelectContent>
              {agents.map((agent) => (
                <SelectItem key={agent.source_id} value={agent.source_id}>
                  <span className="font-mono">{agent.source_id}</span>
                  <span className="ml-2 text-muted-foreground">— {agent.transport}</span>
                </SelectItem>
              ))}
              {parsed.agent_source_id && !agentKnown ? (
                <SelectItem value={parsed.agent_source_id}>
                  {parsed.agent_source_id} (not found)
                </SelectItem>
              ) : null}
            </SelectContent>
          </Select>
        )}
        {agentKnown && !agentsError ? <AgentStatusPanel sourceId={parsed.agent_source_id} enabled /> : null}
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="route-to-agent-handler">
          handler
        </Label>
        <Input
          id="route-to-agent-handler"
          className="h-8 font-mono text-xs"
          placeholder="resolve_location"
          value={parsed.handler}
          onChange={(event) => patch({ handler: event.target.value })}
        />
        <p className="text-[11px] text-muted-foreground">
          Name of the function the agent runs. The app sends data, never code.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="route-to-agent-params">
          params
        </Label>
        <Textarea
          id="route-to-agent-params"
          className="min-h-16 font-mono text-xs"
          placeholder={'{"strict": true}'}
          value={paramsText}
          onChange={(event) => handleParams(event.target.value)}
        />
        {paramsError ? (
          <p className="text-[11px] text-destructive">{paramsError}</p>
        ) : (
          <p className="text-[11px] text-muted-foreground">
            Optional static JSON object for the handler (same for every device; no secrets).
          </p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="route-to-agent-inputs">
          input_paths
        </Label>
        <div className="flex items-start gap-1.5">
          <Textarea
            id="route-to-agent-inputs"
            className="min-h-16 font-mono text-xs"
            placeholder={"nautobot.location.name\nparsed.cisco_config.running.hostname"}
            value={inputPathsText}
            onChange={(event) => handleInputPaths(event.target.value)}
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8 shrink-0"
            onClick={() => setPickerOpen(true)}
            title="Browse attributes"
          >
            <Search className="size-3.5" />
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          One attribute path per line. Only these values are sent; sealed secrets fail the device.
        </p>
        <AttributePathPicker
          open={pickerOpen}
          onClose={() => setPickerOpen(false)}
          onSelect={addPickedPath}
          nodeId={nodeId}
          workflowNodes={workflowNodes}
          workflowEdges={workflowEdges}
        />
      </div>

      <ContentInputsField
        nodeId={nodeId}
        selected={parsed.content_inputs}
        workflowNodes={workflowNodes}
        onChange={(next) => patch({ content_inputs: next })}
      />

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="route-to-agent-destination">
          destination_path
        </Label>
        <Input
          id="route-to-agent-destination"
          className="h-8 font-mono text-xs"
          placeholder="agent.geo"
          value={parsed.destination_path}
          onChange={(event) => patch({ destination_path: event.target.value })}
        />
        <p className="text-[11px] text-muted-foreground">
          Where the answer is written (<span className="font-mono">bag.field</span>).
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="route-to-agent-outputs">
          output_keys
        </Label>
        <Textarea
          id="route-to-agent-outputs"
          className="min-h-12 font-mono text-xs"
          placeholder="location"
          value={outputKeysText}
          onChange={(event) => handleOutputKeys(event.target.value)}
        />
        {resultPaths.length > 0 ? (
          <p className="text-[11px] text-muted-foreground">
            Available afterwards as{" "}
            <span className="font-mono">{resultPaths.join(", ")}</span>. Any other key the agent
            returns fails the device.
          </p>
        ) : (
          <p className="text-[11px] text-muted-foreground">
            One key per line: the only keys the agent may return.
          </p>
        )}
      </div>

      <CheckboxField
        id="route-to-agent-allow-missing"
        label="allow_missing_outputs"
        checked={parsed.allow_missing_outputs}
        onCheckedChange={(checked) => patch({ allow_missing_outputs: checked })}
        description="Accept an answer that leaves out some of the declared keys."
      />

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="route-to-agent-timeout">
          timeout_seconds
        </Label>
        <Input
          id="route-to-agent-timeout"
          type="number"
          className="h-8 w-28 text-xs"
          min={TIMEOUT_RANGE.min}
          max={TIMEOUT_RANGE.max}
          value={parsed.timeout_seconds}
          onChange={(event) => patch({ timeout_seconds: Number(event.target.value) })}
        />
      </div>

      {problems.length > 0 ? (
        <ul
          className="list-disc space-y-0.5 rounded-md border border-dashed bg-muted/40 py-2 pl-6 pr-2 text-[11px] text-muted-foreground"
          aria-label="Configuration problems"
        >
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export const RouteToAgentPlugin: PluginUIComponent = {
  ConfigPanel: RouteToAgentConfigPanel,
  HelpPanel: RouteToAgentHelpPanel,
};
