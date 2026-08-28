"use client";

import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { GitRepositorySelectDialog } from "@/components/features/workflow-steps/shared/git-repository-select-dialog";

type ReferenceLocation = "filesystem" | "git";

const REFERENCE_LOCATION_OPTIONS = [
  {
    value: "filesystem",
    label: "Filesystem",
    hint: "Read from DATA_DIRECTORY/pyats-snapshots/ (or reference_subdirectory).",
  },
  {
    value: "git",
    label: "Git repository",
    hint: "Read from a repository configured under Settings → Git Repositories.",
  },
] as const;

export interface ComparePyatsReferenceFieldsProps {
  config: Record<string, unknown>;
  referenceLocation: ReferenceLocation;
  onReferenceLocationChange: (value: string) => void;
  onReferenceSubdirectoryChange: (value: string) => void;
  onGitRepositoryIdChange: (value: number) => void;
  onRepositorySubdirectoryChange: (value: string) => void;
  onPullBeforeReadChange: (checked: boolean) => void;
}

export function ComparePyatsReferenceFields({
  config,
  referenceLocation,
  onReferenceLocationChange,
  onReferenceSubdirectoryChange,
  onGitRepositoryIdChange,
  onRepositorySubdirectoryChange,
  onPullBeforeReadChange,
}: ComparePyatsReferenceFieldsProps) {
  const [gitRepositoryOpen, setGitRepositoryOpen] = useState(false);
  const isGitReference = referenceLocation === "git";
  const gitRepositoryId =
    typeof config.git_repository_id === "number" ? config.git_repository_id : null;

  const referenceHint = useMemo(
    () => REFERENCE_LOCATION_OPTIONS.find((option) => option.value === referenceLocation)?.hint,
    [referenceLocation],
  );

  return (
    <>
      <div className="space-y-1.5 border-t pt-3">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">reference_location</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={referenceLocation} onValueChange={onReferenceLocationChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {REFERENCE_LOCATION_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {referenceHint ? (
          <p className="text-[11px] text-muted-foreground">{referenceHint}</p>
        ) : null}
      </div>

      {isGitReference ? (
        <>
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">git_repository_id</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                git
              </Badge>
            </div>
            {gitRepositoryId !== null ? (
              <p className="font-mono text-[11px] text-muted-foreground">{gitRepositoryId}</p>
            ) : (
              <p className="text-[11px] text-warning-foreground">Not configured</p>
            )}
            <Button
              className="h-7 w-full text-xs"
              size="sm"
              type="button"
              variant="outline"
              onClick={() => setGitRepositoryOpen(true)}
            >
              {gitRepositoryId !== null ? "Change repository" : "Choose repository"}
            </Button>
          </div>

          <GitRepositorySelectDialog
            open={gitRepositoryOpen}
            selectedRepositoryId={gitRepositoryId}
            onClose={() => setGitRepositoryOpen(false)}
            onSave={onGitRepositoryIdChange}
          />

          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">repository_subdirectory</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={
                typeof config.repository_subdirectory === "string"
                  ? config.repository_subdirectory
                  : ""
              }
              onChange={(event) => onRepositorySubdirectoryChange(event.target.value)}
              placeholder="network/snapshots"
              className="h-8 font-mono text-xs"
            />
          </div>

          <Label className="flex cursor-pointer items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={config.pull_before_read === true}
              onChange={(event) => onPullBeforeReadChange(event.target.checked)}
              className="accent-step"
              aria-hidden={false}
            />
            <span className="font-mono text-xs font-medium">pull_before_read</span>
          </Label>
          <p className="pl-5 text-[11px] text-muted-foreground">
            Pull latest changes once before reading the reference file.
          </p>
        </>
      ) : (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">reference_subdirectory</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <Input
            value={
              typeof config.reference_subdirectory === "string"
                ? config.reference_subdirectory
                : "pyats-snapshots"
            }
            onChange={(event) => onReferenceSubdirectoryChange(event.target.value)}
            className="h-8 font-mono text-xs"
          />
          <p className="text-[11px] text-muted-foreground">
            Files are read from DATA_DIRECTORY/&lt;reference_subdirectory&gt;/.
          </p>
        </div>
      )}
    </>
  );
}
