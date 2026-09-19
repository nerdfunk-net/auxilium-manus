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
import {
  NautobotInterfaceRow,
  type NautobotInterfaceRowValues,
} from "@/components/features/workflow-steps/shared/nautobot-field-rows";

export type InterfacesSource = "manual" | "nautobot_origin";

export interface InterfaceRowConfig {
  id?: string;
  name: string;
  type?: string;
  status?: string;
  ip_address?: string;
  namespace?: string;
  description?: string;
  is_primary_ipv4?: boolean;
}

interface InterfacesSourceSectionProps<T extends InterfaceRowConfig> {
  interfaces: T[];
  interfacesSource: InterfacesSource;
  onSourceChange: (source: InterfacesSource) => void;
  onAddInterface: () => void;
  onPatchInterface: (id: string, patch: Partial<T>) => void;
  onRemoveInterface: (id: string) => void;
  /** Shown under the "Nautobot origin" select when that source is active. */
  originDescription?: string;
}

const DEFAULT_ORIGIN_DESCRIPTION =
  "Every interface present in the device's nautobot attribute bag is used — however " +
  "many there are, each with however many IP addresses it has. The rows below are " +
  "ignored while this is selected.";

export function InterfacesSourceSection<T extends InterfaceRowConfig>({
  interfaces,
  interfacesSource,
  onSourceChange,
  onAddInterface,
  onPatchInterface,
  onRemoveInterface,
  originDescription = DEFAULT_ORIGIN_DESCRIPTION,
}: InterfacesSourceSectionProps<T>) {
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
        <p className="text-[11px] text-muted-foreground">{originDescription}</p>
      ) : interfaces.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">No interfaces configured.</p>
      ) : (
        <div className="space-y-3">
          {interfaces.map((iface) => {
            const rowId = iface.id ?? iface.name;
            const rowValues: NautobotInterfaceRowValues = {
              id: rowId,
              name: iface.name,
              type: iface.type,
              status: iface.status,
              ip_address: iface.ip_address,
              namespace: iface.namespace ?? "Global",
              description: iface.description,
              is_primary_ipv4: iface.is_primary_ipv4,
            };
            return (
              <NautobotInterfaceRow
                key={rowId}
                row={rowValues}
                onChange={(patch) => onPatchInterface(rowId, patch as Partial<T>)}
                onRemove={() => onRemoveInterface(rowId)}
              />
            );
          })}
        </div>
      )}
    </section>
  );
}
