"use client";

import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  useCatalystCenterSitesQuery,
  type CatalystCenterSite,
} from "@/hooks/queries/use-catalyst-center-sites-query";

interface CatalystCenterSitesDialogProps {
  open: boolean;
  sourceId: string;
  /** Site name paths already in the filter: shown checked and not selectable again. */
  alreadySelected: readonly string[];
  onClose: () => void;
  onAdd: (nameHierarchies: string[]) => void;
}

function depthOf(site: CatalystCenterSite): number {
  return site.name_hierarchy.split("/").length - 1;
}

export function CatalystCenterSitesDialog({
  open,
  sourceId,
  alreadySelected,
  onClose,
  onAdd,
}: CatalystCenterSitesDialogProps) {
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const [prevOpen, setPrevOpen] = useState(open);
  const { data, isLoading, isError, error, refetch, isFetching } =
    useCatalystCenterSitesQuery(sourceId, { enabled: open });

  // Reset the picker each time it opens (render-phase state sync, like the source dialog).
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setSearch("");
      setPicked(new Set());
    }
  }

  const sites = useMemo(() => data?.sites ?? [], [data]);
  const taken = useMemo(() => new Set(alreadySelected), [alreadySelected]);
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return needle
      ? sites.filter((site) => site.name_hierarchy.toLowerCase().includes(needle))
      : sites;
  }, [sites, search]);

  const toggle = useCallback((hierarchy: string, checked: boolean) => {
    setPicked((current) => {
      const next = new Set(current);
      if (checked) next.add(hierarchy);
      else next.delete(hierarchy);
      return next;
    });
  }, []);

  const handleAdd = useCallback(() => {
    onAdd(sites.filter((s) => picked.has(s.name_hierarchy)).map((s) => s.name_hierarchy));
    onClose();
  }, [onAdd, onClose, picked, sites]);

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Search sites</DialogTitle>
          <DialogDescription>
            Sites configured on{" "}
            <code className="rounded bg-muted px-1 font-mono text-xs">{sourceId}</code>.
            Select the ones to add to the Site filter. Selecting a parent site
            also covers its sub-sites unless include_child_sites is turned off.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <Input
            className="h-8 text-xs"
            placeholder="Filter sites…"
            aria-label="Filter sites"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />

          {isLoading ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              Loading sites from Catalyst Center…
            </p>
          ) : isError ? (
            <div className="space-y-2 rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
              <p>
                Could not load sites:{" "}
                {error instanceof Error ? error.message : "Unknown error"}
              </p>
              <Button
                className="h-7 text-xs"
                size="sm"
                type="button"
                variant="outline"
                disabled={isFetching}
                onClick={() => refetch()}
              >
                Retry
              </Button>
            </div>
          ) : sites.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              This Catalyst Center has no sites configured.
            </p>
          ) : visible.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No site matches “{search.trim()}”.
            </p>
          ) : (
            <div className="max-h-72 divide-y overflow-y-auto rounded-md border text-xs">
              {visible.map((site) => {
                const isTaken = taken.has(site.name_hierarchy);
                const checked = isTaken || picked.has(site.name_hierarchy);
                const id = `cc-site-${site.id}`;
                return (
                  <label
                    key={site.id}
                    htmlFor={id}
                    className="flex cursor-pointer items-center gap-2 px-3 py-1.5 hover:bg-muted/40 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60"
                    style={{ paddingLeft: `${0.75 + depthOf(site) * 0.75}rem` }}
                  >
                    <Checkbox
                      id={id}
                      checked={checked}
                      disabled={isTaken}
                      onCheckedChange={(value) =>
                        toggle(site.name_hierarchy, value === true)
                      }
                    />
                    <span className="font-mono">{site.name}</span>
                    <span className="truncate text-muted-foreground">
                      {site.name_hierarchy}
                    </span>
                    {isTaken && (
                      <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                        added
                      </span>
                    )}
                  </label>
                );
              })}
            </div>
          )}

          {sites.length > 0 && (
            <p className="text-[11px] text-muted-foreground">
              {visible.length} of {sites.length} site{sites.length !== 1 ? "s" : ""}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" disabled={picked.size === 0} onClick={handleAdd}>
            Add selected{picked.size > 0 ? ` (${picked.size})` : ""}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
