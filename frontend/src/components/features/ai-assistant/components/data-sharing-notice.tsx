"use client";

import Link from "next/link";
import { ShieldAlert, ShieldCheck } from "lucide-react";

import { useAiSettingsQuery } from "@/hooks/queries/use-ai-settings-query";

import { PROVIDER_LABELS } from "../constants/providers";

/**
 * Shows which provider receives the conversation and which device/run-derived data classes the
 * user has allowed (doc/ai_integration/AI_ASSISTANT.md §4.2). Changing them takes effect on the
 * next turn because the server reads the saved settings on every request.
 */
export function DataSharingNotice() {
  const { data: settings } = useAiSettingsQuery();
  if (!settings) {
    return null;
  }
  const shared = [
    settings.share_inventory_data ? "inventory data" : null,
    settings.share_content_data ? "run and device content" : null,
  ].filter((item): item is string => item !== null);
  const Icon = shared.length > 0 ? ShieldAlert : ShieldCheck;

  return (
    <p className="flex items-start gap-2 rounded-md border bg-muted/40 p-2 text-xs text-muted-foreground">
      <Icon className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <span>
        Sent to {PROVIDER_LABELS[settings.provider]}:{" "}
        {shared.length > 0
          ? `${shared.join(" and ")} (best-effort redaction)`
          : "definitions only, no device or run data"}
        .{" "}
        <Link
          href="/settings/ai-assistant"
          className="underline underline-offset-2"
        >
          Change
        </Link>
      </span>
    </p>
  );
}
