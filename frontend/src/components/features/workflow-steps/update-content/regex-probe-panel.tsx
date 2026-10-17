"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  useUpdateContentProbeMutation,
  type UpdateContentProbeResult,
} from "@/hooks/queries/use-update-content-mutations";

import type { RegexFlags } from "./update-content-config";

const EMPTY_PROBE_RESULT: UpdateContentProbeResult | null = null;
const DEFAULT_SAMPLE_TEXT = "ntp server 192.168.1.10\nhostname r1\n";

interface RegexProbePanelProps {
  pattern: string;
  replacement: string;
  regexFlags: RegexFlags;
  replaceAll: boolean;
}

function ProbeResultView({ result }: { result: UpdateContentProbeResult }) {
  return (
    <div className="space-y-2 rounded-lg border border-step-border bg-step-surface p-3 text-step-surface-foreground">
      <div className="flex items-center gap-2">
        <Badge
          className={
            result.matched
              ? "bg-step-hover text-step-foreground hover:bg-step-hover"
              : "bg-warning text-warning-foreground hover:bg-warning"
          }
        >
          {result.matched ? `${result.match_count} match(es)` : "No match"}
        </Badge>
      </div>

      {result.updated_text !== null ? (
        <div className="space-y-1">
          <p className="text-[11px] font-medium">Result</p>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md border bg-card p-2 font-mono text-[11px] leading-4">
            {result.updated_text}
          </pre>
        </div>
      ) : null}

      {!result.matched ? (
        <p className="text-[11px] leading-4">
          The pattern did not match the sample text. At runtime, this rule leaves the
          content unchanged and the step continues.
        </p>
      ) : null}
    </div>
  );
}

export function RegexProbePanel({
  pattern,
  replacement,
  regexFlags,
  replaceAll,
}: RegexProbePanelProps) {
  const [sampleText, setSampleText] = useState(DEFAULT_SAMPLE_TEXT);
  const [result, setResult] = useState<UpdateContentProbeResult | null>(EMPTY_PROBE_RESULT);

  const probeMutation = useUpdateContentProbeMutation();

  const probePayload = useMemo(
    () => ({
      pattern,
      replacement,
      regex_flags: regexFlags,
      replace_all: replaceAll,
    }),
    [pattern, replacement, regexFlags, replaceAll],
  );

  const handleProbe = useCallback(async () => {
    const next = await probeMutation.mutateAsync({
      sample_text: sampleText,
      ...probePayload,
    });
    setResult(next);
  }, [probeMutation, probePayload, sampleText]);

  return (
    <div className="space-y-4">
      <p className="text-[11px] leading-4 text-muted-foreground">
        Test your rule against a sample config snippet before running the workflow.
        Replacements support Python backrefs such as <span className="font-mono">{"\\1"}</span>{" "}
        and <span className="font-mono">{"\\g<name>"}</span>.
      </p>

      <div className="space-y-2 rounded-lg border bg-background p-3">
        <Textarea
          value={sampleText}
          onChange={(event) => setSampleText(event.target.value)}
          rows={6}
          className="font-mono text-xs"
        />
        <Button
          type="button"
          size="sm"
          className="bg-step text-step-foreground hover:bg-step-hover"
          onClick={() => void handleProbe()}
          disabled={probeMutation.isPending}
        >
          Probe sample text
        </Button>
        {result ? <ProbeResultView result={result} /> : null}
        {probeMutation.error ? (
          <p className="text-[11px] text-destructive">{probeMutation.error.message}</p>
        ) : null}
      </div>
    </div>
  );
}
