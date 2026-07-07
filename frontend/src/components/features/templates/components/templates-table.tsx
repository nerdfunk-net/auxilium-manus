"use client";

import { Eye, Pencil, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import type { TemplateListItem } from "../types";

interface TemplatesTableProps {
  templates: TemplateListItem[];
  onView: (template: TemplateListItem) => void;
  onEdit: (template: TemplateListItem) => void;
  onDelete: (template: TemplateListItem) => void;
}

function formatDate(value: string | null): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

export function TemplatesTable({
  templates,
  onView,
  onEdit,
  onDelete,
}: TemplatesTableProps) {
  if (templates.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
        No templates yet. Create your first template to get started.
      </p>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-4 py-3 text-left font-medium">Name</th>
            <th className="px-4 py-3 text-left font-medium">Type</th>
            <th className="px-4 py-3 text-left font-medium">Category</th>
            <th className="px-4 py-3 text-left font-medium">Description</th>
            <th className="px-4 py-3 text-left font-medium">Updated</th>
            <th className="px-4 py-3 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {templates.map((template) => (
            <tr key={template.id} className="bg-background hover:bg-muted/30">
              <td className="px-4 py-3 font-medium text-foreground">{template.name}</td>
              <td className="px-4 py-3">
                <Badge variant="secondary">{template.template_type}</Badge>
              </td>
              <td className="px-4 py-3 text-muted-foreground">{template.category}</td>
              <td className="max-w-xs truncate px-4 py-3 text-muted-foreground">
                {template.description || "—"}
              </td>
              <td className="px-4 py-3 text-muted-foreground">
                {formatDate(template.updated_at)}
              </td>
              <td className="px-4 py-3">
                <div className="flex justify-end gap-1">
                  <Button
                    aria-label={`View ${template.name}`}
                    size="icon"
                    type="button"
                    variant="ghost"
                    onClick={() => onView(template)}
                  >
                    <Eye className="size-4" />
                  </Button>
                  <Button
                    aria-label={`Edit ${template.name}`}
                    size="icon"
                    type="button"
                    variant="ghost"
                    onClick={() => onEdit(template)}
                  >
                    <Pencil className="size-4" />
                  </Button>
                  <Button
                    aria-label={`Delete ${template.name}`}
                    size="icon"
                    type="button"
                    variant="ghost"
                    onClick={() => onDelete(template)}
                  >
                    <Trash2 className="size-4 text-destructive" />
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
