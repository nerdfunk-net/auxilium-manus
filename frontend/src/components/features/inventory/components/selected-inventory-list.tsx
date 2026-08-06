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
    <div className="rounded-lg border-0 bg-white p-0 shadow-lg">
      <div className="flex items-center justify-between rounded-t-lg bg-gradient-to-r from-teal-500/80 to-teal-600/80 px-4 py-2 text-white">
        <div className="flex items-center space-x-2">
          <ListChecks className="h-4 w-4" />
          <span className="text-sm font-medium">Selected Inventory</span>
        </div>
        <div className="text-xs text-teal-100">
          {devices.length} device{devices.length !== 1 ? "s" : ""}
        </div>
      </div>
      <div className="bg-gradient-to-b from-white to-gray-50 p-6">
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
                  <td className="py-8 text-center text-gray-500" colSpan={6}>
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
                        className="h-6 w-6 text-red-600 hover:text-red-800"
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
            className="flex items-center space-x-2 text-red-600 hover:bg-red-50 hover:text-red-700"
            disabled={removalSelectedIds.size === 0}
            onClick={onRemoveSelected}
            type="button"
            variant="outline"
          >
            <Trash2 className="h-4 w-4" />
            <span>Remove Selected Devices</span>
          </Button>
          <Button
            className="flex items-center space-x-2 border-0 bg-teal-600 text-white hover:bg-teal-700 disabled:bg-gray-400"
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
