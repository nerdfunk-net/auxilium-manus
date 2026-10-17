"use client";

import { useState } from "react";
import { CheckCircle2, Minus, Table2, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { DeviceErrorList } from "./step-result-viewer";
import { StepErrorAlert } from "./step-error-alert";
import {
  buildStepSummaryMatrix,
  type SummaryCell,
  type SummaryDeviceRow,
} from "../utils/step-summary-matrix";
import type { WorkflowStepResult } from "../types/workflow-runs";

interface StepSummaryTableProps {
  steps: WorkflowStepResult[];
}

interface SelectedCell {
  step: WorkflowStepResult;
  device: SummaryDeviceRow;
  cell: SummaryCell;
}

function SummaryCellIcon({
  status,
  onClick,
}: {
  status: SummaryCell["status"];
  onClick?: () => void;
}) {
  if (status === "success") {
    return <CheckCircle2 className="size-4 text-success-foreground" aria-label="success" />;
  }
  if (status === "device-error" || status === "step-error") {
    return (
      <button
        type="button"
        onClick={onClick}
        className="rounded hover:bg-error"
        title="View error details"
      >
        <XCircle className="size-4 text-destructive" aria-label="failed — click for details" />
      </button>
    );
  }
  return <Minus className="size-4 text-muted-foreground/50" aria-label="not reached" />;
}

export function StepSummaryTable({ steps }: StepSummaryTableProps) {
  const [tableOpen, setTableOpen] = useState(false);
  const [selected, setSelected] = useState<SelectedCell | null>(null);
  const { devices, columns, getCell } = buildStepSummaryMatrix(steps);

  if (columns.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No other steps have completed yet — the summary table fills in as the run progresses.
      </p>
    );
  }

  if (devices.length === 0) {
    return <p className="text-xs text-muted-foreground">No devices recorded for this run.</p>;
  }

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="h-8 gap-1.5 rounded-lg border-input text-xs"
        onClick={() => setTableOpen(true)}
      >
        <Table2 className="size-3.5" aria-hidden />
        Open summary table ({devices.length} device{devices.length === 1 ? "" : "s"} ×{" "}
        {columns.length} step{columns.length === 1 ? "" : "s"})
      </Button>

      <Dialog open={tableOpen} onOpenChange={setTableOpen}>
        <DialogContent className="flex h-[85vh] max-w-4xl flex-col gap-0 overflow-hidden p-0">
          <DialogHeader className="shrink-0 border-b px-4 py-3">
            <DialogTitle>Run summary</DialogTitle>
            <DialogDescription className="text-xs">
              {devices.length} device{devices.length === 1 ? "" : "s"} × {columns.length} step
              {columns.length === 1 ? "" : "s"} — click a failed cell for details.
            </DialogDescription>
          </DialogHeader>
          <div className="min-h-0 flex-1 overflow-auto p-4">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="sticky left-0 z-10 bg-background">Device</TableHead>
                  {columns.map((step) => (
                    <TableHead
                      key={step.id}
                      title={step.step_name}
                      className="max-w-32 truncate text-center"
                    >
                      {step.step_name}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {devices.map((device) => (
                  <TableRow key={device.id}>
                    <TableCell className="sticky left-0 z-10 max-w-40 truncate bg-background font-medium">
                      <span title={`${device.name} (${device.hostname})`}>{device.name}</span>
                    </TableCell>
                    {columns.map((step) => {
                      const cell = getCell(step.id, device.id);
                      return (
                        <TableCell
                          key={step.id}
                          className={cn(
                            "text-center",
                            (cell.status === "device-error" || cell.status === "step-error") &&
                              "cursor-pointer",
                          )}
                        >
                          <div className="flex items-center justify-center">
                            <SummaryCellIcon
                              status={cell.status}
                              onClick={() => setSelected({ step, device, cell })}
                            />
                          </div>
                        </TableCell>
                      );
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!selected} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {selected?.device.name} — {selected?.step.step_name}
            </DialogTitle>
            <DialogDescription className="font-mono text-xs">
              {selected?.step.step_type}
            </DialogDescription>
          </DialogHeader>
          {selected?.cell.status === "step-error" ? (
            <StepErrorAlert
              message={selected.step.error_message}
              category={selected.step.error_category}
              errorId={selected.step.error_id}
            />
          ) : selected?.cell.status === "device-error" ? (
            <DeviceErrorList errors={selected.cell.errors} />
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
