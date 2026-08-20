"use client";

import { Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NautobotInterfaceRow } from "@/components/features/workflow-steps/shared/nautobot-field-rows";

import type { InterfaceUpdateConfig } from "./types";

interface InterfacesSectionProps {
  interfaces: InterfaceUpdateConfig[];
  onAddInterface: () => void;
  onPatchInterface: (id: string, patch: Partial<InterfaceUpdateConfig>) => void;
  onRemoveInterface: (id: string) => void;
}

export function InterfacesSection({
  interfaces,
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
        <Button
          className="h-7 bg-step text-step-foreground hover:bg-step-hover"
          size="sm"
          type="button"
          onClick={onAddInterface}
        >
          <Plus className="mr-1 size-3.5" />
          Add
        </Button>
      </div>

      {interfaces.length === 0 ? (
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
