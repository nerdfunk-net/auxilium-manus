"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Layers } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { summarizeDeviceGroups } from "../utils/live-step-progress";
import type { WorkflowRunDeviceGroup, WorkflowStepResult } from "../types/workflow-runs";
import { StepStatusBadge } from "./step-status-badge";

const MAX_DEVICE_NAMES_SHOWN = 3;

interface DeviceGroupsPanelProps {
  deviceGroups: readonly WorkflowRunDeviceGroup[];
  stepResults: readonly WorkflowStepResult[];
}

function formatDevices(names: readonly string[]): string {
  const shown = names.slice(0, MAX_DEVICE_NAMES_SHOWN).join(", ");
  const extra = names.length - MAX_DEVICE_NAMES_SHOWN;
  return extra > 0 ? `${shown} +${extra} more` : shown;
}

/**
 * Live view of fan-out children. Children write no step rows while they run, so
 * this is where an operator sees which step each device group is on.
 */
export function DeviceGroupsPanel({ deviceGroups, stepResults }: DeviceGroupsPanelProps) {
  const [open, setOpen] = useState(true);
  const summary = useMemo(() => summarizeDeviceGroups(deviceGroups), [deviceGroups]);
  const stepNameByNodeId = useMemo(
    () => new Map(stepResults.map((step) => [step.step_node_id, step.step_name])),
    [stepResults],
  );

  if (deviceGroups.length === 0) {
    return null;
  }

  return (
    <div className="border-t">
      <Button
        variant="ghost"
        className="flex h-auto w-full items-center justify-start gap-2 rounded-none px-4 py-2 text-xs"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
      >
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        <Layers className="size-3.5 text-muted-foreground" aria-hidden />
        <span className="font-semibold">Device groups</span>
        <span className="text-muted-foreground">
          {summary.finished}/{summary.total} finished
          {summary.running > 0 ? ` · ${summary.running} running` : ""}
          {summary.failed > 0 ? ` · ${summary.failed} failed` : ""}
          {summary.partial > 0 ? ` · ${summary.partial} partial` : ""}
        </span>
      </Button>
      {open ? (
        <div className="max-h-64 overflow-y-auto px-4 pb-3">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12 text-xs">#</TableHead>
                <TableHead className="text-xs">Devices</TableHead>
                <TableHead className="text-xs">Current step</TableHead>
                <TableHead className="w-24 text-right text-xs">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {deviceGroups.map((group) => {
                const runningSteps = Object.entries(group.node_states)
                  .filter(([, state]) => state === "running")
                  .map(([nodeId]) => stepNameByNodeId.get(nodeId) ?? nodeId);
                return (
                  <TableRow key={group.child_index}>
                    <TableCell className="text-xs tabular-nums">{group.child_index + 1}</TableCell>
                    <TableCell className="text-xs">{formatDevices(group.device_names)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {group.error_message && group.status === "failed"
                        ? group.error_message
                        : runningSteps.length > 0
                          ? runningSteps.join(", ")
                          : "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <StepStatusBadge status={group.status} />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </div>
  );
}
