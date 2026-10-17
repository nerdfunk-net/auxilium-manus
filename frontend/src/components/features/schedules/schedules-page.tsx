"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { CalendarClock, FolderOpen, Loader2, Pencil, PlayCircle, Plus, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useWorkflowBuilderStore } from "@/components/features/workflows/hooks/use-workflow-builder-store";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { parseCronExpression } from "@/components/features/workflows/utils/schedule-cron";

import { ScheduleEditorDialog } from "./dialogs/schedule-editor-dialog";
import { useSchedulesQuery } from "./hooks/use-schedules-query";
import { useScheduleMutations } from "./hooks/use-schedule-mutations";
import type { WorkflowSchedule } from "./types/schedule";

function describeTiming(schedule: WorkflowSchedule): string {
  if (schedule.schedule_type === "once") {
    return schedule.run_at
      ? `Once · ${schedule.run_at.replace("T", " ").slice(0, 16)} UTC`
      : "Once";
  }
  const parsed = parseCronExpression(schedule.cron_expression ?? "");
  if (parsed.frequency === "hourly") return `Hourly at :${parsed.minute ?? "00"}`;
  if (parsed.frequency === "daily") return `Daily at ${parsed.time ?? ""} UTC`;
  if (parsed.frequency === "weekly")
    return `Weekly ${(parsed.days ?? []).join(", ")} at ${parsed.time ?? ""} UTC`;
  return `cron: ${schedule.cron_expression ?? ""}`;
}

function describeParams(schedule: WorkflowSchedule): string {
  const entries = Object.entries(schedule.run_inputs ?? {});
  if (entries.length === 0) return "—";
  return entries.map(([k, v]) => `${k}=${String(v)}`).join(", ");
}

interface PendingWorkflowNav {
  workflowId: number;
  workflowName: string;
  thenRuns: boolean;
}

