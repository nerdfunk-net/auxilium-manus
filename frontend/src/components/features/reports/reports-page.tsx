"use client";

import { Sparkles, X } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";

import { AssistantPanel } from "@/components/features/ai-assistant/components/assistant-panel";
import { DataSharingNotice } from "@/components/features/ai-assistant/components/data-sharing-notice";
import { useAiAssistantAvailable } from "@/components/features/ai-assistant/hooks/use-ai-assistant-available";
import { useAssistantSessionOpen } from "@/components/features/ai-assistant/hooks/use-assistant-session-open";
import type {
  AssistantContext,
  ConversationScope,
  QueryProposal,
  ReportOutlineProposal,
  SectionTextProposal,
} from "@/components/features/ai-assistant/types/ai-assistant";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useReportSourcesQuery } from "@/hooks/queries/use-report-sources-query";

import { ExploreTab } from "./explore-tab";
import { ReportsTab, type ReportDraftRequest } from "./reports-tab";
import { SnapshotsTab } from "./snapshots-tab";
import type { ReportQuerySpec } from "./types/report-query";

const DEFAULT_SOURCE_ID = "report_data";

/**
 * The dashboard shell is `h-screen overflow-hidden`, so a page must bring its own scrolling:
 * the whole page scrolls on small screens, and from `lg` up the builder and the result panel
 * each scroll inside a fixed-height layout.
 */
export function ReportsPage() {
  const [tab, setTab] = useState("explore");
  const [loadRequest, setLoadRequest] = useState<{ id: number; query: ReportQuerySpec } | null>(
    null,
  );
  const nextLoadId = useRef(1);
  const [draftRequest, setDraftRequest] = useState<ReportDraftRequest | null>(null);
  const handleDraftConsumed = useCallback(() => setDraftRequest(null), []);

  // AI assistant: explains the catalog and proposes queries; values only with the user's opt-in.
  const assistantAvailable = useAiAssistantAvailable();
  const sources = useReportSourcesQuery();
  const sourceId = sources.data?.[0]?.id ?? DEFAULT_SOURCE_ID;
  const assistantSessionKey = `reports:${sourceId}`;
  const conversationScope = useMemo<ConversationScope>(
    () => ({ surface: "reports", subjectKey: sourceId }),
    [sourceId],
  );
  const {
    open: assistantOpen,
    setOpen: setAssistantOpen,
    toggle: toggleAssistant,
  } = useAssistantSessionOpen(assistantSessionKey);
  const getAssistantContext = useCallback(
    (): AssistantContext => ({ surface: "reports", source_id: sourceId }),
    [sourceId],
  );

  const handleApplyQuery = useCallback((proposal: QueryProposal) => {
    const id = nextLoadId.current;
    nextLoadId.current += 1;
    setLoadRequest({ id, query: proposal.query });
    setTab("explore");
  }, []);
  const queryTarget = useMemo(() => ({ onApply: handleApplyQuery }), [handleApplyQuery]);

  const handleApplyOutline = useCallback((proposal: ReportOutlineProposal) => {
    const id = nextLoadId.current;
    nextLoadId.current += 1;
    setDraftRequest({
      id,
      kind: "outline",
      draft: {
        name: proposal.name,
        description: proposal.description,
        sections: proposal.sections,
      },
    });
    setTab("reports");
  }, []);
  const handleApplySectionText = useCallback((proposal: SectionTextProposal) => {
    const id = nextLoadId.current;
    nextLoadId.current += 1;
    setDraftRequest({
      id,
      kind: "section_text",
      reportId: proposal.reportId,
      sectionId: proposal.sectionId,
      text: proposal.text,
    });
    setTab("reports");
  }, []);
  const reportTarget = useMemo(
    () => ({ onApplyOutline: handleApplyOutline, onApplySectionText: handleApplySectionText }),
    [handleApplyOutline, handleApplySectionText],
  );

  return (
    <div className="flex h-full min-h-0">
      <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-y-auto p-4 lg:overflow-hidden lg:p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold">Reports</h1>
            <p className="text-sm text-muted-foreground">
              Query the data collected by Store for Report steps across all devices, and turn
              queries into stored reports.
            </p>
          </div>
          {assistantAvailable ? (
            <Button variant={assistantOpen ? "default" : "outline"} onClick={toggleAssistant}>
              <Sparkles className="size-4" />
              AI Assistant
            </Button>
          ) : null}
        </div>
        <Tabs value={tab} onValueChange={setTab} className="min-h-0 flex-1">
          <TabsList>
            <TabsTrigger value="explore">Explore</TabsTrigger>
            <TabsTrigger value="reports">Reports</TabsTrigger>
            <TabsTrigger value="snapshots">Snapshots</TabsTrigger>
          </TabsList>
          <TabsContent value="explore" className="min-h-0 flex-1">
            <ExploreTab loadRequest={loadRequest} />
          </TabsContent>
          <TabsContent value="reports" className="min-h-0 flex-1 overflow-y-auto">
            <ReportsTab draftRequest={draftRequest} onDraftConsumed={handleDraftConsumed} />
          </TabsContent>
          <TabsContent value="snapshots" className="min-h-0 flex-1 overflow-y-auto">
            <SnapshotsTab />
          </TabsContent>
        </Tabs>
      </div>
      {assistantAvailable && assistantOpen ? (
        <aside
          className="flex w-[420px] shrink-0 flex-col gap-3 border-l bg-card p-4"
          aria-label="AI Assistant"
        >
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <Sparkles className="size-4" />
              AI Assistant
            </h2>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              onClick={() => setAssistantOpen(false)}
              aria-label="Close assistant"
            >
              <X className="size-4" />
            </Button>
          </div>
          <DataSharingNotice />
          <div className="min-h-0 flex-1">
            <AssistantPanel
              sessionKey={assistantSessionKey}
              conversationScope={conversationScope}
              placeholder="Ask about your report data, e.g. how many devices per location?"
              getContext={getAssistantContext}
              queryTarget={queryTarget}
              reportTarget={reportTarget}
            />
          </div>
        </aside>
      ) : null}
    </div>
  );
}
