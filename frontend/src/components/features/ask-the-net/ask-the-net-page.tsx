"use client";

import { MessageCircleQuestion } from "lucide-react";

import { AssistantPanel } from "@/components/features/ai-assistant/components/assistant-panel";
import { DataSharingNotice } from "@/components/features/ai-assistant/components/data-sharing-notice";
import type { AssistantContext } from "@/components/features/ai-assistant/types/ai-assistant";
import { useAiStatusQuery } from "@/hooks/queries/use-ai-status-query";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import { AssistantUnavailable } from "./components/assistant-unavailable";
import { HelpDialog } from "./components/help-dialog";
import {
  ASK_THE_NET_PLACEHOLDER,
  ASK_THE_NET_SCOPE,
  ASK_THE_NET_SESSION_KEY,
} from "./constants/ask-the-net";

// A module-level function: a stable identity, so the chat hook does not see a new callback on
// every render.
const getAskTheNetContext = (): AssistantContext => ({ surface: "general" });

/**
 * Ask the Net: free questions about the network, answered from the Batfish model with read-only
 * tools (doc/AI_TOOL_CHAIN.md). The dashboard shell is `h-screen overflow-hidden`, so the page
 * brings its own layout; the chat panel scrolls inside it.
 */
export function AskTheNetPage() {
  const { data: status, isLoading } = useAiStatusQuery();
  const user = useAuthStore((state) => state.user);
  // The sidebar hides the link without this permission; a direct visit gets the same rule.
  const canQueryBatfish = hasPermission(user, "sources.batfish", "query");
  const available = status?.available === true && canQueryBatfish;

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-4 lg:p-6">
      <div className="mx-auto w-full max-w-3xl space-y-1">
        <div className="flex items-center justify-between gap-2">
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <MessageCircleQuestion className="size-5" aria-hidden />
            Ask the Net
          </h1>
          {available ? <HelpDialog /> : null}
        </div>
        {canQueryBatfish ? (
          <p className="text-sm text-muted-foreground">
            Ask questions about your network. Answers come from a Batfish
            snapshot of your device configurations, not the live network, and
            always say which snapshot they used.
          </p>
        ) : null}
      </div>
      <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col gap-3">
        {available ? (
          <>
            <DataSharingNotice />
            <div className="min-h-0 flex-1">
              <AssistantPanel
                sessionKey={ASK_THE_NET_SESSION_KEY}
                conversationScope={ASK_THE_NET_SCOPE}
                placeholder={ASK_THE_NET_PLACEHOLDER}
                getContext={getAskTheNetContext}
              />
            </div>
          </>
        ) : (
          <AssistantUnavailable
            status={status}
            isLoading={isLoading}
            missingBatfishPermission={
              status?.available === true && !canQueryBatfish
            }
          />
        )}
      </div>
    </div>
  );
}
