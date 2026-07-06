"use client";

import Link from "next/link";
import { AlertCircle, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";

interface NautobotSourceBannerProps {
  isLoading: boolean;
  hasSources: boolean;
  isReady: boolean;
  sourceId?: string;
}

export function NautobotSourceBanner({
  isLoading,
  hasSources,
  isReady,
  sourceId,
}: NautobotSourceBannerProps) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Resolving Nautobot source...
      </div>
    );
  }

  if (!hasSources) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        <div className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>
            No Nautobot source is configured. Add one in Settings to enable preview and
            field autocomplete.
          </span>
        </div>
        <Button asChild size="sm" type="button" variant="outline">
          <Link href="/settings/sources">Open Settings</Link>
        </Button>
      </div>
    );
  }

  if (!isReady) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        <div className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>
            Nautobot source <strong>{sourceId}</strong> is missing URL or token. Update it in
            Settings.
          </span>
        </div>
        <Button asChild size="sm" type="button" variant="outline">
          <Link href="/settings/sources">Open Settings</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-muted/30 px-4 py-2 text-sm text-muted-foreground">
      Using Nautobot source: <strong className="text-foreground">{sourceId}</strong>
      {" · "}
      <Link
        className="text-primary underline-offset-4 hover:underline"
        href="/settings/sources"
      >
        Change in Settings
      </Link>
    </div>
  );
}
