"use client";

import { Badge } from "@/components/ui/badge";
import type { Capability } from "@/lib/capability-types";

export function CapabilityBadges({ capabilities }: { capabilities: Capability[] }) {
  if (capabilities.length === 0) {
    return <span className="text-xs text-muted-foreground">none</span>;
  }

  return (
    <div className="flex flex-wrap gap-1">
      {capabilities.map((cap) => (
        <Badge key={cap} className="font-mono text-[10px]" variant="secondary">
          {cap}
        </Badge>
      ))}
    </div>
  );
}
