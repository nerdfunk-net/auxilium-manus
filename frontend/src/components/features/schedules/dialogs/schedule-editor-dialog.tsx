"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { useToast } from "@/hooks/use-toast";
import { useWorkflowsQuery } from "@/hooks/queries/use-workflows-query";
import { useWorkflowQuery } from "@/hooks/queries/use-workflow-query";
import { buildCronExpression } from "@/components/features/workflows/utils/schedule-cron";

import { ScheduleParameterFields } from "../components/schedule-parameter-fields";
import {
  DEFAULT_TIMING,
  ScheduleTimingFields,
  describeTimingRun,
  timingFromSchedule,
  useUtcClock,
  type TimingValue,
} from "../components/schedule-timing-fields";
import { useScheduleMutations } from "../hooks/use-schedule-mutations";
import type {
  WorkflowSchedule,
  WorkflowScheduleCreate,
  WorkflowScheduleUpdate,
} from "../types/schedule";

interface ScheduleEditorDialogProps {
  onOpenChange: (open: boolean) => void;
  /** When set, the dialog edits this schedule; otherwise it creates a new one.
   * The parent mounts this component fresh per open (via a `key`), so all state
   * below is seeded once from these props — no reset effect needed. */
  schedule?: WorkflowSchedule | null;
}

