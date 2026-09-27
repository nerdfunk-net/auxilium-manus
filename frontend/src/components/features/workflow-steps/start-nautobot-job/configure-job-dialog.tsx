"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { AttributePathPicker } from "@/components/features/workflow-steps/shared/attribute-path-picker";
import {
  NautobotOptionalFieldRow,
  NautobotRequiredFieldRow,
  type EnabledValueSpec,
} from "@/components/features/workflow-steps/shared/nautobot-field-rows";
import type {
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "@/components/features/workflows/types/workflow-canvas";
import type { NautobotJobSummary } from "@/hooks/queries/use-nautobot-jobs-query";
import { useNautobotJobVariablesQuery } from "@/hooks/queries/use-nautobot-job-variables-query";

import { SelectJobDialog } from "./select-job-dialog";
import {
  EMPTY_PARAMETERS,
  type NautobotJobVariable,
  type StartNautobotJobConfig,
} from "./types";

interface ConfigureJobDialogProps {
  open: boolean;
  value: StartNautobotJobConfig;
  sourceId: string;
  onClose: () => void;
  onChange: (value: StartNautobotJobConfig) => void;
  nodeId: string;
  workflowNodes: PersistedCanvasNode[];
  workflowEdges: WorkflowCanvasEdge[];
}

type PickerTarget = { kind: "required" | "optional"; name: string };

function reconcileRequired(
  previous: Record<string, string>,
  variables: NautobotJobVariable[],
): Record<string, string> {
  const next: Record<string, string> = {};
  for (const variable of variables) {
    if (!variable.required) continue;
    next[variable.name] = previous[variable.name] ?? "";
  }
  return next;
}

function reconcileOptional(
  previous: Record<string, EnabledValueSpec>,
  variables: NautobotJobVariable[],
): Record<string, EnabledValueSpec> {
  const next: Record<string, EnabledValueSpec> = {};
  for (const variable of variables) {
    if (variable.required) continue;
    next[variable.name] = previous[variable.name] ?? { enabled: false, value: "" };
  }
  return next;
}

function ConfigureJobDialogForm({
  value,
  sourceId,
  onClose,
  onChange,
  nodeId,
  workflowNodes,
  workflowEdges,
}: Omit<ConfigureJobDialogProps, "open">) {
  const [jobId, setJobId] = useState(value.job_id ?? "");
  const [jobName, setJobName] = useState(value.job_name ?? "");
  const [schema, setSchema] = useState<NautobotJobVariable[]>(value.job_variables_schema ?? []);
  const [requiredValues, setRequiredValues] = useState<Record<string, string>>(
    value.parameters?.required ?? EMPTY_PARAMETERS.required,
  );
  const [optionalSpecs, setOptionalSpecs] = useState<Record<string, EnabledValueSpec>>(
    value.parameters?.optional ?? EMPTY_PARAMETERS.optional,
  );
  const [taskQueue, setTaskQueue] = useState(value.task_queue ?? "");
  const [selectJobOpen, setSelectJobOpen] = useState(false);
  const [pickerTarget, setPickerTarget] = useState<PickerTarget | null>(null);
  const [loadedVariablesKey, setLoadedVariablesKey] = useState<string | null>(null);

  const variablesQuery = useNautobotJobVariablesQuery({ sourceId, jobId });

  // Reconcile draft parameter values whenever a new job's schema arrives — adjusting state
  // directly during render (rather than in an effect) per
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  const fetchedVariables = variablesQuery.data;
  const variablesKey = fetchedVariables ? `${jobId}:${variablesQuery.dataUpdatedAt}` : null;
  if (fetchedVariables && variablesKey !== loadedVariablesKey) {
    setLoadedVariablesKey(variablesKey);
    setSchema(fetchedVariables);
    setRequiredValues((previous) => reconcileRequired(previous, fetchedVariables));
    setOptionalSpecs((previous) => reconcileOptional(previous, fetchedVariables));
  }

  const requiredVariables = useMemo(() => schema.filter((v) => v.required), [schema]);
  const optionalVariables = useMemo(() => schema.filter((v) => !v.required), [schema]);

  const handleSelectJob = (job: NautobotJobSummary) => {
    setJobId(job.id);
    setJobName(job.name);
  };

  const handleSave = () => {
    onChange({
      ...value,
      job_id: jobId,
      job_name: jobName,
      job_variables_schema: schema,
      parameters: { required: requiredValues, optional: optionalSpecs },
      task_queue: taskQueue.trim() || undefined,
    });
    onClose();
  };

  const handlePickerSelect = (path: string) => {
    if (!pickerTarget) return;
    if (pickerTarget.kind === "required") {
      setRequiredValues((current) => ({ ...current, [pickerTarget.name]: path }));
    } else {
      setOptionalSpecs((current) => ({
        ...current,
        [pickerTarget.name]: { enabled: true, value: path },
      }));
    }
  };

  return (
    <>
      <DialogContent className="flex max-h-[90vh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b step-header px-4 py-3">
          <DialogTitle className="text-base text-step-header-foreground">
            Configure Job
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 overflow-y-auto bg-muted p-4">
          <section className="space-y-1.5">
            <Label className="font-mono text-xs font-medium">job_id</Label>
            {jobId ? (
              <p className="text-xs text-muted-foreground">
                <span className="font-medium text-foreground">{jobName || jobId}</span>
                {variablesQuery.isLoading ? " — loading parameters…" : null}
              </p>
            ) : (
              <p className="text-[11px] text-warning-foreground">No job selected</p>
            )}
            <div className="flex gap-1.5">
              <Button
                className="h-7 flex-1 text-xs"
                size="sm"
                type="button"
                variant="outline"
                disabled={!sourceId}
                onClick={() => setSelectJobOpen(true)}
              >
                {jobId ? "Change Job" : "Select Job"}
              </Button>
              {jobId ? (
                <Button
                  className="h-7 text-xs"
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={() => variablesQuery.refetch()}
                >
                  Refresh parameters
                </Button>
              ) : null}
            </div>
          </section>

          {jobId ? (
            <>
              <section className="space-y-2">
                <span className="text-xs font-medium text-step-muted-foreground">
                  Required parameters
                </span>
                {requiredVariables.length === 0 ? (
                  <p className="text-[11px] text-muted-foreground">
                    This job has no required parameters.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {requiredVariables.map((variable) => (
                      <NautobotRequiredFieldRow
                        key={variable.name}
                        label={variable.name}
                        placeholder="{path} or a literal value"
                        badge={variable.type}
                        value={requiredValues[variable.name] ?? ""}
                        onChange={(v) =>
                          setRequiredValues((current) => ({ ...current, [variable.name]: v }))
                        }
                        onBrowse={() => setPickerTarget({ kind: "required", name: variable.name })}
                      />
                    ))}
                  </div>
                )}
              </section>

              <section className="space-y-2 border-t pt-3">
                <span className="text-xs font-medium text-step-muted-foreground">
                  Optional parameters
                </span>
                {optionalVariables.length === 0 ? (
                  <p className="text-[11px] text-muted-foreground">
                    This job has no optional parameters.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {optionalVariables.map((variable) => (
                      <NautobotOptionalFieldRow
                        key={variable.name}
                        label={variable.name}
                        placeholder="{path} or a literal value"
                        spec={
                          optionalSpecs[variable.name] ?? { enabled: false, value: "" }
                        }
                        onChange={(patch) =>
                          setOptionalSpecs((current) => ({
                            ...current,
                            [variable.name]: {
                              ...(current[variable.name] ?? { enabled: false, value: "" }),
                              ...patch,
                            },
                          }))
                        }
                        onBrowse={() => setPickerTarget({ kind: "optional", name: variable.name })}
                      />
                    ))}
                  </div>
                )}
              </section>
            </>
          ) : null}

          <section className="space-y-1 border-t pt-3">
            <Label className="text-[11px] text-muted-foreground">task_queue (optional)</Label>
            <Input
              className="h-8 font-mono text-xs"
              placeholder="default"
              value={taskQueue}
              onChange={(event) => setTaskQueue(event.target.value)}
            />
          </section>
        </div>

        <DialogFooter className="border-t bg-card px-4 py-3">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            className="bg-step text-step-foreground hover:bg-step-hover"
            type="button"
            disabled={!jobId}
            onClick={handleSave}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>

      <SelectJobDialog
        open={selectJobOpen}
        sourceId={sourceId}
        onClose={() => setSelectJobOpen(false)}
        onSelect={handleSelectJob}
      />

      <AttributePathPicker
        open={pickerTarget !== null}
        onClose={() => setPickerTarget(null)}
        onSelect={handlePickerSelect}
        nodeId={nodeId}
        workflowNodes={workflowNodes}
        workflowEdges={workflowEdges}
      />
    </>
  );
}

export function ConfigureJobDialog({
  open,
  value,
  sourceId,
  onClose,
  onChange,
  nodeId,
  workflowNodes,
  workflowEdges,
}: ConfigureJobDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          onClose();
        }
      }}
    >
      {open ? (
        <ConfigureJobDialogForm
          value={value}
          sourceId={sourceId}
          onClose={onClose}
          onChange={onChange}
          nodeId={nodeId}
          workflowNodes={workflowNodes}
          workflowEdges={workflowEdges}
        />
      ) : null}
    </Dialog>
  );
}
