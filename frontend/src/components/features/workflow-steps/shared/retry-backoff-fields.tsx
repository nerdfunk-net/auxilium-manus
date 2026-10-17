"use client";

import { Minus, Plus } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export const DEFAULT_RETRY_DELAY_SECONDS = 10;
export const MIN_RETRY_BACKOFF_SECONDS = 1;
export const MAX_RETRY_BACKOFF_SECONDS = 600;
export const MAX_RETRY_ATTEMPTS = 5;

export function parseRetryBackoffSeconds(config: Record<string, unknown>): number[] {
  const raw = config.retry_backoff_seconds;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.map((item) =>
    typeof item === "number" && Number.isFinite(item) ? item : DEFAULT_RETRY_DELAY_SECONDS,
  );
}

export interface RetryBackoffSecondsFieldProps {
  retryBackoffSeconds: number[];
  onRetryBackoffSecondsChange: (next: number[]) => void;
}

interface RetryDelayInputProps {
  delay: number;
  onCommit: (clamped: number) => void;
}

/** Holds its own draft text while focused so clearing the field to type a
 * replacement value doesn't get fought by a live default/clamp on every
 * keystroke — the number is only parsed and clamped on blur.
 *
 * Reset-on-external-change is done via the `key` the caller passes (keyed on
 * `delay`, not just row index — see below), not an effect: when the
 * committed value changes for a reason other than this input's own blur
 * (e.g. the row's position shifts, or a different node's config is now
 * shown), React remounts this component with a fresh `draft` instead of a
 * `useEffect` syncing local state from a prop.
 */
function RetryDelayInput({ delay, onCommit }: RetryDelayInputProps) {
  const [draft, setDraft] = useState(() => String(delay));

  return (
    <Input
      type="number"
      min={MIN_RETRY_BACKOFF_SECONDS}
      max={MAX_RETRY_BACKOFF_SECONDS}
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => {
        const parsed = Number.parseInt(draft, 10);
        const clamped = Number.isFinite(parsed)
          ? Math.min(MAX_RETRY_BACKOFF_SECONDS, Math.max(MIN_RETRY_BACKOFF_SECONDS, parsed))
          : DEFAULT_RETRY_DELAY_SECONDS;
        if (clamped === delay) {
          setDraft(String(clamped));
        } else {
          onCommit(clamped);
        }
      }}
      className="h-8 font-mono text-xs"
    />
  );
}

/** SSH connect-phase retry schedule — shared by every Netmiko-touching step's
 * ConfigPanel (Run Command, Get Configs). Never applied to command execution
 * or to an authentication failure — see connection.py::RetryPolicy. */
export function RetryBackoffSecondsField({
  retryBackoffSeconds,
  onRetryBackoffSecondsChange,
}: RetryBackoffSecondsFieldProps) {
  const handleDelayCommit = (index: number, clamped: number) => {
    const next = [...retryBackoffSeconds];
    next[index] = clamped;
    onRetryBackoffSecondsChange(next);
  };

  const handleAdd = () => {
    if (retryBackoffSeconds.length >= MAX_RETRY_ATTEMPTS) {
      return;
    }
    onRetryBackoffSecondsChange([...retryBackoffSeconds, DEFAULT_RETRY_DELAY_SECONDS]);
  };

  const handleRemove = (index: number) => {
    onRetryBackoffSecondsChange(
      retryBackoffSeconds.filter((_, itemIndex) => itemIndex !== index),
    );
  };

  return (
    <div className="space-y-1.5 border-t pt-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">retry_backoff_seconds</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            integer_list
          </Badge>
        </div>
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="size-7"
          onClick={handleAdd}
          disabled={retryBackoffSeconds.length >= MAX_RETRY_ATTEMPTS}
          title="Add retry"
        >
          <Plus className="size-3.5" />
        </Button>
      </div>

      {retryBackoffSeconds.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">
          No retry on a connection timeout — the step fails immediately, same as before. Add
          an attempt to retry an SSH connect that times out (e.g. an unstable WAN link),
          waiting the given number of seconds before that attempt. Never retried on an
          authentication failure.
        </p>
      ) : (
        <div className="space-y-2">
          {retryBackoffSeconds.map((delay, index) => (
            <div key={`retry-${index}`} className="flex items-center gap-2">
              <span className="w-14 shrink-0 text-[11px] text-muted-foreground">
                retry {index + 1}
              </span>
              <RetryDelayInput
                key={`${index}-${delay}`}
                delay={delay}
                onCommit={(clamped) => handleDelayCommit(index, clamped)}
              />
              <span className="shrink-0 text-[11px] text-muted-foreground">sec</span>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="size-8 shrink-0"
                onClick={() => handleRemove(index)}
                title="Remove retry"
              >
                <Minus className="size-3.5" />
              </Button>
            </div>
          ))}
          <p className="text-[11px] text-muted-foreground">
            Wait before each retry, in order (up to {MAX_RETRY_ATTEMPTS} entries).
          </p>
        </div>
      )}
    </div>
  );
}
