"use client";

import { Search } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  type NautobotJobSummary,
  useNautobotJobsQuery,
} from "@/hooks/queries/use-nautobot-jobs-query";

interface SelectJobDialogProps {
  open: boolean;
  sourceId: string;
  onClose: () => void;
  onSelect: (job: NautobotJobSummary) => void;
}

export function SelectJobDialog({ open, sourceId, onClose, onSelect }: SelectJobDialogProps) {
  const [search, setSearch] = useState("");
  const [enabledOnly, setEnabledOnly] = useState(true);

  const { data: jobs, isLoading } = useNautobotJobsQuery({
    sourceId,
    enabledOnly,
    enabled: open,
  });

  const term = search.trim().toLowerCase();
  const visibleJobs = (jobs ?? []).filter((job) => {
    if (!term) return true;
    return (
      job.name.toLowerCase().includes(term) ||
      (job.module_name ?? "").toLowerCase().includes(term) ||
      (job.grouping ?? "").toLowerCase().includes(term)
    );
  });

  const handleSelect = (job: NautobotJobSummary) => {
    onSelect(job);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Select Nautobot job</DialogTitle>
          <DialogDescription>
            Jobs installed on the configured Nautobot source. Selecting a job fetches its
            parameter schema.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-1">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Filter jobs…"
                className="h-8 pl-7 text-xs"
              />
            </div>
            <div className="flex items-center gap-1.5">
              <Switch checked={enabledOnly} onCheckedChange={setEnabledOnly} id="jobs-enabled-only" />
              <Label htmlFor="jobs-enabled-only" className="text-[11px] text-muted-foreground">
                Enabled only
              </Label>
            </div>
          </div>

          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading jobs…</p>
          ) : visibleJobs.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {jobs && jobs.length === 0
                ? "No jobs found on this Nautobot source."
                : "No jobs match your search."}
            </p>
          ) : (
            <div className="max-h-80 space-y-1 overflow-auto rounded border p-1">
              {visibleJobs.map((job) => (
                <button
                  key={job.id}
                  type="button"
                  onClick={() => handleSelect(job)}
                  className="flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left hover:bg-muted"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-xs font-medium">{job.name}</span>
                    {job.module_name ? (
                      <span className="block truncate font-mono text-[11px] text-muted-foreground">
                        {job.module_name}
                      </span>
                    ) : null}
                  </span>
                  {!job.enabled ? (
                    <Badge className="h-4 shrink-0 rounded px-1 text-[10px]" variant="secondary">
                      disabled
                    </Badge>
                  ) : null}
                </button>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
