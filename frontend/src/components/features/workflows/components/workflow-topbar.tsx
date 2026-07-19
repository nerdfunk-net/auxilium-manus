"use client";

import {
  ChevronDown,
  FastForward,
  FilePlus,
  FolderOpen,
  FolderCog,
  Play,
  Save,
  SaveAll,
  StepForward,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuthStore } from "@/lib/auth-store";
import { useWorkflowRunQuery } from "@/hooks/queries/use-workflow-run-query";
import {
  useApproveAllMutation,
  useApproveBatchMutation,
  useContinueRunMutation,
  useStepRunMutation,
} from "@/hooks/queries/use-workflow-run-mutations";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";

interface WorkflowTopbarProps {
  onNew: () => void;
  onOpen: () => void;
  onManage: () => void;
  onSave: () => void;
  onSaveAs: () => void;
  onRun: () => void;
}

export function WorkflowTopbar({
  onNew,
  onOpen,
  onManage,
  onSave,
  onSaveAs,
  onRun,
}: WorkflowTopbarProps) {
  const user = useAuthStore((state) => state.user);
  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);
  const workflowName = useWorkflowBuilderStore((state) => state.workflowName);
  const workflowStatus = useWorkflowBuilderStore(
    (state) => state.workflowStatus,
  );
  const isDirty = useWorkflowBuilderStore((state) => state.isDirty);
  const runMode = useWorkflowBuilderStore((state) => state.runMode);
  const setRunMode = useWorkflowBuilderStore((state) => state.setRunMode);
  const activeRunId = useWorkflowBuilderStore((state) => state.activeRunId);

  const { data: activeRun } = useWorkflowRunQuery(activeRunId);
  const stepRun = useStepRunMutation(workflowId);
  const continueRun = useContinueRunMutation(workflowId);
  const approveBatch = useApproveBatchMutation(workflowId);
  const approveAll = useApproveAllMutation(workflowId);
  const approvalState = activeRun?.approval_state;
  const isAwaitingBatch = activeRun?.status === "paused" && approvalState?.awaiting === true;
  const isAwaitingStep =
    !isAwaitingBatch && runMode === "debug" && activeRun?.status === "paused";

  return (
    <header className="flex h-16 items-center justify-between border-b bg-card px-5">
      <div className="flex items-center gap-4">
        <div>
          <h1 className="text-sm font-semibold">
            {workflowName}
            {isDirty ? <span className="ml-1 text-muted-foreground">●</span> : null}
          </h1>
          <p className="text-xs text-muted-foreground">
            Select devices, run commands, and store artifacts.
          </p>
        </div>
        <Badge
          variant={
            workflowStatus === "Error"
              ? "destructive"
              : workflowStatus === "Running"
                ? "default"
                : "outline"
          }
        >
          {workflowStatus}
        </Badge>
      </div>

      <div className="flex items-center gap-3">
        {user ? (
          <span className="text-xs text-muted-foreground">{user.username}</span>
        ) : null}
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-muted-foreground">Run as</span>
          <Select
            value={runMode}
            onValueChange={(value) => setRunMode(value as typeof runMode)}
          >
            <SelectTrigger className="h-8 w-[110px]" aria-label="Run as">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="normal">Normal</SelectItem>
              <SelectItem value="debug">Debug</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {isAwaitingBatch && approvalState ? (
          <>
            <Button
              variant="outline"
              disabled={approveBatch.isPending || !activeRunId}
              onClick={() => activeRunId && approveBatch.mutate(activeRunId)}
            >
              <StepForward className="size-4" />
              Run next batch ({approvalState.next_batch_index + 1}/
              {approvalState.total_batches})
            </Button>
            <Button
              variant="outline"
              disabled={approveAll.isPending || !activeRunId}
              onClick={() => activeRunId && approveAll.mutate(activeRunId)}
            >
              <FastForward className="size-4" />
              Run all remaining
            </Button>
          </>
        ) : null}

        {isAwaitingStep ? (
          <>
            <Button
              variant="outline"
              disabled={stepRun.isPending || !activeRunId}
              onClick={() => activeRunId && stepRun.mutate(activeRunId)}
            >
              <StepForward className="size-4" />
              Next Step
            </Button>
            <Button
              variant="outline"
              disabled={continueRun.isPending || !activeRunId}
              onClick={() => activeRunId && continueRun.mutate(activeRunId)}
            >
              <FastForward className="size-4" />
              Run to completion
            </Button>
          </>
        ) : null}

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline">
              File
              <ChevronDown className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={onNew}>
              <FilePlus className="size-4" />
              New
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={onOpen}>
              <FolderOpen className="size-4" />
              Open…
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={onManage}>
              <FolderCog className="size-4" />
              Manage…
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={onSave}>
              <Save className="size-4" />
              Save
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={onSaveAs}>
              <SaveAll className="size-4" />
              Save As…
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <Button onClick={onRun}>
          <Play className="size-4" />
          Run
        </Button>
      </div>
    </header>
  );
}
