"use client";

import { FileJson } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { parseStepOutput } from "@/lib/workflow-context-types";
import { StepErrorAlert } from "../step-error-alert";
import type { ErrorCategory } from "../../types/workflow-runs";

import { OutcomeContextView } from "./outcome-context-view";

export { DeviceErrorList } from "./device-error-list";

interface StepResultViewerProps {
  output: Record<string, unknown> | null;
  errorMessage?: string | null;
  errorCategory?: ErrorCategory | null;
  errorId?: string | null;
  compact?: boolean;
  runId?: number | null;
}

export function StepResultViewer({
  output,
  errorMessage,
  errorCategory = null,
  errorId = null,
  compact = false,
  runId = null,
}: StepResultViewerProps) {
  const envelope = useMemo(() => parseStepOutput(output), [output]);
  const outcomeNames = useMemo(
    () => (envelope ? Object.keys(envelope.outcomes) : []),
    [envelope],
  );
  const [selectedOutcome, setSelectedOutcome] = useState<string | null>(null);
  const activeOutcome = useMemo(() => {
    if (selectedOutcome && outcomeNames.includes(selectedOutcome)) {
      return selectedOutcome;
    }
    return outcomeNames[0] ?? "success";
  }, [outcomeNames, selectedOutcome]);

  if (errorMessage) {
    return (
      <StepErrorAlert message={errorMessage} category={errorCategory} errorId={errorId} />
    );
  }

  if (!envelope) {
    if (!output) {
      return (
        <p className="text-xs text-muted-foreground">No output recorded for this step.</p>
      );
    }

    return (
      <div>
        <p className="mb-2 flex items-center gap-1.5 text-xs text-warning-foreground">
          <FileJson className="size-3.5" />
          Legacy or unstructured output
        </p>
        <pre className="max-h-60 overflow-auto rounded bg-muted/30 p-3 text-xs font-mono">
          {JSON.stringify(output, null, 2)}
        </pre>
      </div>
    );
  }

  return (
    <Tabs
      value={activeOutcome}
      onValueChange={setSelectedOutcome}
      className="min-w-0 w-full overflow-hidden"
    >
      <TabsList className="h-8 max-w-full flex-wrap">
        {outcomeNames.map((name) => {
          const deviceCount = Object.keys(envelope.outcomes[name].devices).length;
          return (
            <TabsTrigger key={name} value={name} className="text-xs capitalize">
              {name}
              <Badge className="ml-1.5 h-4 px-1 text-[10px]" variant="secondary">
                {deviceCount}
              </Badge>
            </TabsTrigger>
          );
        })}
      </TabsList>
      {outcomeNames.map((name) => (
        <TabsContent key={name} value={name} className="mt-3 min-w-0 overflow-x-hidden">
          <OutcomeContextView
            context={envelope.outcomes[name]}
            runId={runId}
            compact={compact}
          />
        </TabsContent>
      ))}
    </Tabs>
  );
}
