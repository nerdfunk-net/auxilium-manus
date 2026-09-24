"use client";

import { Bot } from "lucide-react";
import { useCallback } from "react";

import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useWorkflowAiSessionMutations } from "@/hooks/queries/use-workflow-ai-session-mutations";
import { useWorkflowAiSessionQuery } from "@/hooks/queries/use-workflow-ai-session-query";
import { useToast } from "@/hooks/use-toast";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";

const DEFAULT_TTL_MINUTES = 60;

export function WorkflowAiSessionPanel() {
  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);
  const user = useAuthStore((state) => state.user);
  const { toast } = useToast();
  const { data: session, isLoading } = useWorkflowAiSessionQuery(workflowId);
  const { enable, disable } = useWorkflowAiSessionMutations();

  const handleToggle = useCallback(
    (checked: boolean) => {
      if (!workflowId) return;

      if (!checked) {
        disable.mutate(workflowId, {
          onSuccess: () => toast({ description: "AI updates disabled." }),
          onError: (error) => toast({ description: error.message, variant: "destructive" }),
        });
        return;
      }

      enable.mutate(
        { workflowId, data: { ttl_minutes: DEFAULT_TTL_MINUTES } },
        {
          onSuccess: () =>
            toast({
              description: `AI updates enabled for ${DEFAULT_TTL_MINUTES} minutes. A Claude session can now apply changes to this workflow until then.`,
            }),
          onError: (error) => toast({ description: error.message, variant: "destructive" }),
        },
      );
    },
    [workflowId, enable, disable, toast],
  );

  if (!workflowId || !hasPermission(user, "workflows", "write") || isLoading) {
    return null;
  }

  return (
    <div className="space-y-3 border-t pt-4">
      <div className="flex items-center gap-2">
        <Bot className="size-4 text-muted-foreground" aria-hidden />
        <span className="text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
          AI Collaboration
        </span>
      </div>

      <p className="text-[11.5px] text-muted-foreground">
        While enabled, the ai-assistant account may apply changes to this workflow&apos;s canvas —
        see doc/ai_collaboration/PROCESS.md. Time-boxed and off by default; your own edits are
        never affected or attributed to it.
      </p>

      <div className="flex items-center justify-between gap-2">
        <Label className="text-[13px]" htmlFor="ai-session-enabled">
          Enable AI updates
        </Label>
        <Switch
          id="ai-session-enabled"
          checked={!!session?.active}
          disabled={enable.isPending || disable.isPending}
          onCheckedChange={handleToggle}
        />
      </div>

      {session?.active ? (
        <p className="text-[11px] text-muted-foreground">
          Enabled by {session.enabled_by_username ?? "unknown"}
          {session.expires_at
            ? ` — expires ${new Date(session.expires_at).toLocaleTimeString()}`
            : null}
          .
        </p>
      ) : null}
    </div>
  );
}
