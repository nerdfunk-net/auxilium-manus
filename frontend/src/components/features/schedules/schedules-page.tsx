"use client";

import { useCallback, useState } from "react";
import { CalendarClock, Loader2, Pencil, Plus, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

export function SchedulesPage() {
  const { data: schedules, isLoading } = useSchedulesQuery();
  const { updateSchedule, deleteSchedule } = useScheduleMutations();

  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<WorkflowSchedule | null>(null);
  const [pendingDelete, setPendingDelete] = useState<WorkflowSchedule | null>(null);

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
    </div>
  );
}
