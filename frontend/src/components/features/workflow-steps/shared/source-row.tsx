import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface SourceRowProps {
  /** The config key shown as the field name. */
  label: string;
  /** The integration the source belongs to ("nautobot", "ise"). */
  badge: string;
  sourceId: string;
  onOpen: () => void;
  /** Extra lines under the id (see `NautobotSourceStatus`); shown only with an id. */
  status?: ReactNode;
}

/** The "source status + Configure Source button" block of a step config panel
 * (doc/WORKFLOW-STEPS-STYLE_GUIDE.md "Config panel"). */
export function SourceRow({ label, badge, sourceId, onOpen, status }: SourceRowProps) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">{label}</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          {badge}
        </Badge>
      </div>
      {sourceId ? (
        <p className="font-mono text-[11px] text-muted-foreground">
          {sourceId}
          {status}
        </p>
      ) : (
        <p className="text-[11px] text-warning-foreground">Not configured</p>
      )}
      <Button
        className="h-7 w-full text-xs"
        size="sm"
        type="button"
        variant="outline"
        onClick={onOpen}
      >
        {sourceId ? "Edit Source" : "Configure Source"}
      </Button>
    </div>
  );
}

interface NautobotSourceStatusProps {
  isReady: boolean;
  isLoading: boolean;
  url: string;
}

/** What `useNautobotSourceCredentials` found for the chosen source: its URL, loading, or
 * "not found" (the id is not in the settings). */
export function NautobotSourceStatus({ isReady, isLoading, url }: NautobotSourceStatusProps) {
  if (isReady) {
    return <span className="block truncate font-sans text-muted-foreground">{url}</span>;
  }
  if (isLoading) {
    return <span className="block font-sans">Loading credentials…</span>;
  }
  return (
    <span className="block font-sans text-warning-foreground">Source not found in settings</span>
  );
}
