"use client";

import { useCallback, useState } from "react";

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
import { Label } from "@/components/ui/label";
import { useReportDefinitionMutations } from "@/hooks/queries/use-report-definition-mutations";
import { useReportDefinitionsQuery } from "@/hooks/queries/use-report-definitions-query";

import type { ReportSection } from "../types/report-definition";
import type { ReportQuerySpec } from "../types/report-query";
import { LabeledSelect } from "./labeled-select";

const NEW_REPORT = "new";

interface AddToReportDialogProps {
  /** The query to save; the dialog is open while one is set. */
  query: ReportQuerySpec | null;
  onClose: () => void;
}

/** Save an Explore query as a section of an existing report, or of a new one. */
export function AddToReportDialog({ query, onClose }: AddToReportDialogProps) {
  const definitions = useReportDefinitionsQuery();
  const { createDefinition, addSection } = useReportDefinitionMutations();
  const [target, setTarget] = useState<string>(NEW_REPORT);
  const [reportName, setReportName] = useState("");
  const [title, setTitle] = useState("");

  const isNew = target === NEW_REPORT;
  const canSubmit = title.trim() !== "" && (!isNew || reportName.trim() !== "");
  const isPending = createDefinition.isPending || addSection.isPending;

  const handleSubmit = useCallback(() => {
    if (!query || !canSubmit) return;
    const section: ReportSection = {
      id: "section-1",
      title: title.trim(),
      query,
      presentation: "table",
      text: null,
    };
    const done = { onSuccess: onClose };
    if (isNew) {
      createDefinition.mutate(
        { name: reportName.trim(), description: null, sections: [section], template_id: null, default_recipients: [] },
        done,
      );
    } else {
      // The id only has to be unique within the report; the backend rejects a clash.
      addSection.mutate({ id: Number(target), section: { ...section, id: `section-${Date.now()}` } }, done);
    }
  }, [addSection, canSubmit, createDefinition, isNew, onClose, query, reportName, target, title]);

  const options = [
    { value: NEW_REPORT, label: "New report…" },
    ...(definitions.data ?? []).map((d) => ({ value: String(d.id), label: d.name })),
  ];

  return (
    <Dialog open={query !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add to report</DialogTitle>
          <DialogDescription>The query becomes a section that runs whenever the report is generated.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Report</Label>
            <LabeledSelect
              value={target}
              onChange={setTarget}
              options={options}
              placeholder="Report"
              ariaLabel="Report"
              className="h-9 w-full text-sm"
            />
          </div>
          {isNew ? (
            <div className="space-y-1.5">
              <Label htmlFor="add-report-name">Report name</Label>
              <Input id="add-report-name" value={reportName} onChange={(e) => setReportName(e.target.value)} />
            </div>
          ) : null}
          <div className="space-y-1.5">
            <Label htmlFor="add-section-title">Section title</Label>
            <Input id="add-section-title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit || isPending}>
            Add
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