export function SchedulesPage() {
  const router = useRouter();
  const { data: schedules, isLoading } = useSchedulesQuery();
  const { updateSchedule, deleteSchedule } = useScheduleMutations();

  const builderWorkflowId = useWorkflowBuilderStore((state) => state.workflowId);
  const builderIsDirty = useWorkflowBuilderStore((state) => state.isDirty);
  const requestWorkflowLoad = useWorkflowBuilderStore((state) => state.requestWorkflowLoad);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<WorkflowSchedule | null>(null);
  const [pendingDelete, setPendingDelete] = useState<WorkflowSchedule | null>(null);
  const [pendingNav, setPendingNav] = useState<PendingWorkflowNav | null>(null);

  const goToBuilder = useCallback(
    (workflowId: number, thenRuns: boolean) => {
      requestWorkflowLoad(workflowId, thenRuns);
      router.push("/workflows");
    },
    [requestWorkflowLoad, router],
  );

  const loadWorkflow = useCallback(
    (schedule: WorkflowSchedule, thenRuns: boolean) => {
      const alreadyLoaded = builderWorkflowId === schedule.workflow_id;
      // Show Run for the already-loaded workflow: just switch views — the runs
      // page never touches the canvas, so unsaved edits are safe.
      if (thenRuns && alreadyLoaded) {
        router.push("/workflows/runs");
        return;
      }
      if (alreadyLoaded && !builderIsDirty) {
        router.push(thenRuns ? "/workflows/runs" : "/workflows");
        return;
      }
      if (builderIsDirty) {
        setPendingNav({
          workflowId: schedule.workflow_id,
          workflowName: schedule.workflow_name ?? "the workflow",
          thenRuns,
        });
        return;
      }
      goToBuilder(schedule.workflow_id, thenRuns);
    },
    [builderWorkflowId, builderIsDirty, goToBuilder, router],
  );

  const openCreate = useCallback(() => {
    setEditing(null);
    setEditorOpen(true);
  }, []);

  const openEdit = useCallback((schedule: WorkflowSchedule) => {
    setEditing(schedule);
    setEditorOpen(true);
  }, []);

  const toggleEnabled = useCallback(
    (schedule: WorkflowSchedule, enabled: boolean) => {
      updateSchedule.mutate({ id: schedule.id, data: { enabled } });
    },
    [updateSchedule],
  );

  const rows = schedules ?? [];

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <CalendarClock className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-foreground">Schedules</h1>
              <p className="mt-1 text-muted-foreground">
                Run a workflow on a timer with its own inventory and credentials.
              </p>
            </div>
          </div>
          <Button onClick={openCreate} type="button">
            <Plus className="size-4" />
            New schedule
          </Button>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-muted-foreground">
            <Loader2 className="size-5 animate-spin" aria-hidden />
          </div>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-16 text-center text-muted-foreground">
            <CalendarClock className="size-10 opacity-30" aria-hidden />
            <p className="text-sm">No schedules yet.</p>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Workflow</TableHead>
                  <TableHead>Timer</TableHead>
                  <TableHead>Parameters</TableHead>
                  <TableHead>Last run</TableHead>
                  <TableHead className="text-right">Enabled</TableHead>
                  <TableHead className="w-24" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((schedule) => (
                  <TableRow key={schedule.id}>
                    <TableCell className="font-medium">
                      {schedule.name || "Schedule"}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">
                        {schedule.workflow_name ?? `#${schedule.workflow_id}`}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {describeTiming(schedule)}
                    </TableCell>
                    <TableCell className="max-w-[220px] truncate text-muted-foreground">
                      {describeParams(schedule)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {schedule.last_triggered_at
                        ? schedule.last_triggered_at.replace("T", " ").slice(0, 16)
                        : "Never"}
                    </TableCell>
                    <TableCell className="text-right">
                      <Switch
                        checked={schedule.enabled}
                        onCheckedChange={(checked) => toggleEnabled(schedule, checked)}
                        aria-label={`Toggle ${schedule.name || "schedule"}`}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button
                          aria-label="Load workflow in builder"
                          title="Load workflow"
                          size="icon"
                          type="button"
                          variant="ghost"
                          onClick={() => loadWorkflow(schedule, false)}
                        >
                          <FolderOpen className="size-4" />
                        </Button>
                        <Button
                          aria-label="Show runs for this workflow"
                          title="Show runs"
                          size="icon"
                          type="button"
                          variant="ghost"
                          onClick={() => loadWorkflow(schedule, true)}
                        >
                          <PlayCircle className="size-4" />
                        </Button>
                        <Button
                          aria-label="Edit schedule"
                          size="icon"
                          type="button"
                          variant="ghost"
                          onClick={() => openEdit(schedule)}
                        >
                          <Pencil className="size-4" />
                        </Button>
                        <Button
                          aria-label="Delete schedule"
                          size="icon"
                          type="button"
                          variant="ghost"
                          onClick={() => setPendingDelete(schedule)}
                        >
                          <Trash2 className="size-4 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {editorOpen ? (
        <ScheduleEditorDialog
          key={editing?.id ?? "new"}
          onOpenChange={setEditorOpen}
          schedule={editing}
        />
      ) : null}

      <Dialog
        open={pendingDelete != null}
        onOpenChange={(next) => !next && setPendingDelete(null)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete schedule?</DialogTitle>
            <DialogDescription>
              This removes the timer for{" "}
              <span className="font-mono">{pendingDelete?.name || "this schedule"}</span>.
              The workflow itself is not deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setPendingDelete(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={deleteSchedule.isPending}
              onClick={() => {
                if (!pendingDelete) return;
                deleteSchedule.mutate(pendingDelete.id, {
                  onSuccess: () => setPendingDelete(null),
                });
              }}
            >
              {deleteSchedule.isPending ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={pendingNav != null} onOpenChange={(next) => !next && setPendingNav(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Discard unsaved changes?</DialogTitle>
            <DialogDescription>
              The workflow builder has unsaved changes. Loading{" "}
              <span className="font-medium">{pendingNav?.workflowName}</span> will discard
              them.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setPendingNav(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => {
                if (!pendingNav) return;
                goToBuilder(pendingNav.workflowId, pendingNav.thenRuns);
                setPendingNav(null);
              }}
            >
              Discard &amp; load
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
