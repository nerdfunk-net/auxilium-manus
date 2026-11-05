"use client";

import { Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import type { NewInterfaceTypeMode, ParsedListConfig, ParsedListFieldKey } from "./types";
import { PARSED_LIST_FIELD_DEFINITIONS, PARSED_LIST_FIXED_FIELDS } from "./types";
import { parsedListProblem } from "./update-device-config";

interface ParsedListSectionProps {
  value: ParsedListConfig;
  onChange: (next: ParsedListConfig) => void;
  /** Opens the attribute picker; the chosen path becomes ``source_path``. */
  onBrowse: () => void;
}

const NEW_TYPE_DESCRIPTIONS: Record<NewInterfaceTypeMode, string> = {
  none: "Interfaces that do not exist in Nautobot are skipped with a warning.",
  infer:
    "Ethernet/GigabitEthernet… → 1000base-t, Loopback/Vlan/Tunnel → virtual, Port-channel → lag, " +
    "an unknown name → other. Existing interfaces keep their type.",
  fixed: "Every new interface gets this type. Existing interfaces keep their type.",
};

const FIXED_LABELS: Partial<Record<ParsedListFieldKey, string>> = {
  port_type: "Port type for every row",
  mode: "802.1Q mode for every row",
  duplex: "Duplex for every row",
  vrf: "VRF for every row (must exist in Nautobot)",
};

/**
 * Maps the columns of a parsed list (for example TextFSM ``show interfaces`` output) to
 * interface fields, so one step updates every interface of a device.
 */
export function ParsedListSection({ value, onChange, onBrowse }: ParsedListSectionProps) {
  const problem = parsedListProblem(value);

  const patchMap = (
    which: "field_map" | "fixed_values",
    key: ParsedListFieldKey,
    text: string,
  ) => {
    onChange({ ...value, [which]: { ...value[which], [key]: text } });
  };

  return (
    <div className="space-y-3">
      <p className="text-[11px] text-muted-foreground">
        Reads a list of objects from the device (for example the TextFSM output of{" "}
        <span className="font-mono">show interfaces</span>) and updates one Nautobot
        interface per row. Blank cells are skipped, so existing Nautobot values are not
        wiped; interfaces that do not exist are only created when you choose a type for new
        interfaces below.
      </p>

      <div className="space-y-1">
        <Label className="text-[11px] text-muted-foreground">List to read (source path)</Label>
        <div className="flex items-center gap-1.5">
          <Input
            className="h-8 font-mono text-xs"
            placeholder="parsed.show_interfaces.parsed"
            value={value.source_path}
            onChange={(event) => onChange({ ...value, source_path: event.target.value })}
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8 shrink-0"
            onClick={onBrowse}
            title="Browse attributes"
          >
            <Search className="size-3.5" />
          </Button>
        </div>
      </div>

      <div className="space-y-2 rounded-lg border border-border bg-muted p-3">
        <span className="text-xs font-medium text-step-muted-foreground">
          Column of the list for each interface field
        </span>
        <div className="grid gap-2 sm:grid-cols-2">
          {PARSED_LIST_FIELD_DEFINITIONS.map((definition) => (
            <div key={definition.key} className="space-y-1">
              <Label className="text-[11px] text-muted-foreground">
                {definition.label}
                {"required" in definition && definition.required ? " *" : ""}
              </Label>
              <Input
                className="h-8 font-mono text-xs"
                placeholder={definition.placeholder}
                value={value.field_map[definition.key] ?? ""}
                onChange={(event) => patchMap("field_map", definition.key, event.target.value)}
              />
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-2 rounded-lg border border-border bg-muted p-3">
        <span className="text-xs font-medium text-step-muted-foreground">
          Fixed values (same for every row, existing interfaces too)
        </span>
        <div className="grid gap-2 sm:grid-cols-2">
          {PARSED_LIST_FIXED_FIELDS.map((key) => (
            <div key={key} className="space-y-1">
              <Label className="text-[11px] text-muted-foreground">{FIXED_LABELS[key]}</Label>
              <Input
                className="h-8 text-xs"
                placeholder={key === "type" ? "1000base-t" : ""}
                value={value.fixed_values[key] ?? ""}
                onChange={(event) => patchMap("fixed_values", key, event.target.value)}
              />
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-2 rounded-lg border border-border bg-muted p-3">
        <span className="text-xs font-medium text-step-muted-foreground">
          Type for new interfaces
        </span>
        <Select
          value={value.new_interface_type.mode}
          onValueChange={(mode) =>
            onChange({
              ...value,
              new_interface_type: { ...value.new_interface_type, mode: mode as NewInterfaceTypeMode },
            })
          }
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">Do not create missing interfaces</SelectItem>
            <SelectItem value="infer">Create, type guessed from the interface name</SelectItem>
            <SelectItem value="fixed">Create, always with this type</SelectItem>
          </SelectContent>
        </Select>
        {value.new_interface_type.mode === "fixed" ? (
          <Input
            className="h-8 font-mono text-xs"
            placeholder="1000base-t"
            value={value.new_interface_type.value}
            onChange={(event) =>
              onChange({
                ...value,
                new_interface_type: { ...value.new_interface_type, value: event.target.value },
              })
            }
          />
        ) : null}
        <p className="text-[11px] text-muted-foreground">
          {NEW_TYPE_DESCRIPTIONS[value.new_interface_type.mode]}
        </p>
      </div>

      {problem ? <p className="text-[11px] text-warning-foreground">{problem}</p> : null}
    </div>
  );
}
