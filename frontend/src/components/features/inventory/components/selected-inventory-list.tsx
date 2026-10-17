"use client";

import { ListChecks, Minus, Save, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";

import type { DeviceInfo } from "../types/device-selector";
import { formatDeviceValue, getStatusColor } from "../utils/device-format";

interface SelectedInventoryListProps {
  devices: DeviceInfo[];
  removalSelectedIds: Set<string>;
  onToggleRemovalSelect: (id: string, checked: boolean) => void;
  onSelectAllForRemoval: (checked: boolean) => void;
  onRemoveDevice: (id: string) => void;
  onRemoveSelected: () => void;
  onSave: () => void;
  isSaving?: boolean;
}

export function SelectedInventoryList({
  devices,
  removalSelectedIds,
  onToggleRemovalSelect,
  onSelectAllForRemoval,
  onRemoveDevice,
  onRemoveSelected,
  onSave,
  isSaving = false,
}: SelectedInventoryListProps) {
  const allSelected = devices.length > 0 && devices.every((d) => removalSelectedIds.has(d.id));

  return (
    <div className="rounded-lg border-0 bg-card p-0 shadow-lg">
      <div className="flex items-center justify-between rounded-t-lg step-header px-4 py-2">
        <div className="flex items-center space-x-2">
          <ListChecks className="h-4 w-4" />
          <span className="text-sm font-medium">Selected Inventory</span>
        </div>
        <div className="text-xs text-step-header-muted">
          {devices.length} device{devices.length !== 1 ? "s" : ""}
        </div>
      </div>
      <div className="bg-gradient-to-b from-card to-muted p-6">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="w-10 p-2"> </th>
                <th className="w-10 p-2">
                  <Checkbox
                    aria-label="Select all devices"
                    checked={allSelected}
                    onCheckedChange={(checked) => onSelectAllForRemoval(checked === true)}
                  />
                </th>
                <th className="p-2 font-medium">Host Name</th>
                <th className="p-2 font-medium">IP Address</th>
                <th className="p-2 font-medium">Location</th>
                <th className="p-2 font-medium">Role</th>
                <th className="p-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {devices.length === 0 ? (
                <tr>
                  <td className="py-8 text-center text-muted-foreground" colSpan={6}>
                    No devices added yet. Preview results and use &quot;Add Devices to
                    selection&quot; to build this list.
                  </td>
                </tr>
              ) : (
                devices.map((device) => (
                  <tr className="border-b last:border-0" key={device.id}>
                    <td className="p-2">
                      <Button
                        aria-label={`Remove device ${device.name}`}
                        className="h-6 w-6 text-error-foreground hover:text-error-foreground"
                        onClick={() => onRemoveDevice(device.id)}
                        size="icon"
                        type="button"
                        variant="ghost"
                      >
                        <Minus className="h-4 w-4" />
                      </Button>
                    </td>
                    <td className="p-2">
                      <Checkbox
                        aria-label={`Select device ${device.name}`}
                        checked={removalSelectedIds.has(device.id)}
                        onCheckedChange={(checked) =>
                          onToggleRemovalSelect(device.id, checked === true)
                        }
                      />
                    </td>
                    <td className="p-2 font-medium">{device.name || "Unnamed Device"}</td>
                    <td className="p-2">{formatDeviceValue(device.primary_ip4)}</td>
                    <td className="p-2">{device.location || "N/A"}</td>
                    <td className="p-2">{device.role || "N/A"}</td>
                    <td className="p-2">
                      <Badge className={getStatusColor(device.status || "")}>
                        {device.status || "Unknown"}
                      </Badge>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-4 flex items-center justify-between border-t pt-4">
          <Button
            className="flex items-center space-x-2 text-error-foreground hover:bg-error hover:text-error-foreground"
            disabled={removalSelectedIds.size === 0}
            onClick={onRemoveSelected}
            type="button"
            variant="outline"
          >
            <Trash2 className="h-4 w-4" />
            <span>Remove Selected Devices</span>
          </Button>
          <Button
            className="flex items-center space-x-2 border-0 bg-step-hover text-step-foreground hover:bg-step-hover/90 disabled:bg-muted-foreground"
            disabled={devices.length === 0 || isSaving}
            onClick={onSave}
            type="button"
          >
            <Save className="h-4 w-4" />
            <span>{isSaving ? "Saving..." : "Save List of Devices"}</span>
          </Button>
        </div>
      </div>
    </div>
  );
}
