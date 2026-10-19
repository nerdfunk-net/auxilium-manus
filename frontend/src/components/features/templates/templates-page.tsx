"use client";

import { ChevronDown, FileCode, FileText, HelpCircle, Plus, Search, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import { DeleteTemplateDialog } from "./components/delete-template-dialog";
import { JinjaHelpDialog } from "./components/jinja-help-dialog";
import { TemplateViewDialog } from "./components/template-view-dialog";
import { TemplatesTable } from "./components/templates-table";
import { TemplateImportDialog } from "./dialogs/template-import-dialog";
import { useTemplateExportMutation } from "./hooks/use-template-export-mutation";
import { useTemplateMutations } from "./hooks/use-template-mutations";
import { useTemplatesQuery } from "./hooks/use-templates-query";
import { REPORT_CATEGORY } from "./report/constants";
import type { TemplateListItem } from "./types";

const CATEGORY_FILTERS = [
  { value: "all", label: "All" },
  { value: "netmiko", label: "Device" },
  { value: REPORT_CATEGORY, label: "Report" },
] as const;

export function TemplatesPage() {
  const router = useRouter();
  const user = useAuthStore((state) => state.user);
  const canWrite = hasPermission(user, "templates", "write");
  const canDelete = hasPermission(user, "templates", "delete");
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const { data, isLoading, error } = useTemplatesQuery({ search });
  const { deleteTemplate } = useTemplateMutations();
  const exportTemplate = useTemplateExportMutation();

  const [viewTarget, setViewTarget] = useState<TemplateListItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<TemplateListItem | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  const templates = useMemo(
    () =>
      (data?.templates ?? []).filter(
        (template) => categoryFilter === "all" || template.category === categoryFilter,
      ),
    [data, categoryFilter],
  );

  const handleCreate = () => {
    router.push("/templates/editor");
  };

  const handleCreateReport = () => {
    router.push("/templates/report-editor");
  };

  // Report templates have their own editor: no devices, commands or Batfish.
  const handleEdit = (template: TemplateListItem) => {
    const editor = template.category === REPORT_CATEGORY ? "report-editor" : "editor";
    router.push(`/templates/${editor}?id=${template.id}`);
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
                Jinja2 templates for configuring network devices, and for the text of reports
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  aria-label="How to write a Jinja2 template"
                  onClick={() => setShowHelp(true)}
                >
                  <HelpCircle className="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>How to write a Jinja2 template</TooltipContent>
            </Tooltip>
            {canWrite ? (
              <>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setImportOpen(true)}
                >
                  <Upload className="size-4" />
                  Import
                </Button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button type="button">
                      <Plus className="size-4" />
                      New Template
                      <ChevronDown className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={handleCreate}>
                      <FileCode className="size-4" />
                      New Netmiko Template
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={handleCreateReport}>
                      <FileText className="size-4" />
                      New Report Template
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </>
            ) : null}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="relative w-full max-w-sm">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              placeholder="Search templates…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          <div className="flex items-center gap-1" role="group" aria-label="Category">
            {CATEGORY_FILTERS.map((filter) => (
              <Button
                key={filter.value}
                type="button"
                size="sm"
                variant={categoryFilter === filter.value ? "default" : "outline"}
                onClick={() => setCategoryFilter(filter.value)}
              >
                {filter.label}
              </Button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading templates…</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error.message}</p>
        ) : (
          <TemplatesTable
            templates={templates}
            exportingId={
              exportTemplate.isPending
                ? (exportTemplate.variables as number | undefined) ?? null
                : null
            }
            onView={setViewTarget}
            onEdit={handleEdit}
            onExport={(template) => exportTemplate.mutate(template.id)}
            onDelete={setDeleteTarget}
            canEdit={canWrite}
            canDelete={canDelete}
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

      <TemplateImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
      />

      <JinjaHelpDialog open={showHelp} onClose={() => setShowHelp(false)} />
    </div>
  );
}
