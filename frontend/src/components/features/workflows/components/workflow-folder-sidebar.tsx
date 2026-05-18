"use client";

import { ChevronDown, ChevronRight, Folder } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

import { FOLDER_ROOT, getFolderLabel } from "../utils/workflow-folders";

interface WorkflowFolderSidebarProps {
  totalCount: number;
  folderCounts: Map<string, number>;
  sortedFolders: string[];
  selectedFolder: string | null;
  onSelectFolder: (folder: string | null) => void;
}

export function WorkflowFolderSidebar({
  totalCount,
  folderCounts,
  sortedFolders,
  selectedFolder,
  onSelectFolder,
}: WorkflowFolderSidebarProps) {
  const [rootExpanded, setRootExpanded] = useState(true);
  const subFolders = sortedFolders.filter((f) => f !== FOLDER_ROOT);

  return (
    <div className="flex w-60 shrink-0 flex-col border-r p-4">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Folders
      </p>

      <FolderButton
        active={selectedFolder === null}
        count={totalCount}
        icon={<Folder className="size-4" />}
        label="All"
        onClick={() => onSelectFolder(null)}
      />

      {folderCounts.has(FOLDER_ROOT) && (
        <FolderButton
          active={selectedFolder === FOLDER_ROOT}
          count={folderCounts.get(FOLDER_ROOT) ?? 0}
          expandable
          expanded={rootExpanded}
          icon={<Folder className="size-4" />}
          label="Root"
          onClick={() => {
            onSelectFolder(FOLDER_ROOT);
            setRootExpanded((prev) => !prev);
          }}
        />
      )}

      {rootExpanded &&
        subFolders.map((folder) => (
          <FolderButton
            key={folder}
            active={selectedFolder === folder}
            count={folderCounts.get(folder) ?? 0}
            icon={<Folder className="size-4" />}
            indented
            label={getFolderLabel(folder)}
            onClick={() => onSelectFolder(folder)}
          />
        ))}
    </div>
  );
}

interface FolderButtonProps {
  active: boolean;
  count: number;
  expandable?: boolean;
  expanded?: boolean;
  icon: React.ReactNode;
  indented?: boolean;
  label: string;
  onClick: () => void;
}

export function FolderButton({
  active,
  count,
  expandable = false,
  expanded = false,
  icon,
  indented = false,
  label,
  onClick,
}: FolderButtonProps) {
  return (
    <button
      type="button"
      className={cn(
        "flex w-full items-center justify-between rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-muted/50",
        indented && "pl-7",
        active && "bg-primary/10 font-medium text-primary",
      )}
      onClick={onClick}
    >
      <span className="flex items-center gap-2">
        {expandable ? (
          expanded ? (
            <ChevronDown className="size-3" />
          ) : (
            <ChevronRight className="size-3" />
          )
        ) : null}
        {icon}
        {label}
      </span>
      <span className="text-xs text-muted-foreground">{count}</span>
    </button>
  );
}
