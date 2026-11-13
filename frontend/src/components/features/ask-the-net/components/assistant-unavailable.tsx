import Link from "next/link";
import { Info, Loader2 } from "lucide-react";

import type { AiStatus } from "@/components/features/ai-assistant/types/ai-assistant";

interface Explanation {
  message: string;
  /** The user can fix it in their own assistant settings. */
  inSettings: boolean;
}

const EXPLANATIONS: Record<Exclude<AiStatus["reason"], "ok">, Explanation> = {
  operator_disabled: {
    message:
      "The AI assistant is switched off by the operator. Ask an administrator to enable it.",
    inSettings: false,
  },
  no_permission: {
    message: "You do not have permission to use the AI assistant.",
    inSettings: false,
  },
  disabled: {
    message: "You switched the assistant off in your settings.",
    inSettings: true,
  },
  not_configured: {
    message:
      "The assistant is not set up yet: add a provider and an API key in your settings.",
    inSettings: true,
  },
  provider_not_allowed: {
    message:
      "The provider you chose is not allowed by the operator. Pick another one in your settings.",
    inSettings: true,
  },
};

interface AssistantUnavailableProps {
  /** `undefined` while the status is loading or when it could not be read. */
  status: AiStatus | undefined;
  isLoading: boolean;
}

/**
 * Unlike the side panels, which simply stay hidden, this page is only about the assistant, so a
 * user who lands here is told why it is not available.
 */
export function AssistantUnavailable({
  status,
  isLoading,
}: AssistantUnavailableProps) {
  if (isLoading) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        Checking whether the assistant is available…
      </p>
    );
  }
  const explanation =
    status && status.reason !== "ok" ? EXPLANATIONS[status.reason] : undefined;
  return (
    <div className="flex items-start gap-2 rounded-md border bg-muted/40 p-4 text-sm">
      <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="space-y-2">
        <p>
          {explanation?.message ??
            "Could not check whether the assistant is available. Reload the page to try again."}
        </p>
        {explanation?.inSettings ? (
          <Link
            href="/settings/ai-assistant"
            className="underline underline-offset-2"
          >
            Assistant settings
          </Link>
        ) : null}
      </div>
    </div>
  );
}
