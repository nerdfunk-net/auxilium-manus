"use client";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

const MIN_READ_TIMEOUT = 5;
const MAX_READ_TIMEOUT = 600;

export interface DeployReadTimeoutFieldsProps {
  readTimeout: number;
  onReadTimeoutChange: (value: string) => void;
}

export function DeployReadTimeoutFields({
  readTimeout,
  onReadTimeoutChange,
}: DeployReadTimeoutFieldsProps) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">read_timeout</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          integer
        </Badge>
      </div>
      <Input
        type="number"
        min={MIN_READ_TIMEOUT}
        max={MAX_READ_TIMEOUT}
        value={readTimeout}
        onChange={(event) => onReadTimeoutChange(event.target.value)}
        className="h-8 font-mono text-xs"
      />
      <p className="text-[11px] text-muted-foreground">
        Seconds to wait for each command&apos;s response. Raise this if a &ldquo;Pattern not
        detected&rdquo; timeout appears for commands with slow or multi-line output.
      </p>
    </div>
  );
}
