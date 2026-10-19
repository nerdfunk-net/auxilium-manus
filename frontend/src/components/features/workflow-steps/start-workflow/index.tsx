"use client";

import { useCallback, useEffect, useMemo } from "react";

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
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { ScheduleParameterFields } from "@/components/features/schedules/components/schedule-parameter-fields";
import { useWorkflowQuery } from "@/hooks/queries/use-workflow-query";
import { useWorkflowsQuery } from "@/hooks/queries/use-workflows-query";

import { StartWorkflowHelpPanel } from "./help-panel";
import {
  MAX_MAX_RUNS,
  MAX_POLL_SECONDS,
  MAX_WAIT_SECONDS,
  MIN_MAX_RUNS,
  MIN_POLL_SECONDS,
  MIN_WAIT_SECONDS,
  analyseTarget,
  callerFansOut,
  cleanRunInputs,
  clampNumber,
  missingRequiredInputs,
  startWorkflowFromConfig,
  type RunMode,
} from "./start-workflow-config";

const NO_DEVICES_INPUT = "__none__";

function withoutKeys(
  config: Record<string, unknown>,
  keys: readonly string[],
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(config).filter(([key]) => !keys.includes(key)),
  );
}

function Warning({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] text-warning-foreground">{children}</p>;
}

function StartWorkflowConfigPanel({
  config,
  onChange,
  workflowNodes,
}: PluginConfigPanelProps) {
  const settings = useMemo(() => startWorkflowFromConfig(config), [config]);
  const workflows = useWorkflowsQuery();
  const target = useWorkflowQuery(settings.workflow_id);
  const analysis = useMemo(
    () =>
      analyseTarget(target.data?.canvas_nodes, target.data?.static_attributes),
    [target.data],
  );

  // A freshly selected workflow has no devices_input key yet: once its inputs are known, use its
  // only device input, if it has exactly one. An explicit choice (also "none") is never touched.
  const devicesInputUnset = !("devices_input" in config);
  useEffect(() => {
    if (!target.data || !devicesInputUnset) return;
    onChange({
      ...config,
      devices_input:
        analysis.deviceInputs.length === 1 ? analysis.deviceInputs[0] : "",
    });
  }, [target.data, devicesInputUnset, analysis, config, onChange]);

  const handleWorkflowChange = useCallback(
    (value: string) => {
      const selected = workflows.data?.workflows.find(
        (w) => String(w.id) === value,
      );
      onChange({
        ...withoutKeys(config, ["devices_input", "run_inputs", "run_mode"]),
        workflow_id: Number(value),
        workflow_name: selected?.name ?? "",
      });
    },
    [config, onChange, workflows.data],
  );

  const handleDevicesInputChange = useCallback(
    (value: string) => {
      const devicesInput = value === NO_DEVICES_INPUT ? "" : value;
      onChange({
        ...config,
        devices_input: devicesInput,
        ...(devicesInput ? {} : { run_mode: "all_devices" }),
      });
    },
    [config, onChange],
  );

  const handleRunInputsChange = useCallback(
    (next: Record<string, unknown>) =>
      onChange({ ...config, run_inputs: cleanRunInputs(next) }),
    [config, onChange],
  );

  const declaredNames = useMemo(
    () =>
      new Set((target.data?.static_attributes ?? []).map((attr) => attr.name)),
    [target.data],
  );
  const staleInputs = useMemo(
    () =>
      target.data
        ? Object.keys(settings.run_inputs).filter(
            (name) => !declaredNames.has(name),
          )
        : [],
    [target.data, settings.run_inputs, declaredNames],
  );
  const missingInputs = useMemo(
    () => missingRequiredInputs(analysis.otherAttributes, settings.run_inputs),
    [analysis.otherAttributes, settings.run_inputs],
  );
  const requiredSecrets = useMemo(
    () =>
      (target.data?.static_attributes ?? [])
        .filter((attr) => attr.type === "secret" && attr.required)
        .map((attr) => attr.name),
    [target.data],
  );

  const selectedValue =
    settings.workflow_id === null ? "" : String(settings.workflow_id);
  const selectedKnown = workflows.data?.workflows.some(
    (w) => String(w.id) === selectedValue,
  );
  const devicesInputKnown =
    settings.devices_input === "" ||
    analysis.deviceInputs.includes(settings.devices_input);

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <Label className="text-xs font-medium">Workflow to start</Label>
        <Select value={selectedValue} onValueChange={handleWorkflowChange}>
          <SelectTrigger className="h-8 text-xs" aria-label="Workflow to start">
            <SelectValue
              placeholder={
                workflows.isLoading ? "Loading workflows…" : "Select a workflow"
              }
            />
          </SelectTrigger>
          <SelectContent>
            {(workflows.data?.workflows ?? []).map((workflow) => (
              <SelectItem key={workflow.id} value={String(workflow.id)}>
                {workflow.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {settings.workflow_id === null ? (
          <Warning>No workflow selected</Warning>
        ) : workflows.data && !selectedKnown ? (
          <Warning>
            Workflow {settings.workflow_id}
            {settings.workflow_name ? ` (${settings.workflow_name})` : ""} was
            not found or is not visible to you.
          </Warning>
        ) : null}
      </div>

      {target.data ? (
        <div className="space-y-2 border-t pt-3">
          <Label
            className="text-xs font-medium"
            htmlFor="start-workflow-devices-input"
          >
            Devices of this workflow go into
          </Label>
          <Select
            value={settings.devices_input || NO_DEVICES_INPUT}
            onValueChange={handleDevicesInputChange}
          >
            <SelectTrigger
              id="start-workflow-devices-input"
              className="h-8 font-mono text-xs"
              aria-label="Input that receives the devices"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_DEVICES_INPUT}>
                None (start without devices)
              </SelectItem>
              {analysis.deviceInputs.map((name) => (
                <SelectItem key={name} value={name}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {analysis.deviceInputs.length === 0 ? (
            <p className="text-[11px] text-muted-foreground">
              This workflow has no Get from User step, so it takes no devices
              and is started without any.
            </p>
          ) : (
            <p className="text-[11px] text-muted-foreground">
              One line per device (<span className="font-mono">name,ip,driver</span>),
              the way a schedule or a manual run fills a Get from User input.
            </p>
          )}
          {!devicesInputKnown ? (
            <Warning>
              The input {settings.devices_input} is not read by an enabled Get
              from User step of this workflow any more.
            </Warning>
          ) : null}
          {analysis.deviceInputs.length > 0 && settings.devices_input === "" ? (
            <Warning>
              This workflow expects devices, but none are passed: it would start
              without them.
            </Warning>
          ) : null}

          {settings.devices_input ? (
            <div className="space-y-1.5">
              <Label
                className="text-[11px] text-muted-foreground"
                htmlFor="start-workflow-mode"
              >
                Runs
              </Label>
              <Select
                value={settings.run_mode}
                onValueChange={(value) =>
                  onChange({ ...config, run_mode: value as RunMode })
                }
              >
                <SelectTrigger
                  id="start-workflow-mode"
                  className="h-8 text-xs"
                  aria-label="Runs"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all_devices">
                    One run for all devices
                  </SelectItem>
                  <SelectItem value="per_device">One run per device</SelectItem>
                </SelectContent>
              </Select>
              {settings.run_mode === "per_device" ? (
                <div className="space-y-1">
                  <Label
                    className="text-[11px] text-muted-foreground"
                    htmlFor="start-workflow-max"
                  >
                    max_runs ({MIN_MAX_RUNS} to {MAX_MAX_RUNS})
                  </Label>
                  <Input
                    id="start-workflow-max"
                    className="h-8 font-mono text-xs"
                    type="number"
                    min={MIN_MAX_RUNS}
                    max={MAX_MAX_RUNS}
                    value={settings.max_runs}
                    onChange={(event) =>
                      onChange({
                        ...config,
                        max_runs: clampNumber(
                          event.target.value,
                          MIN_MAX_RUNS,
                          MAX_MAX_RUNS,
                          settings.max_runs,
                        ),
                      })
                    }
                  />
                  <Warning>
                    Starts one run for every device, up to {settings.max_runs}.
                    If more devices arrive, the step stops before it starts any.
                    {callerFansOut(workflowNodes)
                      ? " This workflow fans out, so the step may run in every child and multiply the runs."
                      : ""}
                  </Warning>
                </div>
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  All devices share one run; they pass or fail together.
                </p>
              )}
            </div>
          ) : null}
        </div>
      ) : null}

      {target.data ? (
        <div className="space-y-2 border-t pt-3">
          <Label className="text-xs font-medium">Run inputs</Label>
          {analysis.otherAttributes.length === 0 ? (
            <p className="text-[11px] text-muted-foreground">
              This workflow has no other run inputs.
            </p>
          ) : (
            <ScheduleParameterFields
              attributes={analysis.otherAttributes}
              values={settings.run_inputs}
              onChange={handleRunInputsChange}
            />
          )}
          {missingInputs.length > 0 ? (
            <Warning>
              Required, no default: {missingInputs.join(", ")}. The run cannot
              start without a value.
            </Warning>
          ) : null}
          {staleInputs.length > 0 ? (
            <Warning>
              Not declared by this workflow any more: {staleInputs.join(", ")}.
              The run will be refused.
            </Warning>
          ) : null}
          {analysis.secretNames.length > 0 ? (
            <p className="text-[11px] text-muted-foreground">
              Secret inputs ({analysis.secretNames.join(", ")}) are never passed
              by a step.
            </p>
          ) : null}
          {requiredSecrets.length > 0 ? (
            <Warning>
              Required secret without a default: {requiredSecrets.join(", ")}.
              This workflow cannot be started from here.
            </Warning>
          ) : null}
        </div>
      ) : settings.workflow_id !== null && target.isError ? (
        <Warning>Could not load the selected workflow.</Warning>
      ) : null}

      <div className="space-y-2 border-t pt-3">
        <div className="flex items-center gap-2">
          <Checkbox
            id="start-workflow-wait"
            checked={settings.wait}
            onCheckedChange={(checked) =>
              onChange({ ...config, wait: checked === true })
            }
          />
          <Label htmlFor="start-workflow-wait" className="text-xs">
            Wait for the runs to finish
          </Label>
        </div>

        <div className="space-y-1">
          <Label
            className="text-[11px] text-muted-foreground"
            htmlFor="start-workflow-wait-secs"
          >
            wait_seconds (max {MAX_WAIT_SECONDS})
          </Label>
          <Input
            id="start-workflow-wait-secs"
            className="h-8 font-mono text-xs"
            type="number"
            min={MIN_WAIT_SECONDS}
            max={MAX_WAIT_SECONDS}
            disabled={!settings.wait}
            value={settings.wait_seconds}
            onChange={(event) =>
              onChange({
                ...config,
                wait_seconds: clampNumber(
                  event.target.value,
                  MIN_WAIT_SECONDS,
                  MAX_WAIT_SECONDS,
                  settings.wait_seconds,
                ),
              })
            }
          />
        </div>

        <div className="space-y-1">
          <Label
            className="text-[11px] text-muted-foreground"
            htmlFor="start-workflow-poll"
          >
            poll_interval_seconds
          </Label>
          <Input
            id="start-workflow-poll"
            className="h-8 font-mono text-xs"
            type="number"
            min={MIN_POLL_SECONDS}
            max={MAX_POLL_SECONDS}
            disabled={!settings.wait}
            value={settings.poll_interval_seconds}
            onChange={(event) =>
              onChange({
                ...config,
                poll_interval_seconds: clampNumber(
                  event.target.value,
                  MIN_POLL_SECONDS,
                  MAX_POLL_SECONDS,
                  settings.poll_interval_seconds,
                ),
              })
            }
          />
        </div>

        <div className="flex items-center gap-2">
          <Checkbox
            id="start-workflow-partial"
            checked={settings.allow_partial}
            disabled={!settings.wait}
            onCheckedChange={(checked) =>
              onChange({ ...config, allow_partial: checked === true })
            }
          />
          <Label htmlFor="start-workflow-partial" className="text-xs">
            Accept a partial result as success
          </Label>
        </div>

        <p className="text-[11px] text-muted-foreground">
          {settings.wait
            ? `A device leaves through failure if its run has not finished successfully within ${settings.wait_seconds} s. The run keeps going.`
            : "The runs are only started; the step reports success right away."}
        </p>
      </div>
    </div>
  );
}

export const StartWorkflowPlugin: PluginUIComponent = {
  ConfigPanel: StartWorkflowConfigPanel,
  HelpPanel: StartWorkflowHelpPanel,
};
