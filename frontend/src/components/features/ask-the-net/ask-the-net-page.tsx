"use client";

import { MessageCircleQuestion } from "lucide-react";

import { AssistantPanel } from "@/components/features/ai-assistant/components/assistant-panel";
import { DataSharingNotice } from "@/components/features/ai-assistant/components/data-sharing-notice";
import type { AssistantContext } from "@/components/features/ai-assistant/types/ai-assistant";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useAiStatusQuery } from "@/hooks/queries/use-ai-status-query";
import { useNautobotConfiguredSourcesQuery } from "@/hooks/queries/use-nautobot-configured-sources-query";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import { AssistantUnavailable } from "./components/assistant-unavailable";
import { HelpDialog } from "./components/help-dialog";
import {
  ASK_THE_NET_PLACEHOLDER,
  ASK_THE_NET_SCOPE,
  ASK_THE_NET_SESSION_KEY,
} from "./constants/ask-the-net";
import { hasAskTheNetData } from "./utils/data-access";

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
  // Access is the assistant itself (the status says whether this user may use it). What it can
  // read depends on the user's other permissions, which every tool group checks on each call.
  const available = status?.available === true;
  // Nautobot reads count only when a source is configured; the query needs that permission.
  const nautobotSources = useNautobotConfiguredSourcesQuery({
    enabled: available && hasPermission(user, "sources.nautobot", "read"),
  });
  const nautobotConfigured = nautobotSources.data
    ? nautobotSources.data.length > 0
    : undefined;
  const hasDataPermission = hasAskTheNetData(user, nautobotConfigured);

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
        <p className="text-sm text-muted-foreground">
          Ask questions about your network and get answers from your own data,
          as far as your permissions reach: the Batfish model of your device
          configurations, the documented network in Nautobot, workflow runs and,
          when you confirm, live read-only device commands. It can also write
          reports. The Batfish model is a snapshot of your configurations, not
          the live network.
        </p>
      </div>
      <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col gap-3">
        {available ? (
          <>
            {hasDataPermission ? null : (
              <Alert data-testid="no-data-permission">
                <AlertDescription>
                  None of your permissions lets Ask the Net read your network
                  (for example sources.nautobot:read with a Nautobot source,
                  sources.batfish:query, reports:read or workflow_runs:read), so
                  it cannot look anything up in Batfish, Nautobot, runs or
                  reports for you. Tools that need no permission, such as a DNS
                  lookup when the operator has switched it on, still follow your
                  data settings. Ask an administrator for access.
                </AlertDescription>
              </Alert>
            )}
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
          <AssistantUnavailable status={status} isLoading={isLoading} />
        )}
      </div>
    </div>
  );
}
