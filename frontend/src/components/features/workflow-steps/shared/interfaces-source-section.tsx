"use client";

import type { ReactNode } from "react";
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

export type InterfacesSource = "manual" | "nautobot_origin" | "parsed_list";

export interface InterfaceRowConfig {
  id?: string;
  name: string;
  type?: string;
  status?: string;
  ip_address?: string;
  namespace?: string;
  description?: string;
  is_primary_ipv4?: boolean;
  mac_address?: string;
  port_type?: string;
  mode?: string;
  speed?: string;
  duplex?: string;
  mtu?: string;
  vrf?: string;
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
  /**
   * Offers the "Parsed list" source and renders this content while it is selected.
   * Leave undefined for steps that do not support it.
   */
  parsedListContent?: ReactNode;
  /** Show MAC address, port type, mode, speed, duplex, MTU and VRF in the manual rows. */
  showExtendedFields?: boolean;
  /** Sources that cannot be chosen right now (shown disabled). The selected one stays visible. */
  unavailableSources?: ReadonlyArray<InterfacesSource>;
}

const NO_UNAVAILABLE_SOURCES: ReadonlyArray<InterfacesSource> = [];

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
  parsedListContent,
  showExtendedFields = false,
  unavailableSources = NO_UNAVAILABLE_SOURCES,
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
          <SelectItem
            value="nautobot_origin"
            disabled={unavailableSources.includes("nautobot_origin")}
          >
            All from Nautobot origin
          </SelectItem>
          {parsedListContent !== undefined ? (
            <SelectItem value="parsed_list" disabled={unavailableSources.includes("parsed_list")}>
              From a parsed list (e.g. TextFSM)
            </SelectItem>
          ) : null}
        </SelectContent>
      </Select>

      {interfacesSource === "nautobot_origin" ? (
        <p className="text-[11px] text-muted-foreground">{originDescription}</p>
      ) : interfacesSource === "parsed_list" && parsedListContent !== undefined ? (
        parsedListContent
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
              mac_address: iface.mac_address,
              port_type: iface.port_type,
              mode: iface.mode,
              speed: iface.speed,
              duplex: iface.duplex,
              mtu: iface.mtu,
              vrf: iface.vrf,
            };
            return (
              <NautobotInterfaceRow
                key={rowId}
                row={rowValues}
                onChange={(patch) => onPatchInterface(rowId, patch as Partial<T>)}
                onRemove={() => onRemoveInterface(rowId)}
                showExtendedFields={showExtendedFields}
              />
            );
          })}
        </div>
      )}
    </section>
  );
}
