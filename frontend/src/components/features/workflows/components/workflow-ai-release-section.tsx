"use client";

import { MessagesSquare } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useWorkflowAiReleaseMutations } from "@/hooks/queries/use-workflow-ai-release-mutations";
import { useWorkflowAiReleaseQuery } from "@/hooks/queries/use-workflow-ai-release-query";
import { useToast } from "@/hooks/use-toast";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";

/** The Select cannot hold an empty value, so "no designated result" has its own item value. */
const NO_RESULT = "__none__";
const MAX_DESCRIPTION = 4000;

/**
 * "Release to be used by Ask the Net": lets the assistant propose running this workflow (the user
 * still confirms every start) and read one designated step's output as the result. Needs
 * `workflows:release_ai`. Any change to the saved definition clears the release on the server.
 */
export function WorkflowAiReleaseSection() {
  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);
  const visibility = useWorkflowBuilderStore(
    (state) => state.workflowVisibility,
  );
  const isDirty = useWorkflowBuilderStore((state) => state.isDirty);
  const user = useAuthStore((state) => state.user);
  const { toast } = useToast();
  const allowed = hasPermission(user, "workflows", "release_ai");
  const { data, refetch } = useWorkflowAiReleaseQuery(workflowId, allowed);
  const { release, unrelease } = useWorkflowAiReleaseMutations();

  // What the user typed; null shows the saved release. Derived, not synced in an effect.
  const [draftDescription, setDraftDescription] = useState<string | null>(null);
  const [draftResultNode, setDraftResultNode] = useState<string | null>(null);

  const savedNodes = data?.canvas_nodes;
  const steps = useMemo(
    () =>
      (savedNodes ?? [])
        .filter((node) => node.type === "workflowNode")
        .map((node) => ({ id: node.id, title: node.data?.title || node.id })),
    [savedNodes],
  );

  const description = draftDescription ?? data?.ai_description ?? "";
  const resultNodeId = draftResultNode ?? data?.ai_result_node_id ?? NO_RESULT;

  // Saving the canvas clears a release on the server: look again once the save is done.
  useEffect(() => {
    if (!isDirty && allowed) {
      void refetch();
    }
  }, [isDirty, allowed, refetch]);

  const handleRelease = useCallback(() => {
    if (!workflowId) return;
    release.mutate(
      {
        workflowId,
        data: {
          description: description.trim(),
          result_node_id: resultNodeId === NO_RESULT ? null : resultNodeId,
        },
      },
      {
        onSuccess: () => {
          setDraftDescription(null);
          setDraftResultNode(null);
          toast({ description: "Released for Ask the Net." });
        },
        onError: (error) =>
          toast({ description: error.message, variant: "destructive" }),
      },
    );
  }, [workflowId, description, resultNodeId, release, toast]);

  const handleRemove = useCallback(() => {
    if (!workflowId) return;
    unrelease.mutate(workflowId, {
      onSuccess: () => {
        setDraftDescription(null);
        setDraftResultNode(null);
        toast({ description: "Release removed." });
      },
      onError: (error) =>
        toast({ description: error.message, variant: "destructive" }),
    });
  }, [workflowId, unrelease, toast]);

  if (!workflowId || !allowed) {
    return null;
  }

  const released = !!data?.ai_released;
  const blocker =
    visibility === "private"
      ? "Share the workflow (not private) before releasing it."
      : isDirty
        ? "Save the workflow first: a release belongs to the saved version."
        : description.trim().length === 0
          ? "Describe the workflow for the assistant to enable Release."
          : null;
  const busy = release.isPending || unrelease.isPending;

  return (
    <div className="space-y-3 border-t pt-4">
      <div className="flex items-center gap-2">
        <MessagesSquare className="size-4 text-muted-foreground" aria-hidden />
        <span className="text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
          Release to be used by Ask the Net
        </span>
      </div>

      <p className="text-[11.5px] text-muted-foreground">
        Lets the assistant propose running this workflow and read one
        step&apos;s output. Every start still needs a click from the user, who
        must be allowed to run it. Editing the workflow ends the release.
      </p>

      <div className="space-y-1.5">
        <Label className="text-[13px]" htmlFor="ai-release-description">
          Description for the assistant
        </Label>
        <Textarea
          id="ai-release-description"
          value={description}
          maxLength={MAX_DESCRIPTION}
          rows={4}
          placeholder="What it does, when to use it, what each input means, what the result holds."
          onChange={(event) => setDraftDescription(event.target.value)}
          disabled={busy}
        />
      </div>

      <div className="space-y-1.5">
        <Label className="text-[13px]" htmlFor="ai-release-result">
          Result step
        </Label>
        <Select
          value={resultNodeId}
          onValueChange={setDraftResultNode}
          disabled={busy}
        >
          <SelectTrigger id="ai-release-result" aria-label="Result step">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_RESULT}>None (status only)</SelectItem>
            {steps.map((step) => (
              <SelectItem key={step.id} value={step.id}>
                {step.title}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {blocker ? (
        <p className="text-[11px] text-muted-foreground" role="status">
          {blocker}
        </p>
      ) : null}

      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          onClick={handleRelease}
          disabled={busy || !!blocker}
        >
          {released ? "Update release" : "Release"}
        </Button>
        {released ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handleRemove}
            disabled={busy}
          >
            Remove release
          </Button>
        ) : null}
      </div>

      {released && data?.ai_released_at ? (
        <p className="text-[11px] text-muted-foreground">
          Released {new Date(data.ai_released_at).toLocaleString()}.
        </p>
      ) : null}
    </div>
  );
}
