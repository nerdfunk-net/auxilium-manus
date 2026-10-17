"use client";

import { Rocket } from "lucide-react";
import { useCallback, useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useWorkflowBackgroundTierMutations } from "@/hooks/queries/use-workflow-background-tier-mutations";
import { useWorkflowBackgroundTierQuery } from "@/hooks/queries/use-workflow-background-tier-query";
import { useToast } from "@/hooks/use-toast";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";

export function WorkflowBackgroundTierPanel() {
  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);
  const user = useAuthStore((state) => state.user);
  const { toast } = useToast();
  const { data: tier, isLoading } = useWorkflowBackgroundTierQuery(workflowId);
  const { publish, unpublish, checkHasActiveRuns } = useWorkflowBackgroundTierMutations();

  const [concurrencyInput, setConcurrencyInput] = useState("");
  const [syncedTierId, setSyncedTierId] = useState<number | null>(null);

  // Adjust local editable state during render when the fetched tier changes
  // (a different workflow's tier loaded, or a publish/unpublish completed) —
  // the React-recommended alternative to setState-in-effect for this case.
  const tierId = tier?.id ?? null;
  if (tierId !== syncedTierId) {
    setSyncedTierId(tierId);
    setConcurrencyInput(tier?.concurrency_limit != null ? String(tier.concurrency_limit) : "");
  }

  const handleToggle = useCallback(
    async (checked: boolean) => {
      if (!workflowId) return;

      if (!checked) {
        let hadActiveRuns = false;
        try {
          hadActiveRuns = await checkHasActiveRuns(workflowId);
        } catch {
          // If the check itself fails, proceed with unpublish anyway rather
          // than blocking the admin action on a secondary lookup.
        }
        unpublish.mutate(workflowId, {
          onSuccess: () => {
            toast({
              description: hadActiveRuns
                ? "Unpublished. Runs still in progress for this workflow may stall until re-published."
                : "Unpublished from the background tier.",
              variant: hadActiveRuns ? "destructive" : "default",
            });
          },
          onError: (error) => toast({ description: error.message, variant: "destructive" }),
        });
        return;
      }

      publish.mutate(
        { workflowId, data: { concurrency_limit: null } },
        {
          onSuccess: () =>
            toast({
              description:
                "Published to the background tier. Takes effect within ~30 seconds.",
            }),
          onError: (error) => toast({ description: error.message, variant: "destructive" }),
        },
      );
    },
    [workflowId, publish, unpublish, checkHasActiveRuns, toast],
  );

  const handleConcurrencyBlur = useCallback(() => {
    if (!workflowId || !tier) return;
    const trimmed = concurrencyInput.trim();
    const nextLimit = trimmed === "" ? null : Math.max(1, Number(trimmed));
    if (nextLimit === tier.concurrency_limit) return;

    publish.mutate(
      { workflowId, data: { concurrency_limit: nextLimit } },
      {
        onSuccess: () =>
          toast({ description: "Concurrency limit updated. Takes effect within ~30 seconds." }),
        onError: (error) => toast({ description: error.message, variant: "destructive" }),
      },
    );
  }, [workflowId, tier, concurrencyInput, publish, toast]);

  if (!workflowId || !hasPermission(user, "workflows", "publish") || isLoading) {
    return null;
  }

  return (
    <div className="space-y-3 border-t pt-4">
      <div className="flex items-center gap-2">
        <Rocket className="size-4 text-muted-foreground" aria-hidden />
        <span className="text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
          Background Tier
        </span>
      </div>

      <p className="text-[11.5px] text-muted-foreground">
        Publishing gives this workflow its own dedicated execution identity, so it can never
        overlap with itself and never competes with other workflows for capacity. Independent of
        scheduling — publish a manually-triggered workflow too if you want it isolated.
      </p>

      <div className="flex items-center justify-between gap-2">
        <Label className="text-[13px]" htmlFor="background-tier-enabled">
          Publish to background tier
        </Label>
        <Switch
          id="background-tier-enabled"
          checked={!!tier}
          disabled={publish.isPending || unpublish.isPending}
          onCheckedChange={handleToggle}
        />
      </div>

      {tier ? (
        <div className="grid gap-1">
          <Label className="text-xs" htmlFor="background-tier-concurrency">
            Concurrency limit
          </Label>
          <Input
            id="background-tier-concurrency"
            type="number"
            min={1}
            placeholder="No limit"
            value={concurrencyInput}
            onChange={(e) => setConcurrencyInput(e.target.value)}
            onBlur={handleConcurrencyBlur}
          />
          <p className="text-[11px] text-muted-foreground">
            Max concurrent runs of this workflow. Blank = unlimited.
          </p>
        </div>
      ) : null}
    </div>
  );
}
