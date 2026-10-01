"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useIseNetworkDeviceGroupsQuery } from "@/hooks/queries/use-ise-network-device-groups-query";

interface IseDeviceGroupPickerDialogProps {
  open: boolean;
  sourceId: string;
  /** Group names already present in the step config (shown disabled). */
  selectedGroups: string[];
  onClose: () => void;
  onSelect: (groupName: string) => void;
}

export function IseDeviceGroupPickerDialog({
  open,
  sourceId,
  selectedGroups,
  onClose,
  onSelect,
}: IseDeviceGroupPickerDialogProps) {
  const [search, setSearch] = useState("");
  const { data, isFetching, error, refetch } = useIseNetworkDeviceGroupsQuery(
    sourceId,
    {
      enabled: open,
    },
  );

  const groups = useMemo(() => {
    const term = search.trim().toLowerCase();
    const all = data?.groups ?? [];
    return term
      ? all.filter((group) => group.name.toLowerCase().includes(term))
      : all;
  }, [data, search]);

  const selected = useMemo(() => new Set(selectedGroups), [selectedGroups]);

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>ISE network device groups</DialogTitle>
          <DialogDescription>
            Groups configured on ISE source{" "}
            <span className="font-mono">{sourceId}</span>. Click one to add its
            full name to <span className="font-mono">device_groups</span>.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Input
            className="h-8 text-xs"
            placeholder="Filter groups…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />

          {isFetching && !data ? (
            <p className="text-sm text-muted-foreground">Loading groups…</p>
          ) : error ? (
            <p className="text-sm text-destructive">{error.message}</p>
          ) : groups.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {data?.groups.length
                ? "No groups match the filter."
                : "ISE returned no groups."}
            </p>
          ) : (
            <ul className="max-h-80 space-y-1 overflow-y-auto rounded-md border p-1">
              {groups.map((group) => {
                const added = selected.has(group.name);
                return (
                  <li key={group.id ?? group.name}>
                    <button
                      type="button"
                      disabled={added}
                      onClick={() => onSelect(group.name)}
                      className="flex w-full flex-col items-start rounded px-2 py-1.5 text-left hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <span className="font-mono text-xs">{group.name}</span>
                      {group.description && (
                        <span className="text-[11px] text-muted-foreground">
                          {group.description}
                        </span>
                      )}
                      {added && (
                        <span className="text-[11px] text-muted-foreground">
                          Already added
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          {data?.truncated && (
            <p className="text-[11px] text-warning-foreground">
              ISE has more groups than could be loaded; use the filter or type
              the name manually.
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={isFetching}
            onClick={() => refetch()}
          >
            Refresh
          </Button>
          <Button type="button" variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
