"use client";

import { Loader2, Pencil, Play, Plus, Trash2 } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useReportDefinitionMutations } from "@/hooks/queries/use-report-definition-mutations";
import {
  useReportDefinitionQuery,
  useReportDefinitionsQuery,
} from "@/hooks/queries/use-report-definitions-query";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import { ReportEditorDialog, type ReportDraft } from "./components/report-editor-dialog";
import { SnapshotViewer } from "./components/snapshot-viewer";
import type { ReportDefinitionInput, ReportDefinitionSummary } from "./types/report-definition";
import { formatTimestamp } from "./utils/format";

type EditorTarget =
  | { kind: "new"; draft?: ReportDraft }
  | { kind: "edit"; id: number; sectionText?: { sectionId: string; text: string } }
  | null;

/** A report change the AI assistant drafted; opening it fills the editor, saving stays manual. */
export type ReportDraftRequest =
  | { id: number; kind: "outline"; draft: ReportDraft }
  | { id: number; kind: "section_text"; reportId: number; sectionId: string; text: string };

function requestToTarget(request: ReportDraftRequest | null): EditorTarget {
  if (!request) return null;
  return request.kind === "outline"
    ? { kind: "new", draft: request.draft }
    : {
        kind: "edit",
        id: request.reportId,
        sectionText: { sectionId: request.sectionId, text: request.text },
      };
}

interface ReportsTabProps {
  draftRequest?: ReportDraftRequest | null;
  /** Called when the editor opened by the request is closed. */
  onDraftConsumed?: () => void;
}

/** Saved reports: create, edit, generate a snapshot, delete. */
export function ReportsTab({ draftRequest = null, onDraftConsumed }: ReportsTabProps) {
  const user = useAuthStore((state) => state.user);
  const canWrite = hasPermission(user, "reports", "write");
  const canDelete = hasPermission(user, "reports", "delete");

  const list = useReportDefinitionsQuery();
  const { createDefinition, updateDefinition, deleteDefinition, generateSnapshot } =
    useReportDefinitionMutations();

  const [localEditor, setLocalEditor] = useState<EditorTarget>(null);
  // A draft request (from the AI assistant) opens the editor without an effect: it is derived here
  // and cleared on close, so switching tabs never reopens it.
  const editor = useMemo<EditorTarget>(
    () => localEditor ?? requestToTarget(draftRequest),
    [localEditor, draftRequest],
  );
  const setEditor = useCallback(
    (next: EditorTarget) => {
      setLocalEditor(next);
      if (next === null) onDraftConsumed?.();
    },
    [onDraftConsumed],
  );
  const [toDelete, setToDelete] = useState<ReportDefinitionSummary | null>(null);
  const [viewing, setViewing] = useState<number | null>(null);
  const [generatingId, setGeneratingId] = useState<number | null>(null);

  const editingId = editor?.kind === "edit" ? editor.id : null;
  const editingDefinition = useReportDefinitionQuery(editingId);

  // The saved definition with the drafted section text filled in (unsaved until the user saves).
  const sectionText = editor?.kind === "edit" ? editor.sectionText : undefined;
  const loadedDefinition = editingDefinition.data;
  const editorDefinition = useMemo(() => {
    if (!loadedDefinition || !sectionText) return loadedDefinition;
    return {
      ...loadedDefinition,
      sections: loadedDefinition.sections.map((section) =>
        section.id === sectionText.sectionId ? { ...section, text: sectionText.text } : section,
      ),
    };
  }, [loadedDefinition, sectionText]);

  const handleSave = useCallback(
    (input: ReportDefinitionInput) => {
      const done = { onSuccess: () => setEditor(null) };
      if (editor?.kind === "edit") updateDefinition.mutate({ id: editor.id, data: input }, done);
      else createDefinition.mutate(input, done);
    },
    [createDefinition, editor, setEditor, updateDefinition],
  );

  const handleGenerate = useCallback(
    (id: number) => {
      setGeneratingId(id);
      generateSnapshot.mutate(id, {
        onSuccess: (snapshot) => setViewing(snapshot.id),
        onSettled: () => setGeneratingId(null),
      });
    },
    [generateSnapshot],
  );

  const handleConfirmDelete = useCallback(() => {
    if (!toDelete) return;
    deleteDefinition.mutate(toDelete.id, { onSettled: () => setToDelete(null) });
  }, [deleteDefinition, toDelete]);

  if (list.isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (list.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{list.error.message}</AlertDescription>
      </Alert>
    );
  }

  const definitions = list.data ?? [];
  // The editor opens only once the full definition (with sections) is loaded.
  const editorReady = editor?.kind === "new" || (editor?.kind === "edit" && !!editingDefinition.data);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Generating a report runs all its queries and stores the result as a snapshot.
        </p>
        {canWrite ? (
          <Button size="sm" onClick={() => setEditor({ kind: "new" })}>
            <Plus className="mr-1 size-4" /> New report
          </Button>
        ) : null}
      </div>

      <div className="rounded-lg border">
        <table className="w-full caption-bottom text-sm">
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead className="text-right">Sections</TableHead>
              <TableHead className="text-right">Snapshots</TableHead>
              <TableHead>Last generated</TableHead>
              <TableHead className="w-40" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {definitions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-sm text-muted-foreground">
                  No reports yet.
                </TableCell>
              </TableRow>
            ) : (
              definitions.map((definition) => (
                <TableRow key={definition.id}>
                  <TableCell>
                    <div className="font-medium">{definition.name}</div>
                    {definition.description ? (
                      <div className="text-xs text-muted-foreground">{definition.description}</div>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{definition.section_count}</TableCell>
                  <TableCell className="text-right tabular-nums">{definition.snapshot_count}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatTimestamp(definition.last_generated_at)}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      {canWrite ? (
                        <>
                          <Button
                            size="icon"
                            variant="ghost"
                            aria-label={`Generate ${definition.name}`}
                            disabled={definition.section_count === 0 || generatingId !== null}
                            onClick={() => handleGenerate(definition.id)}
                          >
                            {generatingId === definition.id ? (
                              <Loader2 className="size-4 animate-spin" />
                            ) : (
                              <Play className="size-4" />
                            )}
                          </Button>
                          <Button
                            size="icon"
                            variant="ghost"
                            aria-label={`Edit ${definition.name}`}
                            onClick={() => setEditor({ kind: "edit", id: definition.id })}
                          >
                            <Pencil className="size-4" />
                          </Button>
                        </>
                      ) : null}
                      {canDelete ? (
                        <Button
                          size="icon"
                          variant="ghost"
                          aria-label={`Delete ${definition.name}`}
                          onClick={() => setToDelete(definition)}
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </table>
      </div>

      {editorReady ? (
        <ReportEditorDialog
          open
          onOpenChange={(open) => (open ? undefined : setEditor(null))}
          definition={editor?.kind === "edit" ? editorDefinition : undefined}
          draft={editor?.kind === "new" ? editor.draft : undefined}
          isSaving={createDefinition.isPending || updateDefinition.isPending}
          onSave={handleSave}
        />
      ) : null}

      <Dialog open={toDelete !== null} onOpenChange={(open) => (open ? undefined : setToDelete(null))}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete report?</DialogTitle>
            <DialogDescription>
              {toDelete ? `“${toDelete.name}” will be deleted. Its snapshots are kept.` : ""}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setToDelete(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleConfirmDelete} disabled={deleteDefinition.isPending}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <SnapshotViewer snapshotId={viewing} onClose={() => setViewing(null)} />
    </div>
  );
}
