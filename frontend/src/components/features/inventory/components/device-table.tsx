"use client";

import { ChevronLeft, ChevronRight, Database } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import type { DeviceInfo } from "../types/device-selector";

interface DeviceTableProps {
  devices: DeviceInfo[];
  totalDevices: number;
  operationsExecuted: number;
  showPreviewResults: boolean;
  enableSelection?: boolean;
  selectedIds: Set<string>;
  onSelectAll: (checked: boolean) => void;
  onSelectDevice: (id: string, checked: boolean) => void;
  onClearSelection: () => void;
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  pageSize: number;
  setPageSize: (size: number) => void;
  currentPageDevices: DeviceInfo[];
}

export function DeviceTable({
  devices,
  totalDevices,
  operationsExecuted,
  showPreviewResults,
  enableSelection,
  selectedIds,
  onSelectAll,
  onSelectDevice,
  onClearSelection,
  currentPage,
  totalPages,
  onPageChange,
  pageSize,
  setPageSize,
  currentPageDevices,
}: DeviceTableProps) {
  if (!showPreviewResults && devices.length === 0) return null;

  const formatDeviceValue = (
    value: string | { name?: string; address?: string } | null | undefined,
  ) => {
    if (!value) return "N/A";
    if (typeof value === "object") {
      return value.name || value.address?.split("/")[0] || "N/A";
    }
    return value;
  };

  const getStatusColor = (status: string) => {
    switch (status?.toLowerCase()) {
      case "active":
        return "bg-green-100 text-green-800";
      case "planned":
        return "bg-blue-100 text-blue-800";
      case "staged":
        return "bg-yellow-100 text-yellow-800";
      case "failed":
        return "bg-red-100 text-red-800";
      case "offline":
        return "bg-gray-100 text-gray-800";
      default:
        return "bg-blue-100 text-blue-800";
    }
  };

  return (
    <div className="rounded-lg border-0 bg-white p-0 shadow-lg">
      <div className="flex items-center justify-between rounded-t-lg bg-gradient-to-r from-blue-400/80 to-blue-500/80 px-4 py-2 text-white">
        <div className="flex items-center space-x-2">
          <Database className="h-4 w-4" />
          <span className="text-sm font-medium">Preview Results</span>
        </div>
        <div className="text-xs text-blue-100">
          {totalDevices} devices found ({operationsExecuted} queries executed)
        </div>
      </div>
      <div className="bg-gradient-to-b from-white to-gray-50 p-6">
        {enableSelection && selectedIds.size > 0 ? (
          <div className="mb-4 flex items-center justify-between rounded-md border border-purple-200 bg-purple-50 p-3">
            <p className="text-sm text-purple-800">
              <strong>{selectedIds.size}</strong> device
              {selectedIds.size !== 1 ? "s" : ""} selected for command execution
            </p>
            <Button
              className="text-purple-600 hover:text-purple-800"
              onClick={onClearSelection}
              size="sm"
              type="button"
              variant="ghost"
            >
              Clear Selection
            </Button>
          </div>
        ) : null}
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                {enableSelection ? <th className="w-12 p-2"> </th> : null}
                <th className="p-2 font-medium">Host Name</th>
                <th className="p-2 font-medium">IP Address</th>
                <th className="p-2 font-medium">Location</th>
                <th className="p-2 font-medium">Role</th>
                <th className="p-2 font-medium">Type</th>
                <th className="p-2 font-medium">Tags</th>
                <th className="p-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {currentPageDevices.length === 0 ? (
                <tr>
                  <td
                    className="py-8 text-center text-gray-500"
                    colSpan={enableSelection ? 8 : 7}
                  >
                    No devices found matching the criteria.
                  </td>
                </tr>
              ) : (
                currentPageDevices.map((device) => (
                  <tr className="border-b last:border-0" key={device.id}>
                    {enableSelection ? (
                      <td className="p-2">
                        <input
                          aria-label={`Select device ${device.name}`}
                          checked={selectedIds.has(device.id)}
                          className="h-4 w-4 rounded border-gray-300"
                          onChange={(e) => onSelectDevice(device.id, e.target.checked)}
                          type="checkbox"
                        />
                      </td>
                    ) : null}
                    <td className="p-2 font-medium">{device.name || "Unnamed Device"}</td>
                    <td className="p-2">{formatDeviceValue(device.primary_ip4)}</td>
                    <td className="p-2">{device.location || "N/A"}</td>
                    <td className="p-2">{device.role || "N/A"}</td>
                    <td className="p-2">{formatDeviceValue(device.device_type)}</td>
                    <td className="p-2">
                      <div className="flex flex-wrap gap-1">
                        {device.tags && device.tags.length > 0 ? (
                          device.tags.slice(0, 3).map((tag) => (
                            <Badge className="h-5 px-1 py-0 text-xs" key={tag} variant="secondary">
                              {tag.split(":")[1] || tag}
                            </Badge>
                          ))
                        ) : (
                          <span className="text-xs text-gray-400">-</span>
                        )}
                        {device.tags && device.tags.length > 3 ? (
                          <Badge className="h-5 px-1 py-0 text-xs" variant="outline">
                            +{device.tags.length - 3}
                          </Badge>
                        ) : null}
                      </div>
                    </td>
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

        {totalDevices > 0 ? (
          <div className="mt-4 flex items-center justify-between border-t pt-4">
            <div className="text-sm text-gray-500">
              Showing {(currentPage - 1) * pageSize + 1} to{" "}
              {Math.min(currentPage * pageSize, totalDevices)} of {totalDevices} entries
            </div>
            <div className="flex items-center space-x-2">
              {enableSelection ? (
                <label className="mr-2 flex items-center gap-2 text-sm text-muted-foreground">
                  <input
                    checked={
                      currentPageDevices.length > 0 &&
                      currentPageDevices.every((d) => selectedIds.has(d.id))
                    }
                    className="h-4 w-4 rounded border-gray-300"
                    onChange={(e) => onSelectAll(e.target.checked)}
                    type="checkbox"
                  />
                  Select page
                </label>
              ) : null}
              <Button
                disabled={currentPage === 1}
                onClick={() => onPageChange(currentPage - 1)}
                size="sm"
                type="button"
                variant="outline"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <div className="flex items-center space-x-1">
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  let pageNum = currentPage;
                  if (totalPages <= 5) {
                    pageNum = i + 1;
                  } else if (currentPage <= 3) {
                    pageNum = i + 1;
                  } else if (currentPage >= totalPages - 2) {
                    pageNum = totalPages - 4 + i;
                  } else {
                    pageNum = currentPage - 2 + i;
                  }

                  return (
                    <Button
                      className="h-8 w-8 p-0"
                      key={pageNum}
                      onClick={() => onPageChange(pageNum)}
                      size="sm"
                      type="button"
                      variant={currentPage === pageNum ? "default" : "outline"}
                    >
                      {pageNum}
                    </Button>
                  );
                })}
              </div>
              <Button
                disabled={currentPage === totalPages}
                onClick={() => onPageChange(currentPage + 1)}
                size="sm"
                type="button"
                variant="outline"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
              <div className="ml-4 flex items-center gap-2">
                <span className="text-sm text-gray-500">Rows per page:</span>
                <Select
                  onValueChange={(val) => setPageSize(parseInt(val, 10))}
                  value={pageSize.toString()}
                >
                  <SelectTrigger className="h-8 w-16">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="10">10</SelectItem>
                    <SelectItem value="20">20</SelectItem>
                    <SelectItem value="50">50</SelectItem>
                    <SelectItem value="100">100</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
