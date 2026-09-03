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
  type TimingValue,
  timingFromSchedule,
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

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit schedule" : "New schedule"}</DialogTitle>
          <DialogDescription>
            Run a workflow on a timer with its own inventory and credentials. The
            workflow is published to the background tier so overlapping runs are
            serialised.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
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

          {workflowId != null ? (
            <div className="space-y-1.5">
              <Label className="text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
                Parameters
              </Label>
              <ScheduleParameterFields
                attributes={staticAttributes}
                values={paramValues}
                onChange={setParamValues}
              />
            </div>
          ) : null}

          <div className="space-y-1.5">
            <Label className="text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
              Timer
            </Label>
            <ScheduleTimingFields value={timing} onChange={setTiming} />
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

          <div className="flex items-center justify-between gap-2">
            <Label className="text-xs" htmlFor="schedule-enabled">
              Enabled
            </Label>
            <Switch id="schedule-enabled" checked={enabled} onCheckedChange={setEnabled} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} type="button">
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={pending} type="button">
            {pending ? "Saving…" : isEdit ? "Save schedule" : "Create schedule"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
