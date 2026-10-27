"use client";

import { Pencil, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import type {
  GlossaryFilter,
  GlossaryTerm,
} from "@/components/features/ai-assistant/types/ai-assistant";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAiGlossaryMutations } from "@/hooks/queries/use-ai-glossary-mutations";
import { useAiGlossaryQuery } from "@/hooks/queries/use-ai-glossary-query";
import { useNautobotConfiguredSourcesQuery } from "@/hooks/queries/use-nautobot-configured-sources-query";

import { AiGlossaryTermDialog } from "./ai-glossary-term-dialog";

const PAGE_SIZE = 25;
const SEARCH_DELAY_MS = 300;

/** One line per condition group, for the table. */
export function summarizeFilter(filter: GlossaryFilter): string {
  const part = (c: { field: string; operator: string; value: string }) =>
    `${c.field} ${c.operator.replace(/_/g, " ")} ${c.value}`;
  const joiner = ` ${filter.logic} `;
  const pieces = [
    ...filter.conditions.map(part),
    ...filter.groups.map(
      (g) =>
        `${g.negate ? "NOT " : ""}(${g.conditions.map(part).join(` ${g.logic} `)})`,
    ),
  ];
  return pieces.join(joiner);
}

interface AiGlossaryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AiGlossaryDialog({
  open,
  onOpenChange,
}: AiGlossaryDialogProps) {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<GlossaryTerm | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [deleting, setDeleting] = useState<GlossaryTerm | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search.trim());
      setOffset(0);
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [search]);

  const { data, isLoading, error } = useAiGlossaryQuery({
    query,
    offset,
    limit: PAGE_SIZE,
    enabled: open,
  });
  const { data: sources } = useNautobotConfiguredSourcesQuery({
    enabled: open,
  });
  const sourceIds = useMemo(
    () =>
      (sources ?? []).filter((s) => s.token_configured).map((s) => s.source_id),
    [sources],
  );
  const hasSource = sourceIds.length > 0;
  const { deleteTerm } = useAiGlossaryMutations();

  const total = data?.total ?? 0;
  const items = data?.items ?? [];

  const handleAdd = useCallback(() => {
    setEditing(null);
    setFormOpen(true);
  }, []);
  const handleEdit = useCallback((term: GlossaryTerm) => {
    setEditing(term);
    setFormOpen(true);
  }, []);
  const handleConfirmDelete = useCallback(() => {
    if (!deleting) {
      return;
    }
    // Deleting the only row of a later page would leave an empty page: step back first.
    const emptiesThePage = items.length === 1 && offset > 0;
    deleteTerm.mutate(deleting.id, {
      onSuccess: () => {
        if (emptiesThePage) {
          setOffset(Math.max(0, offset - PAGE_SIZE));
        }
      },
      onSettled: () => setDeleting(null),
    });
  }, [deleteTerm, deleting, items.length, offset]);

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-5xl">
          <DialogHeader>
            <DialogTitle>Inventory glossary</DialogTitle>
            <DialogDescription>
              Words and acronyms the inventory assistant may expand into a
              filter. Shared by every user; only administrators edit it.
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2">
            <Input
              aria-label="Search glossary"
              placeholder="Search terms and aliases"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Button type="button" onClick={handleAdd} disabled={!hasSource}>
              <Plus className="mr-1 size-4" />
              Add term
            </Button>
          </div>
          {!hasSource && sources && (
            <p className="text-sm text-muted-foreground">
              Configure a Nautobot source first: values are checked against it.
            </p>
          )}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error.message}
            </p>
          )}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Term</TableHead>
                <TableHead>Aliases</TableHead>
                <TableHead>Filter</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((term) => (
                <TableRow key={term.id}>
                  <TableCell className="font-medium">{term.term}</TableCell>
                  <TableCell>{term.aliases.join(", ")}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {summarizeFilter(term.filter)}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={`Edit ${term.term}`}
                      disabled={!hasSource}
                      onClick={() => handleEdit(term)}
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={`Delete ${term.term}`}
                      onClick={() => setDeleting(term)}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {!isLoading && items.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="text-center text-muted-foreground"
                  >
                    {query ? "No term matches." : "No glossary terms yet."}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          <DialogFooter className="items-center sm:justify-between">
            <span className="text-sm text-muted-foreground">
              {total === 0
                ? "0 terms"
                : `${offset + 1}-${Math.min(offset + PAGE_SIZE, total)} of ${total}`}
            </span>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Previous
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AiGlossaryTermDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        term={editing}
        sourceIds={sourceIds}
      />

      <Dialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete glossary term</DialogTitle>
            <DialogDescription>
              Delete &quot;{deleting?.term}&quot;? The assistant will no longer
              know this word.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeleting(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={deleteTerm.isPending}
              onClick={handleConfirmDelete}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
