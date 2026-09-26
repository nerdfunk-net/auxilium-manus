"use client";

import { Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useWorkflowAiSessionQuery } from "@/hooks/queries/use-workflow-ai-session-query";

/**
 * "AI updated this — reload to view" strip, styled like run-banners.tsx's
 * inline banners (not the popup toast, which auto-dismisses too fast for
 * this). Purely derived, no dismiss state: visible exactly when the poll's
 * workflow_updated_at is newer than the updated_at this canvas loaded with.
 *
 * "Reload" calls onReload (wired to the same handleLoadWorkflow used by the
 * Open dialog) rather than a full page reload — this app has no per-workflow
 * URL/route, so window.location.reload() lands on a blank new workflow, not
 * the one you're looking at. Re-fetching and re-applying in place is the
 * only correct "reload" here.
 */
export function AiSessionUpdateBanner({
  workflowId,
  baselineUpdatedAt,
  onReload,
}: {
  workflowId: number | null;
  baselineUpdatedAt: string | null;
  onReload: () => void;
}) {
  const { data: session } = useWorkflowAiSessionQuery(workflowId);

  if (!baselineUpdatedAt || !session) return null;
  const hasNewerVersion = new Date(session.workflow_updated_at) > new Date(baselineUpdatedAt);
  if (!hasNewerVersion) return null;

  return (
    <div className="flex items-center gap-2 border-t bg-warning px-4 py-2 text-xs text-warning-foreground">
      <Sparkles className="size-3.5 shrink-0 text-warning-foreground" aria-hidden />
      <span className="font-semibold">The AI updated this workflow</span>
      <span className="text-warning-foreground">— what&apos;s on screen is out of date.</span>
      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onReload}>
        Reload
      </Button>
    </div>
  );
}
