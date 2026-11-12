"use client";

import { Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";

/** Metadata key suffix written by the contact-the-ai step (`<node id>.ai_response`). */
export const AI_RESPONSE_METADATA_SUFFIX = ".ai_response";

export interface AiResponsePayload {
  status: "ok" | "failed" | "skipped";
  response?: string;
  reason?: string;
  provider?: string;
  model?: string;
  prompt_chars?: number;
  output_attribute?: string;
  responded_at?: string;
}

function isAiResponsePayload(value: unknown): value is AiResponsePayload {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const status = (value as { status?: unknown }).status;
  return status === "ok" || status === "failed" || status === "skipped";
}

export function extractAiResponses(metadata: Record<string, unknown>): AiResponsePayload[] {
  return Object.entries(metadata)
    .filter(([key]) => key.endsWith(AI_RESPONSE_METADATA_SUFFIX))
    .map(([, value]) => value)
    .filter(isAiResponsePayload);
}

export function AiResponsePanel({ entries }: { entries: AiResponsePayload[] }) {
  if (entries.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      {entries.map((entry, index) => (
        <div key={`ai-response-${index}`} className="rounded-lg border bg-card p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Sparkles className="size-3.5 shrink-0 text-step" aria-hidden />
            <Badge
              className="text-[10px]"
              variant={entry.status === "failed" ? "destructive" : "secondary"}
            >
              {entry.status === "ok" ? "answered" : entry.status}
            </Badge>
            {entry.provider ? (
              <Badge className="text-[10px]" variant="outline">
                {entry.provider}
                {entry.model ? ` · ${entry.model}` : ""}
              </Badge>
            ) : null}
            {entry.output_attribute ? (
              <span className="font-mono text-[11px] text-muted-foreground">
                → {`{${entry.output_attribute}}`}
              </span>
            ) : null}
            {typeof entry.prompt_chars === "number" ? (
              <span className="text-[11px] text-muted-foreground">
                prompt {entry.prompt_chars.toLocaleString()} chars
              </span>
            ) : null}
            {entry.responded_at ? (
              <span className="text-[11px] text-muted-foreground">{entry.responded_at}</span>
            ) : null}
          </div>
          {entry.status === "ok" ? (
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-muted/30 p-3 text-xs">
              {entry.response ?? ""}
            </pre>
          ) : (
            <p className="text-xs text-error-foreground">{entry.reason ?? "The AI step failed."}</p>
          )}
        </div>
      ))}
    </div>
  );
}
