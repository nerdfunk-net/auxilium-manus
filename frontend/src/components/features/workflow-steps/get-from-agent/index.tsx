"use client";

import { Minus, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useMemo } from "react";

import { AgentStatusPanel } from "@/components/features/settings/components/agent-status-panel";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
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
import { useAgentSourcesQuery } from "@/hooks/queries/use-agent-sources-query";
import { isForbiddenError } from "@/hooks/use-api";

import { FanOutConfigSection, type FanOutConfig } from "../shared/fan-out-config";
import {
  buildGetFromAgentConfig,
  configProblems,
  emptyAttribute,
  parseGetFromAgentConfig,
  TIMEOUT_RANGE,
  type AgentAttribute,
  type GetFromAgentConfig,
} from "./config";
import { GetFromAgentHelpPanel } from "./help-panel";

function GetFromAgentConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const router = useRouter();
  const parsed = useMemo(() => parseGetFromAgentConfig(config), [config]);
  const {
    data: agentData,
    isLoading: agentsLoading,
    error: agentsError,
  } = useAgentSourcesQuery();
  const agents = agentData?.sources ?? [];
  const agentsForbidden = isForbiddenError(agentsError);
  const agentKnown = agents.some((agent) => agent.source_id === parsed.agent_source_id);
  const problems = useMemo(() => configProblems(parsed), [parsed]);

  const patch = useCallback(
    (next: Partial<GetFromAgentConfig>) => onChange(buildGetFromAgentConfig(config, next)),
    [config, onChange],
  );

  const handleAttributeChange = useCallback(
    (index: number, field: keyof AgentAttribute, value: string) =>
      patch({
        attributes: parsed.attributes.map((row, rowIndex) =>
          rowIndex === index ? { ...row, [field]: value } : row,
        ),
      }),
    [parsed.attributes, patch],
  );

  const handleAddAttribute = useCallback(
    () => patch({ attributes: [...parsed.attributes, emptyAttribute()] }),
    [parsed.attributes, patch],
  );

  const handleRemoveAttribute = useCallback(
    (index: number) =>
      patch({ attributes: parsed.attributes.filter((_, rowIndex) => rowIndex !== index) }),
    [parsed.attributes, patch],
  );

  const handleFanOutChange = useCallback(
    (next: Partial<FanOutConfig>) => patch({ fan_out: { ...parsed.fan_out, ...next } }),
    [parsed.fan_out, patch],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="get-from-agent-source">
          agent_source_id
        </Label>
        {agentsLoading ? (
          <p className="text-[11px] text-muted-foreground">Loading agents…</p>
        ) : agentsError ? (
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
            <SelectTrigger id="get-from-agent-source" className="h-8 text-xs">
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
        {agentKnown && !agentsError ? (
          <AgentStatusPanel sourceId={parsed.agent_source_id} enabled />
        ) : null}
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="get-from-agent-handler">
          handler
        </Label>
        <Input
          id="get-from-agent-handler"
          className="h-8 font-mono text-xs"
          placeholder="list_devices"
          value={parsed.handler}
          onChange={(event) => patch({ handler: event.target.value })}
        />
        <p className="text-[11px] text-muted-foreground">
          Name of the function the agent runs. It returns the device list.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">attributes</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              object_list
            </Badge>
          </div>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-7"
            onClick={handleAddAttribute}
            title="Add attribute"
          >
            <Plus className="size-3.5" aria-hidden />
          </Button>
        </div>
        {parsed.attributes.length === 0 ? (
          <p className="text-[11px] text-muted-foreground">
            No attributes: the agent gets an empty request.
          </p>
        ) : null}
        <div className="space-y-2">
          {parsed.attributes.map((row, index) => (
            <div
              key={`attribute-${index}`}
              className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-2"
            >
              <Input
                value={row.name}
                onChange={(event) => handleAttributeChange(index, "name", event.target.value)}
                placeholder="site"
                aria-label={`Attribute ${index + 1} name`}
                className="h-8 min-w-0 font-mono text-xs"
              />
              <Input
                value={row.value}
                onChange={(event) => handleAttributeChange(index, "value", event.target.value)}
                placeholder="berlin or {run_input.site}"
                aria-label={`Attribute ${index + 1} value`}
                className="h-8 min-w-0 font-mono text-xs"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="size-8 shrink-0"
                onClick={() => handleRemoveAttribute(index)}
                title="Remove attribute"
              >
                <Minus className="size-3.5" aria-hidden />
              </Button>
            </div>
          ))}
        </div>
        <p className="text-[11px] text-muted-foreground">
          Sent to the agent as name/value pairs. A value is fixed text or a run input such as{" "}
          <span className="font-mono">{"{run_input.site}"}</span>. Never put secrets here.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="get-from-agent-timeout">
          timeout_seconds
        </Label>
        <Input
          id="get-from-agent-timeout"
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

      <FanOutConfigSection value={parsed.fan_out} onChange={handleFanOutChange} />
    </div>
  );
}

export const GetFromAgentPlugin: PluginUIComponent = {
  ConfigPanel: GetFromAgentConfigPanel,
  HelpPanel: GetFromAgentHelpPanel,
};
