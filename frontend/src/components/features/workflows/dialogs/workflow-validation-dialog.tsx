"use client";

import { useMemo } from "react";
import { AlertTriangle, CheckCircle2, ShieldAlert } from "lucide-react";

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
import { cn } from "@/lib/utils";

import type { PersistedCanvasNode } from "../types/workflow-canvas";
import type { ValidationFinding, WorkflowValidationResult } from "../types/workflow-validation";

interface WorkflowValidationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  result: WorkflowValidationResult | null;
  allNodes: PersistedCanvasNode[];
  onSelectNode: (nodeId: string) => void;
}

interface FindingGroup {
  nodeId: string | null;
  title: string;
  findings: ValidationFinding[];
}

const SEVERITY_BADGE_CLASS: Record<ValidationFinding["severity"], string> = {
  error: "border-error-border bg-error text-error-foreground",
  warning: "border-warning-border bg-warning text-warning-foreground",
};

function groupFindings(
  findings: ValidationFinding[],
  nodeTitleById: Map<string, string>,
): FindingGroup[] {
  const groups = new Map<string, FindingGroup>();
  for (const finding of findings) {
    const key = finding.node_id ?? "__workflow__";
    const existing = groups.get(key);
    if (existing) {
      existing.findings.push(finding);
      continue;
    }
    groups.set(key, {
      nodeId: finding.node_id,
      title: finding.node_id
        ? (nodeTitleById.get(finding.node_id) ?? finding.node_id)
        : "Workflow",
      findings: [finding],
    });
  }
  return Array.from(groups.values());
}

export function WorkflowValidationDialog({
  open,
  onOpenChange,
  result,
  allNodes,
  onSelectNode,
}: WorkflowValidationDialogProps) {
  const nodeTitleById = useMemo(() => {
    const map = new Map<string, string>();
    for (const node of allNodes) {
      const title = typeof node.data?.title === "string" ? node.data.title : undefined;
      if (title) map.set(node.id, title);
    }
    return map;
  }, [allNodes]);

  const groups = useMemo(
    () => groupFindings(result?.findings ?? [], nodeTitleById),
    [result, nodeTitleById],
  );

  const errorCount = result?.findings.filter((f) => f.severity === "error").length ?? 0;
  const warningCount = result?.findings.filter((f) => f.severity === "warning").length ?? 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[80vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle className="flex items-center gap-2">
            {errorCount > 0 ? (
              <ShieldAlert className="size-4 text-error-foreground" />
            ) : (
              <CheckCircle2 className="size-4 text-success-foreground" />
            )}
            Validation results
          </DialogTitle>
          <DialogDescription>
            {groups.length === 0
              ? "No schema or reference issues found."
              : `${errorCount} error${errorCount === 1 ? "" : "s"}, ${warningCount} warning${
                  warningCount === 1 ? "" : "s"
                } across ${groups.length} step${groups.length === 1 ? "" : "s"}.`}
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {groups.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-10 text-center text-sm text-muted-foreground">
              <CheckCircle2 className="size-8 text-success-foreground" />
              This workflow passed schema and reference validation.
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {groups.map((group) => (
                <div
                  key={group.nodeId ?? "__workflow__"}
                  className={cn(
                    "rounded-lg border p-3",
                    group.nodeId ? "cursor-pointer hover:bg-muted/50" : "",
                  )}
                  onClick={() => group.nodeId && onSelectNode(group.nodeId)}
                  role={group.nodeId ? "button" : undefined}
                  tabIndex={group.nodeId ? 0 : undefined}
                  onKeyDown={(event) => {
                    if (group.nodeId && (event.key === "Enter" || event.key === " ")) {
                      event.preventDefault();
                      onSelectNode(group.nodeId);
                    }
                  }}
                >
                  <p className="text-sm font-semibold">{group.title}</p>
                  <div className="mt-2 flex flex-col gap-2">
                    {group.findings.map((finding, index) => (
                      <div key={index} className="flex items-start gap-2">
                        <Badge
                          className={cn("shrink-0 gap-1", SEVERITY_BADGE_CLASS[finding.severity])}
                          variant="outline"
                        >
                          <AlertTriangle className="size-3" aria-hidden />
                          {finding.severity}
                        </Badge>
                        <p className="text-xs leading-5 text-muted-foreground">
                          {finding.message}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <DialogFooter className="border-t px-6 py-4">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
