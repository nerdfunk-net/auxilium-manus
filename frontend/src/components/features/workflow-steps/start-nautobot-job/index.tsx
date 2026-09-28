"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";

import {
  NAUTOBOT_SOURCE_ID_KEY,
  isNautobotSourceConfigured,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import { ConfigureJobDialog } from "./configure-job-dialog";
import { StartNautobotJobHelpPanel } from "./help-panel";
import type { StartNautobotJobConfig } from "./types";

const DEFAULT_BAG_NAME = "nautobot_job";

function countParameters(config: StartNautobotJobConfig): { required: number; optional: number } {
  const required = Object.keys(config.parameters?.required ?? {}).length;
  const optional = Object.values(config.parameters?.optional ?? {}).filter(
    (spec) => spec.enabled,
  ).length;
  return { required, optional };
}

function StartNautobotJobConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes,
  workflowEdges,
}: PluginConfigPanelProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });
  const jobConfig = config as StartNautobotJobConfig;

  const [sourceOpen, setSourceOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);

  const isSourceConfigured = isNautobotSourceConfigured(config);
  const { required, optional } = countParameters(jobConfig);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [NAUTOBOT_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleDialogSave = useCallback(
    (next: StartNautobotJobConfig) => {
      onChange({ ...config, ...next });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{NAUTOBOT_SOURCE_ID_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            nautobot
          </Badge>
        </div>

        {isSourceConfigured ? (
          <p className="font-mono text-[11px] text-muted-foreground">
            {sourceId}
            {credentials.isReady ? (
              <span className="block truncate font-sans text-muted-foreground">
                {credentials.url}
              </span>
            ) : credentials.isLoading ? (
              <span className="block font-sans">Loading credentials…</span>
            ) : (
              <span className="block font-sans text-warning-foreground">
                Source not found in settings
              </span>
            )}
          </p>
        ) : (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
        )}

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setSourceOpen(true)}
        >
          {isSourceConfigured ? "Edit Source" : "Configure Source"}
        </Button>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">job_id</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            job
          </Badge>
        </div>

        {jobConfig.job_id ? (
          <p className="text-[11px] text-muted-foreground">
            <span className="block truncate font-medium text-foreground">
              {jobConfig.job_name || jobConfig.job_id}
            </span>
            {required} required · {optional} optional configured
          </p>
        ) : (
          <p className="text-[11px] text-warning-foreground">No job selected</p>
        )}

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          disabled={!isSourceConfigured}
          onClick={() => setDialogOpen(true)}
        >
          Configure Job
        </Button>
      </div>

      <div className="space-y-1 border-t pt-3">
        <Label className="text-[11px] text-muted-foreground">bag_name</Label>
        <Input
          className="h-8 font-mono text-xs"
          placeholder={DEFAULT_BAG_NAME}
          value={jobConfig.bag_name ?? ""}
          onChange={(event) => onChange({ ...config, bag_name: event.target.value })}
        />
        <p className="text-[11px] text-muted-foreground">
          attribute_bags key this job&apos;s result is stored under. Give paired
          start/check-nautobot-job nodes a unique name to run more than one job per
          device (e.g. &quot;onboard_job&quot;, &quot;update_job&quot;).
        </p>
      </div>

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />

      <ConfigureJobDialog
        open={dialogOpen}
        value={jobConfig}
        sourceId={sourceId}
        onClose={() => setDialogOpen(false)}
        onChange={handleDialogSave}
        nodeId={nodeId}
        workflowNodes={workflowNodes ?? []}
        workflowEdges={workflowEdges ?? []}
      />
    </div>
  );
}

export const StartNautobotJobPlugin: PluginUIComponent = {
  ConfigPanel: StartNautobotJobConfigPanel,
  HelpPanel: StartNautobotJobHelpPanel,
};
