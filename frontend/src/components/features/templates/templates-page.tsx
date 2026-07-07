"use client";

import { FileCode, Plus, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { DeleteTemplateDialog } from "./components/delete-template-dialog";
import { TemplateViewDialog } from "./components/template-view-dialog";
import { TemplatesTable } from "./components/templates-table";
import { useTemplateMutations } from "./hooks/use-template-mutations";
import { useTemplatesQuery } from "./hooks/use-templates-query";
import type { TemplateListItem } from "./types";

export function TemplatesPage() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const { data, isLoading, error } = useTemplatesQuery({ search });
  const { deleteTemplate } = useTemplateMutations();

  const [viewTarget, setViewTarget] = useState<TemplateListItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<TemplateListItem | null>(null);

  const templates = data?.templates ?? [];

  const handleCreate = () => {
    router.push("/templates/editor");
  };

  const handleEdit = (template: TemplateListItem) => {
    router.push(`/templates/editor?id=${template.id}`);
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget) {
      return;
    }
    try {
      await deleteTemplate.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch {
      // error toast handled by mutation
    }
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <FileCode className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-foreground">Templates</h1>
              <p className="mt-1 text-muted-foreground">
                Manage Jinja2 templates used by Netmiko to configure network devices
              </p>
            </div>
          </div>
          <Button type="button" onClick={handleCreate}>
            <Plus className="size-4" />
            Create New Template
          </Button>
        </div>

        <div className="relative max-w-sm">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-9"
            placeholder="Search templates…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading templates…</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error.message}</p>
        ) : (
          <TemplatesTable
            templates={templates}
            onView={setViewTarget}
            onEdit={handleEdit}
            onDelete={setDeleteTarget}
          />
        )}
      </div>

      <TemplateViewDialog
        open={viewTarget !== null}
        templateId={viewTarget?.id ?? null}
        templateName={viewTarget?.name}
        onClose={() => setViewTarget(null)}
      />

      <DeleteTemplateDialog
        open={deleteTarget !== null}
        templateName={deleteTarget?.name}
        isDeleting={deleteTemplate.isPending}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleConfirmDelete}
      />
    </div>
  );
}
