"use client";

import { useCallback } from "react";
import {
  CircleHelp,
  Filter,
  FolderOpen,
  Loader2,
  Play,
  Save,
  Settings,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { useGetNautobotDevicesPreviewMutation } from "@/hooks/queries/use-get-nautobot-devices-preview-mutation";

import { ConditionBuilder } from "./condition-builder/condition-builder";
import { treeToOperations } from "./condition-builder/tree-to-operation";
import { countConditions, type FilterTree } from "./condition-builder/types";

interface DeviceFilterCardProps {
  tree: FilterTree;
  nautobot_url: string;
  nautobot_token: string;
  onChange: (tree: FilterTree) => void;
  /** When omitted (e.g. inside the filter modal), Manage Inventory is hidden. */
  onManageInventory?: () => void;
  className?: string;
}

export function DeviceFilterCard({
  tree,
  nautobot_url,
  nautobot_token,
  onChange,
  onManageInventory,
  className,
}: DeviceFilterCardProps) {
  const previewMutation = useGetNautobotDevicesPreviewMutation();
  const hasSource = Boolean(nautobot_url && nautobot_token);
  const conditionCount = countConditions(tree);
  const canPreview = hasSource && conditionCount > 0;

  const handlePreview = useCallback(() => {
    const operations = treeToOperations(tree);
    previewMutation.mutate({ nautobot_url, nautobot_token, operations });
  }, [tree, nautobot_url, nautobot_token, previewMutation]);

  return (
    <div
      className={`flex min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-card shadow-sm ${className ?? ""}`}
    >
      {/* Header — sky blue like legacy inventory builder */}
      <div className="flex items-center justify-between bg-sky-500 px-4 py-2.5 text-white">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Filter className="h-4 w-4 shrink-0" aria-hidden />
          Device Filter
          {conditionCount > 0 ? (
            <span className="rounded-full bg-white/20 px-2 py-0.5 text-[10px] font-medium">
              {conditionCount} condition{conditionCount !== 1 ? "s" : ""}
            </span>
          ) : null}
        </div>
        <button
          className="flex items-center gap-1 text-xs font-medium text-white/90 transition-colors hover:text-white"
          type="button"
          aria-label="Device filter help"
        >
          <CircleHelp className="h-3.5 w-3.5" aria-hidden />
          Help
        </button>
      </div>

      {/* Body */}
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto bg-slate-50/80 p-4">
        {!hasSource ? (
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            {onManageInventory
              ? "Configure a Nautobot source via Manage Inventory to enable value autocomplete and preview."
              : "Configure the Nautobot source in the step properties panel to enable value autocomplete and preview."}
          </p>
        ) : null}

        <ConditionBuilder
          tree={tree}
          nautobot_url={nautobot_url}
          nautobot_token={nautobot_token}
          onChange={onChange}
        />

        {(previewMutation.isPending ||
          previewMutation.data ||
          previewMutation.isError) && (
          <div className="rounded-lg border border-slate-200 bg-white p-3">
            {previewMutation.isPending ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                Querying Nautobot…
              </div>
            ) : null}
            {previewMutation.isError ? (
              <p className="text-xs text-destructive">
                {previewMutation.error.message ??
                  "Preview failed. Check Nautobot connectivity."}
              </p>
            ) : null}
            {previewMutation.data ? (
              <div className="space-y-2">
                <p className="text-xs font-medium text-foreground">
                  {previewMutation.data.total} device
                  {previewMutation.data.total !== 1 ? "s" : ""} found
                </p>
                <div className="max-h-36 overflow-y-auto rounded-md border border-slate-200">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-muted">
                      <tr>
                        <th className="px-2 py-1.5 text-left font-medium">Name</th>
                        <th className="px-2 py-1.5 text-left font-medium">Location</th>
                        <th className="px-2 py-1.5 text-left font-medium">Role</th>
                        <th className="px-2 py-1.5 text-left font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previewMutation.data.devices.slice(0, 50).map((device) => (
                        <tr className="border-t border-slate-100" key={device.id}>
                          <td className="px-2 py-1">{device.name ?? "—"}</td>
                          <td className="px-2 py-1 text-muted-foreground">
                            {device.location ?? "—"}
                          </td>
                          <td className="px-2 py-1 text-muted-foreground">
                            {device.role ?? "—"}
                          </td>
                          <td className="px-2 py-1 text-muted-foreground">
                            {device.status ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {previewMutation.data.total > 50 ? (
                    <p className="px-2 py-1 text-center text-[10px] text-muted-foreground">
                      Showing first 50 of {previewMutation.data.total}
                    </p>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>
        )}
      </div>

      {/* Footer actions */}
      <div className="flex flex-wrap items-center gap-2 border-t border-slate-200 bg-white px-4 py-3">
        <Button
          className="h-8 gap-1.5 rounded-lg text-xs"
          disabled={!canPreview || previewMutation.isPending}
          onClick={handlePreview}
          size="sm"
          type="button"
          variant="secondary"
        >
          {previewMutation.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <Play className="h-3.5 w-3.5" aria-hidden />
          )}
          Preview Results
        </Button>
        <Button
          className="h-8 gap-1.5 rounded-lg text-xs"
          disabled
          size="sm"
          title="Filter is saved automatically with the workflow step"
          type="button"
          variant="secondary"
        >
          <Save className="h-3.5 w-3.5" aria-hidden />
          Save
        </Button>
        <Button
          className="h-8 gap-1.5 rounded-lg text-xs"
          disabled
          size="sm"
          title="Coming soon"
          type="button"
          variant="secondary"
        >
          <Save className="h-3.5 w-3.5" aria-hidden />
          Save as
        </Button>
        <Button
          className="h-8 gap-1.5 rounded-lg border-slate-300 text-xs"
          disabled
          size="sm"
          title="Coming soon"
          type="button"
          variant="outline"
        >
          <FolderOpen className="h-3.5 w-3.5" aria-hidden />
          Load
        </Button>
        {onManageInventory ? (
          <Button
            className="ml-auto h-8 gap-1.5 rounded-lg border-violet-400 text-xs text-violet-700 hover:bg-violet-50 hover:text-violet-800"
            onClick={onManageInventory}
            size="sm"
            type="button"
            variant="outline"
          >
            <Settings className="h-3.5 w-3.5 text-violet-600" aria-hidden />
            Manage Inventory
          </Button>
        ) : null}
      </div>
    </div>
  );
}
