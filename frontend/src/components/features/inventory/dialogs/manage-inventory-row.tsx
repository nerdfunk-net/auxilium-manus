"use client";

import {
  Pencil,
  Trash2,
  X,
  Check,
  Loader2,
  Download,
  FileText,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface SavedInventoryRow {
  id: number;
  name: string;
  description?: string | null;
  scope: string;
  group_path?: string | null;
  created_by: string;
  created_at?: string | null;
}

interface ManageInventoryRowProps {
  inventory: SavedInventoryRow;
  isSelected: boolean;
  isEditing: boolean;
  deleteConfirmId: number | null;
  isDeleting: number | null;
  isExporting: number | null;
  editName: string;
  editDescription: string;
  editScope: string;
  editGroup: string;
  allGroupPaths: string[];
  onSelect: () => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSaveEdit: () => void;
  onEditNameChange: (value: string) => void;
  onEditDescriptionChange: (value: string) => void;
  onEditScopeChange: (value: string) => void;
  onEditGroupChange: (value: string) => void;
  onDeleteClick: () => void;
  onConfirmDelete: () => void;
  onCancelDelete: () => void;
  onExport: () => void;
}

export function ManageInventoryRow({
  inventory,
  isSelected,
  isEditing,
  deleteConfirmId,
  isDeleting,
  isExporting,
  editName,
  editDescription,
  editScope,
  editGroup,
  allGroupPaths,
  onSelect,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onEditNameChange,
  onEditDescriptionChange,
  onEditScopeChange,
  onEditGroupChange,
  onDeleteClick,
  onConfirmDelete,
  onCancelDelete,
  onExport,
}: ManageInventoryRowProps) {
  return (
    <div
      className={`border rounded-lg transition-colors ${
        isSelected && !isEditing
          ? "border-info-border bg-info"
          : "border-border bg-card"
      }`}
    >
      {isEditing ? (
        <div className="p-3 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label className="text-xs">Name</Label>
              <Input
                value={editName}
                onChange={(e) => onEditNameChange(e.target.value)}
                className="h-7 text-sm"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Scope</Label>
              <Select value={editScope} onValueChange={onEditScopeChange}>
                <SelectTrigger className="h-7 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="global">Global</SelectItem>
                  <SelectItem value="private">Private</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Description</Label>
            <Textarea
              value={editDescription}
              onChange={(e) => onEditDescriptionChange(e.target.value)}
              rows={1}
              className="min-h-[36px] text-sm resize-none"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Group</Label>
            <Select
              onValueChange={(value) =>
                onEditGroupChange(value === "__root__" ? "" : value)
              }
              value={editGroup || "__root__"}
            >
              <SelectTrigger className="h-7 text-sm">
                <SelectValue placeholder="Root (no group)" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__root__">Root (no group)</SelectItem>
                {allGroupPaths.map((path) => (
                  <SelectItem key={path} value={path}>
                    {path}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex justify-end gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={onCancelEdit}
              className="h-7 text-xs"
            >
              <X className="h-3 w-3 mr-1" /> Cancel
            </Button>
            <Button size="sm" onClick={onSaveEdit} className="h-7 text-xs">
              <Check className="h-3 w-3 mr-1" /> Save
            </Button>
          </div>
        </div>
      ) : (
        <div
          className="flex items-center gap-2 px-3 py-2 cursor-pointer"
          onClick={onSelect}
        >
          <FileText
            className={`h-4 w-4 flex-shrink-0 ${isSelected ? "text-primary" : "text-muted-foreground"}`}
          />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium truncate">
                {inventory.name}
              </span>
              <Badge variant="secondary" className="text-xs flex-shrink-0">
                {inventory.scope}
              </Badge>
            </div>
            <div className="text-xs text-muted-foreground">
              {inventory.created_by}
              {inventory.created_at && (
                <>
                  {" "}
                  &bull; {new Date(inventory.created_at).toLocaleDateString()}
                </>
              )}
            </div>
          </div>

          <div className="flex items-center gap-1 flex-shrink-0">
            {deleteConfirmId === inventory.id ? (
              <div className="flex items-center gap-1 bg-error px-2 py-1 rounded border border-error-border">
                <span className="text-xs text-error-foreground font-medium">
                  Sure?
                </span>
                <Button
                  size="sm"
                  variant="destructive"
                  className="h-6 px-2 text-xs"
                  onClick={(e) => {
                    e.stopPropagation();
                    onConfirmDelete();
                  }}
                  disabled={isDeleting === inventory.id}
                >
                  {isDeleting === inventory.id ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    "Yes"
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 w-6 p-0"
                  onClick={(e) => {
                    e.stopPropagation();
                    onCancelDelete();
                  }}
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
            ) : (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 w-7 p-0 hover:bg-muted"
                  title="Edit"
                  onClick={(e) => {
                    e.stopPropagation();
                    onStartEdit();
                  }}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 w-7 p-0 text-primary hover:bg-info"
                  title="Export"
                  onClick={(e) => {
                    e.stopPropagation();
                    onExport();
                  }}
                  disabled={isExporting === inventory.id}
                >
                  {isExporting === inventory.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Download className="h-3.5 w-3.5" />
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 w-7 p-0 text-error-foreground hover:bg-error"
                  title="Delete"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteClick();
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
