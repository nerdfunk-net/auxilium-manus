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
import { Switch } from "@/components/ui/switch";

import type { RedundancyGroupsConfig } from "./redundancy-groups";
import {
  REDUNDANCY_GROUP_STATUSES,
  redundancyNameExamples,
  redundancyPatternProblem,
} from "./redundancy-groups";

interface RedundancyGroupsSectionProps {
  value: RedundancyGroupsConfig;
  onChange: (next: RedundancyGroupsConfig) => void;
}

/** HSRP/VRRP groups of the interfaces: switch, name schema and status of new groups. */
export function RedundancyGroupsSection({ value, onChange }: RedundancyGroupsSectionProps) {
  const problem = value.enabled ? redundancyPatternProblem(value.name_pattern) : null;

  return (
    <section className="space-y-3 rounded-xl border border-border bg-card p-3 shadow-sm">
      <div className="flex items-center justify-between">
        <Label className="font-mono text-xs font-medium" htmlFor="redundancy-groups-enabled">
          redundancy_groups
        </Label>
        <Switch
          id="redundancy-groups-enabled"
          aria-label="Write HSRP/VRRP redundancy groups"
          checked={value.enabled}
          onCheckedChange={(checked) => onChange({ ...value, enabled: checked })}
        />
      </div>
      <p className="text-[11px] text-muted-foreground">
        Write the HSRP groups of the interfaces to Nautobot (VRRP only when it is written as
        legacy <span className="font-mono">vrrp &lt;n&gt; ip</span> lines in a Genie running
        config; the IOS-XE <span className="font-mono">address-family</span> form is not read).
        A group that already exists (same protocol, group id and virtual IP) is reused and only
        this interface is added; otherwise a new group is created. Nothing is deleted.
      </p>

      {value.enabled ? (
        <>
          <div className="space-y-1">
            <Label className="text-[11px] text-muted-foreground" htmlFor="redundancy-name-pattern">
              Name of a new group
            </Label>
            <Input
              id="redundancy-name-pattern"
              className="h-8 font-mono text-xs"
              value={value.name_pattern}
              onChange={(event) => onChange({ ...value, name_pattern: event.target.value })}
            />
            {problem ? (
              <p className="text-[11px] text-warning-foreground">{problem}</p>
            ) : (
              <p className="text-[11px] text-muted-foreground">
                <span className="font-mono">{"{next}"}</span> is the lowest free number:{" "}
                <span className="font-mono">{redundancyNameExamples(value.name_pattern)}</span>.{" "}
                <span className="font-mono">{"{protocol}"}</span> is hsrp or vrrp.
              </p>
            )}
          </div>

          <div className="space-y-1">
            <Label className="text-[11px] text-muted-foreground">Status of a new group</Label>
            <Select
              value={value.status}
              onValueChange={(status) => onChange({ ...value, status })}
            >
              <SelectTrigger className="h-8 text-xs" aria-label="Status of a new group">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {REDUNDANCY_GROUP_STATUSES.map((status) => (
                  <SelectItem key={status} value={status}>
                    {status}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </>
      ) : null}
    </section>
  );
}
