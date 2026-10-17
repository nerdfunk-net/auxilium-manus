"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import type { VirtualChassisConfig } from "./types";

interface VirtualChassisSectionProps {
  virtualChassis: VirtualChassisConfig;
  onPatch: (patch: Partial<VirtualChassisConfig>) => void;
}

export function VirtualChassisSection({ virtualChassis, onPatch }: VirtualChassisSectionProps) {
  return (
    <section className="space-y-2 border-t pt-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs font-medium">virtual_chassis</span>
      </div>
      <p className="text-[11px] text-muted-foreground">
        Optionally join or create a virtual chassis for this device.
      </p>
      <Select
        value={virtualChassis.mode}
        onValueChange={(mode) => onPatch({ mode: mode as VirtualChassisConfig["mode"] })}
      >
        <SelectTrigger className="h-8 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none">None</SelectItem>
          <SelectItem value="join">Join existing virtual chassis</SelectItem>
          <SelectItem value="create">Create new virtual chassis (device = master)</SelectItem>
        </SelectContent>
      </Select>

      {virtualChassis.mode === "join" ? (
        <div className="space-y-1 pl-1">
          <Label className="text-[11px] text-muted-foreground">Virtual chassis UUID</Label>
          <Input
            className="h-8 font-mono text-xs"
            placeholder="550e8400-e29b-41d4-a716-446655440000"
            value={virtualChassis.id ?? ""}
            onChange={(event) => onPatch({ id: event.target.value })}
          />
        </div>
      ) : null}

      {virtualChassis.mode === "create" ? (
        <div className="space-y-1 pl-1">
          <Label className="text-[11px] text-muted-foreground">New virtual chassis name</Label>
          <Input
            className="h-8 text-xs"
            placeholder="stack-1"
            value={virtualChassis.name ?? ""}
            onChange={(event) => onPatch({ name: event.target.value })}
          />
        </div>
      ) : null}
    </section>
  );
}
