"use client";

import { Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { NautobotInterfaceRow } from "@/components/features/workflow-steps/shared/nautobot-field-rows";

import type { InterfaceCreateConfig, InterfacesSource } from "./types";

interface InterfacesSectionProps {
  interfaces: InterfaceCreateConfig[];
  interfacesSource: InterfacesSource;
  onSourceChange: (source: InterfacesSource) => void;
  onAddInterface: () => void;
  onPatchInterface: (id: string, patch: Partial<InterfaceCreateConfig>) => void;
  onRemoveInterface: (id: string) => void;
}

export function InterfacesSection({
  interfaces,
  interfacesSource,
  onSourceChange,
  onAddInterface,
  onPatchInterface,
  onRemoveInterface,
}: InterfacesSectionProps) {
  return (
    <section className="space-y-3 rounded-xl border border-border bg-card p-3 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-medium">interfaces</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            object_list
          </Badge>
        </div>
        {interfacesSource === "manual" ? (
          <Button
            className="h-7 bg-step text-step-foreground hover:bg-step-hover"
            size="sm"
            type="button"
            onClick={onAddInterface}
          >
            <Plus className="mr-1 size-3.5" />
            Add
          </Button>
        ) : null}
      </div>

      <Select
        value={interfacesSource}
        onValueChange={(source) => onSourceChange(source as InterfacesSource)}
      >
        <SelectTrigger className="h-8 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="manual">Manual — rows below</SelectItem>
          <SelectItem value="nautobot_origin">All from Nautobot origin</SelectItem>
        </SelectContent>
      </Select>

      {interfacesSource === "nautobot_origin" ? (
        <p className="text-[11px] text-muted-foreground">
          Every interface present in the device&apos;s nautobot attribute bag is created — however
          many there are, each with however many IP addresses it has. The rows below are ignored
          while this is selected.
        </p>
      ) : interfaces.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">No interfaces configured.</p>
      ) : (
        <div className="space-y-3">
          {interfaces.map((iface) => {
            const rowId = iface.id ?? iface.name;
            return (
              <NautobotInterfaceRow
                key={rowId}
                row={{
                  id: rowId,
                  name: iface.name,
                  type: iface.type,
                  status: iface.status,
                  ip_address: iface.ip_address,
                  namespace: iface.namespace ?? "Global",
                  description: iface.description,
                  is_primary_ipv4: iface.is_primary_ipv4,
                }}
                onChange={(patch) => onPatchInterface(rowId, patch)}
                onRemove={() => onRemoveInterface(rowId)}
              />
            );
          })}
        </div>
      )}
    </section>
  );
}
