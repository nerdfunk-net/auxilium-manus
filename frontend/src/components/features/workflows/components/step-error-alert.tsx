"use client";

import { useCallback, useState } from "react";
import { AlertTriangle, Bug, Check, ChevronDown, ChevronRight, Copy, XCircle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { ErrorCategory } from "../types/workflow-runs";

interface StepErrorAlertProps {
  message: string | null;
  category: ErrorCategory | null;
  errorId: string | null;
  className?: string;
}

interface CategoryMeta {
  title: string;
  hint: string;
  icon: typeof AlertTriangle;
}

const CATEGORY_META: Record<ErrorCategory, CategoryMeta> = {
  configuration: {
    title: "Configuration error",
    hint: "This step is missing or has invalid configuration. Fix it in the step's settings and run again.",
    icon: AlertTriangle,
  },
  execution: {
    title: "Step failed",
    hint: "This step ran but could not complete. Review the message below, address the cause, and run again.",
    icon: XCircle,
  },
  internal: {
    title: "Unexpected error",
    hint: "This looks like an application bug rather than a configuration problem. Share the error ID below with an administrator so they can look up the full logs.",
    icon: Bug,
  },
};

/** Runs from before this field existed have no error_category. */
const FALLBACK_META: CategoryMeta = CATEGORY_META.internal;

/** Small inline icon for compact/collapsed error previews (e.g. a list row). */
export function ErrorCategoryIcon({
  category,
  className,
}: {
  category: ErrorCategory | null;
  className?: string;
}) {
  const Icon = (category ? CATEGORY_META[category] : null)?.icon ?? FALLBACK_META.icon;
  return <Icon className={className} />;
}

/** Rich, user-facing rendering of a step/run failure — replaces raw
 * "Step failed (ValueError). See worker logs for error_id=..." strings with a
 * categorized, human message plus an optional collapsible error ID for
 * correlating with worker logs. */
export function StepErrorAlert({ message, category, errorId, className }: StepErrorAlertProps) {
  const [copied, setCopied] = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  const handleCopyErrorId = useCallback(() => {
    if (!errorId) return;
    void navigator.clipboard.writeText(errorId).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [errorId]);

  if (!message) {
    return null;
  }

  const meta = (category ? CATEGORY_META[category] : null) ?? FALLBACK_META;
  const Icon = meta.icon;

  return (
    <Alert variant="destructive" className={className}>
      <Icon />
      <AlertTitle>{meta.title}</AlertTitle>
      <AlertDescription className="space-y-2">
        <p className="whitespace-pre-wrap break-words font-mono text-xs">{message}</p>
        <p className="text-xs text-muted-foreground">{meta.hint}</p>
        {errorId ? (
          <div>
            <button
              type="button"
              onClick={() => setShowDetails((value) => !value)}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              {showDetails ? (
                <ChevronDown className="size-3" />
              ) : (
                <ChevronRight className="size-3" />
              )}
              Technical details
            </button>
            {showDetails ? (
              <div className="mt-1 flex items-center gap-2 rounded border bg-muted/40 px-2 py-1">
                <code className="flex-1 truncate font-mono text-[11px] text-muted-foreground">
                  error_id={errorId}
                </code>
                <button
                  type="button"
                  onClick={handleCopyErrorId}
                  className="flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
                >
                  {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