export function ScheduleEditorDialog({ onOpenChange, schedule }: ScheduleEditorDialogProps) {
  const isEdit = schedule != null;
  const { toast } = useToast();
  const { createSchedule, updateSchedule } = useScheduleMutations();

  const workflowsQuery = useWorkflowsQuery();
  const [workflowId, setWorkflowId] = useState<number | null>(
    schedule?.workflow_id ?? null,
  );
  const workflowQuery = useWorkflowQuery(workflowId);
  const staticAttributes = useMemo(
    () => workflowQuery.data?.static_attributes ?? [],
    [workflowQuery.data],
  );

  const [name, setName] = useState(schedule?.name ?? "");
  const [enabled, setEnabled] = useState(schedule?.enabled ?? true);
  const [timing, setTiming] = useState<TimingValue>(() =>
    schedule
      ? timingFromSchedule(
          schedule.schedule_type,
          schedule.cron_expression,
          schedule.run_at,
        )
      : DEFAULT_TIMING,
  );
  const [paramValues, setParamValues] = useState<Record<string, unknown>>(
    schedule?.run_inputs ?? {},
  );
  const [concurrencyLimit, setConcurrencyLimit] = useState(
    schedule?.concurrency_limit != null ? String(schedule.concurrency_limit) : "1",
  );

  const pending = createSchedule.isPending || updateSchedule.isPending;

  const buildTimingPayload = ():
    | { schedule_type: "cron"; cron_expression: string; run_at: null }
    | { schedule_type: "once"; cron_expression: null; run_at: string }
    | null => {
    if (timing.schedule_type === "once") {
      if (!timing.runAt) {
        toast({ description: "Pick a date and time.", variant: "destructive" });
        return null;
      }
      return {
        schedule_type: "once",
        cron_expression: null,
        run_at: `${timing.runAt}:00Z`,
      };
    }
    const cron = buildCronExpression(timing);
    if (!cron) {
      toast({ description: "Enter a cron expression.", variant: "destructive" });
      return null;
    }
    return { schedule_type: "cron", cron_expression: cron, run_at: null };
  };

  const handleSubmit = () => {
    if (!isEdit && workflowId == null) {
      toast({ description: "Select a workflow.", variant: "destructive" });
      return;
    }
    const timingPayload = buildTimingPayload();
    if (!timingPayload) return;

    const limit = Number(concurrencyLimit);
    const concurrency_limit = Number.isFinite(limit) && limit >= 1 ? limit : 1;

    if (isEdit && schedule) {
      const data: WorkflowScheduleUpdate = {
        name: name.trim() || null,
        enabled,
        run_inputs: paramValues,
        concurrency_limit,
        ...timingPayload,
      };
      updateSchedule.mutate(
        { id: schedule.id, data },
        { onSuccess: () => onOpenChange(false) },
      );
      return;
    }

    const data: WorkflowScheduleCreate = {
      workflow_id: workflowId as number,
      name: name.trim() || null,
      enabled,
      run_inputs: paramValues,
      concurrency_limit,
      ...timingPayload,
    };
    createSchedule.mutate(data, { onSuccess: () => onOpenChange(false) });
  };

  const utcClock = useUtcClock();
  const runSummary = describeTimingRun(timing);
  const sectionLabel =
    "text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground";

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[88vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl">
        <DialogHeader className="border-b px-6 py-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <DialogTitle>{isEdit ? "Edit schedule" : "New schedule"}</DialogTitle>
              <DialogDescription>
                Run a workflow on a timer with its own inventory and credentials. The
                workflow is published to the background tier so overlapping runs are
                serialised.
              </DialogDescription>
            </div>
            <div className="shrink-0 rounded-md border bg-muted/40 px-3 py-1.5 text-right">
              <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                Now (UTC)
              </p>
              <p className="font-mono text-sm text-foreground">{utcClock}</p>
            </div>
          </div>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-1">
              <Label className="text-xs">Workflow</Label>
              <Select
                value={workflowId != null ? String(workflowId) : ""}
                onValueChange={(v) => setWorkflowId(Number(v))}
                disabled={isEdit}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select a workflow" />
                </SelectTrigger>
                <SelectContent>
                  {(workflowsQuery.data?.workflows ?? []).map((wf) => (
                    <SelectItem key={wf.id} value={String(wf.id)}>
                      {wf.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1">
              <Label className="text-xs" htmlFor="schedule-name">
                Name
              </Label>
              <Input
                id="schedule-name"
                placeholder="e.g. Site A nightly"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
          </div>

          <div className="mt-5 grid gap-6 sm:grid-cols-2">
            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label className={sectionLabel}>Timer</Label>
                <ScheduleTimingFields value={timing} onChange={setTiming} />
              </div>

              <div className="rounded-md border bg-muted/30 px-3 py-2">
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Runs
                </p>
                <p className="text-[13px] text-foreground">{runSummary.utc}</p>
                {runSummary.local ? (
                  <p className="text-[11.5px] text-muted-foreground">{runSummary.local}</p>
                ) : null}
              </div>

              <div className="grid gap-1">
                <Label className="text-xs" htmlFor="schedule-concurrency">
                  Concurrency limit
                </Label>
                <Input
                  id="schedule-concurrency"
                  type="number"
                  min={1}
                  value={concurrencyLimit}
                  onChange={(e) => setConcurrencyLimit(e.target.value)}
                />
                <p className="text-[11px] text-muted-foreground">
                  Maximum overlapping runs of this workflow. 1 = a new run waits for the
                  previous one to finish.
                </p>
              </div>

              <div className="flex items-center justify-between gap-2 rounded-md border px-3 py-2">
                <Label className="text-xs" htmlFor="schedule-enabled">
                  Enabled
                </Label>
                <Switch id="schedule-enabled" checked={enabled} onCheckedChange={setEnabled} />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label className={sectionLabel}>Parameters</Label>
              {workflowId == null ? (
                <p className="text-[12px] text-muted-foreground">
                  Select a workflow to see its run parameters.
                </p>
              ) : (
                <ScheduleParameterFields
                  attributes={staticAttributes}
                  values={paramValues}
                  onChange={setParamValues}
                />
              )}
            </div>
          </div>
        </div>

        <DialogFooter className="border-t px-6 py-4">
          <Button variant="outline" onClick={() => onOpenChange(false)} type="button">
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={pending} type="button">
            {pending ? "Saving…" : isEdit ? "Save schedule" : "Add schedule"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
