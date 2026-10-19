"use client";

import { Minus, Plus } from "lucide-react";
import { useCallback, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import {
  NETWORK_DRIVER_SUGGESTIONS,
  cleanDeviceField,
  parseDeviceListText,
  serializeDeviceRows,
  type DeviceRow,
} from "../utils/device-list-text";

const CELL_CLASS = "h-8 min-w-0 font-mono text-xs focus-visible:ring-step/40";

interface RunInputDeviceTableFieldProps {
  value: string;
  onChange: (text: string) => void;
  defaultNetworkDriver: string;
}

/**
 * Manual device entry for a `get-from-user` run input: one row per device with a name, an IP
 * address and a network driver. The committed value is the same newline-delimited
 * `name,ip_address,network_driver` text the executor parses.
 */
export function RunInputDeviceTableField({
  value,
  onChange,
  defaultNetworkDriver,
}: RunInputDeviceTableFieldProps) {
  const listId = useId();
  const blankRow = useCallback(
    (): DeviceRow => ({ name: "", ip: "", driver: defaultNetworkDriver }),
    [defaultNetworkDriver],
  );
  // Rows are local state: a half-typed row serializes to nothing and would vanish if the
  // table were derived from the committed text on every keystroke.
  const [rows, setRows] = useState<DeviceRow[]>(() => {
    const parsed = parseDeviceListText(value, defaultNetworkDriver);
    return parsed.length > 0 ? parsed : [{ name: "", ip: "", driver: defaultNetworkDriver }];
  });

  const commit = useCallback(
    (next: DeviceRow[]) => {
      setRows(next);
      onChange(serializeDeviceRows(next));
    },
    [onChange],
  );

  const handleCell = (index: number, field: keyof DeviceRow, cell: string) =>
    commit(
      rows.map((row, i) => (i === index ? { ...row, [field]: cleanDeviceField(cell) } : row)),
    );

  const handleRemove = (index: number) => {
    const next = rows.filter((_, i) => i !== index);
    commit(next.length > 0 ? next : [blankRow()]);
  };

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto] gap-2 text-[11px] text-muted-foreground">
        <span>Name</span>
        <span>IP address</span>
        <span>Network driver</span>
        <span className="size-8" aria-hidden />
      </div>
      {rows.map((row, index) => (
        <div
          key={index}
          className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-2"
        >
          <Input
            className={CELL_CLASS}
            value={row.name}
            placeholder="router1.example.com"
            aria-label={`Device ${index + 1} name`}
            onChange={(event) => handleCell(index, "name", event.target.value)}
          />
          <Input
            className={CELL_CLASS}
            value={row.ip}
            placeholder="10.0.0.5"
            aria-label={`Device ${index + 1} IP address`}
            onChange={(event) => handleCell(index, "ip", event.target.value)}
          />
          <Input
            className={CELL_CLASS}
            value={row.driver}
            list={listId}
            placeholder={defaultNetworkDriver}
            aria-label={`Device ${index + 1} network driver`}
            onChange={(event) => handleCell(index, "driver", event.target.value)}
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8 shrink-0"
            onClick={() => handleRemove(index)}
            title="Remove device"
          >
            <Minus className="size-3.5" />
          </Button>
        </div>
      ))}
      <datalist id={listId}>
        {NETWORK_DRIVER_SUGGESTIONS.map((driver) => (
          <option key={driver} value={driver} />
        ))}
      </datalist>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-7 text-xs"
        onClick={() => commit([...rows, blankRow()])}
      >
        <Plus className="mr-1 size-3.5" /> Add device
      </Button>
    </div>
  );
}
