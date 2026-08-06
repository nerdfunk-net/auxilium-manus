"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { WorkflowSummary } from "@/components/features/workflows/types/workflow-persistence";

const NONE_VALUE = "__none__";

interface LinkWorkflowDialogProps {
  open: boolean;
  workflows: WorkflowSummary[];
  selectedId: number | null;
  onSelect: (workflowId: number | null) => void;
  onClose: () => void;
}

export function LinkWorkflowDialog({
  open,
  workflows,
  selectedId,
  onSelect,
  onClose,
}: LinkWorkflowDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Link Workflow</DialogTitle>
          <DialogDescription>
            Preview a workflow&apos;s declared static attributes as a{" "}
            <code className="font-mono">run_input</code> reference variable. This
            link is a per-session helper only — it is not saved with the
            template.
          </DialogDescription>
        </DialogHeader>

        <Select
          value={selectedId != null ? String(selectedId) : NONE_VALUE}
          onValueChange={(next) => {
            const workflowId = next === NONE_VALUE ? null : Number(next);
            onSelect(workflowId);
            onClose();
          }}
        >
          <SelectTrigger>
            <SelectValue placeholder="Select a workflow" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE_VALUE}>— None (unlink) —</SelectItem>
            {workflows.map((workflow) => (
              <SelectItem key={workflow.id} value={String(workflow.id)}>
                {workflow.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </DialogContent>
    </Dialog>
  );
}
