"use client";

import { useCallback, useState } from "react";
import { List, Sparkles, X } from "lucide-react";

import { AssistantPanel } from "@/components/features/ai-assistant/components/assistant-panel";
import { DataSharingNotice } from "@/components/features/ai-assistant/components/data-sharing-notice";
import { useAiAssistantAvailable } from "@/components/features/ai-assistant/hooks/use-ai-assistant-available";
import type { AssistantContext } from "@/components/features/ai-assistant/types/ai-assistant";
import { Button } from "@/components/ui/button";

import { DeviceSelector } from "./components/device-selector";
import { NautobotSourceBanner } from "./components/nautobot-source-banner";
import { useInventorySource } from "./hooks/use-inventory-source";

export function InventoryPage() {
  const source = useInventorySource();

  // AI assistant: read-only inventory questions, rendered only while the user has it enabled
  // and a Nautobot source exists (the tools read through that source).
  const assistantAvailable = useAiAssistantAvailable();
  const [assistantOpen, setAssistantOpen] = useState(false);
  const toggleAssistant = useCallback(
    () => setAssistantOpen((open) => !open),
    [],
  );
  const sourceId = source.sourceId;
  const getAssistantContext = useCallback(
    (): AssistantContext => ({ surface: "inventory", source_id: sourceId }),
    [sourceId],
  );
  const showAssistant = assistantAvailable && source.isReady;

  return (
    <div className="flex h-full min-h-0">
      <div className="h-full min-w-0 flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-6xl space-y-6">
          <div className="flex items-center gap-4">
            <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <List className="h-6 w-6" />
            </div>
            <div className="flex-1">
              <h1 className="text-3xl font-bold text-foreground">Inventory Builder</h1>
              <p className="mt-1 text-muted-foreground">
                Build dynamic device inventories using logical operations
              </p>
            </div>
            {showAssistant ? (
              <Button
                variant={assistantOpen ? "default" : "outline"}
                onClick={toggleAssistant}
              >
                <Sparkles className="size-4" />
                AI Assistant
              </Button>
            ) : null}
          </div>

          <NautobotSourceBanner
            hasSources={source.hasSources}
            isLoading={source.isLoading}
            isReady={source.isReady}
            sourceId={source.sourceId}
          />

          <DeviceSelector
            sourceId={source.sourceId}
            showActions
            showSaveLoad
            sourceReady={source.isReady}
          />
        </div>
      </div>
      {showAssistant && assistantOpen ? (
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
              placeholder="Ask about your inventories, e.g. how many devices are in LAB?"
              getContext={getAssistantContext}
            />
          </div>
        </aside>
      ) : null}
    </div>
  );
}
