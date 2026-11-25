"use client";

import { useCallback, useMemo, useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";

import { AttributePathPicker } from "../shared/attribute-path-picker";
import { NautobotRequiredFieldRow } from "../shared/nautobot-field-rows";
import {
  NAUTOBOT_SOURCE_ID_KEY,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import { CheckNautobotJobHelpPanel } from "./help-panel";
import { NautobotSourceStatus, SourceRow } from "../shared/source-row";

const MAX_TOTAL_WAIT_SECONDS = 600;
const DEFAULT_JOB_UUID = "{nautobot_job.job_result_id}";
const DEFAULT_BAG_NAME = "nautobot_job";

interface CheckNautobotJobConfig {
  nautobot_source_id?: string;
  job_uuid?: string;
  max_checks?: number;
  interval_seconds?: number;
  bag_name?: string;
}

function CheckNautobotJobConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes,
  workflowEdges,
}: PluginConfigPanelProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });
  const jobConfig = config as CheckNautobotJobConfig;

  const [sourceOpen, setSourceOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  const jobUuid = jobConfig.job_uuid ?? DEFAULT_JOB_UUID;
  const maxChecks = jobConfig.max_checks ?? 10;
  const intervalSeconds = jobConfig.interval_seconds ?? 5;
  const worstCaseWait = maxChecks * intervalSeconds;

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [NAUTOBOT_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handlePickerSelect = useCallback(
    (path: string) => {
      onChange({ ...config, job_uuid: `{${path}}` });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <SourceRow
        label={NAUTOBOT_SOURCE_ID_KEY}
        badge="nautobot"
        sourceId={sourceId}
        onOpen={() => setSourceOpen(true)}
        status={
          <NautobotSourceStatus
            isReady={credentials.isReady}
            isLoading={credentials.isLoading}
            url={credentials.url}
          />
        }
      />

      <NautobotRequiredFieldRow
        label="job_uuid"
        placeholder={DEFAULT_JOB_UUID}
        value={jobUuid}
        onChange={(value) => onChange({ ...config, job_uuid: value })}
        onBrowse={() => setPickerOpen(true)}
      />

      <div className="space-y-2 border-t pt-3">
        <div className="space-y-1">
          <Label className="text-[11px] text-muted-foreground">max_checks</Label>
          <Input
            className="h-8 font-mono text-xs"
            type="number"
            min={1}
            value={maxChecks}
            onChange={(event) =>
              onChange({ ...config, max_checks: Number(event.target.value) || 1 })
            }
          />
        </div>
        <div className="space-y-1">
          <Label className="text-[11px] text-muted-foreground">interval_seconds</Label>
          <Input
            className="h-8 font-mono text-xs"
            type="number"
            min={0}
            value={intervalSeconds}
            onChange={(event) =>
              onChange({ ...config, interval_seconds: Number(event.target.value) || 0 })
            }
          />
        </div>
        <p
          className={
            worstCaseWait > MAX_TOTAL_WAIT_SECONDS
              ? "text-[11px] text-warning-foreground"
              : "text-[11px] text-muted-foreground"
          }
        >
          Worst case wait: {worstCaseWait}s
          {worstCaseWait > MAX_TOTAL_WAIT_SECONDS
            ? ` — exceeds the ${MAX_TOTAL_WAIT_SECONDS}s ceiling, run will fail to start`
            : null}
        </p>
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
          attribute_bags key this check&apos;s status is merged into. Must match the
          bag_name on the start-nautobot-job node whose job_uuid this reads (e.g.
          &quot;onboard_job&quot;, &quot;update_job&quot;) when running more than one
          job per device.
        </p>
      </div>

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />

      <AttributePathPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onSelect={handlePickerSelect}
        nodeId={nodeId}
        workflowNodes={workflowNodes ?? []}
        workflowEdges={workflowEdges ?? []}
      />
    </div>
  );
}

export const CheckNautobotJobPlugin: PluginUIComponent = {
  ConfigPanel: CheckNautobotJobConfigPanel,
  HelpPanel: CheckNautobotJobHelpPanel,
};
