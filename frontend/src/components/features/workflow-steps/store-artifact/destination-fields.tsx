"use client";

import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { GitDestinationFields } from "@/components/features/workflow-steps/shared/git-destination-fields";

type Destination = "filesystem" | "git";

const DESTINATION_OPTIONS = [
  {
    value: "filesystem",
    label: "Filesystem",
    hint: "Write under the default export directory (Settings → General) → exports/<workflow_id>/<run_id>/.",
  },
  {
    value: "git",
    label: "Git repository",
    hint: "Write into a repository configured under Settings → Git Repositories.",
  },
] as const;

export interface StoreArtifactDestinationFieldsProps {
  destination: Destination;
  isGitDestination: boolean;
  gitRepositoryId: number | null;
  gitRepositoryOpen: boolean;
  onGitRepositoryOpenChange: (open: boolean) => void;
  repositorySubdirectory: string;
  pullBeforeWrite: boolean;
  commitAfterWrite: boolean;
  pushAfterWrite: boolean;
  commitMessageTemplate: string;
  onDestinationChange: (value: string) => void;
  onGitDestinationChange: (patch: {
    git_repository_id?: number | null;
    repository_subdirectory?: string;
    pull_before_write?: boolean;
    commit_after_write?: boolean;
    push_after_write?: boolean;
    commit_message_template?: string;
  }) => void;
}

export function StoreArtifactDestinationFields({
  destination,
  isGitDestination,
  gitRepositoryId,
  gitRepositoryOpen,
  onGitRepositoryOpenChange,
  repositorySubdirectory,
  pullBeforeWrite,
  commitAfterWrite,
  pushAfterWrite,
  commitMessageTemplate,
  onDestinationChange,
  onGitDestinationChange,
}: StoreArtifactDestinationFieldsProps) {
  const destinationHint = DESTINATION_OPTIONS.find(
    (option) => option.value === destination,
  )?.hint;

  return (
    <>
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">destination</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={destination} onValueChange={onDestinationChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DESTINATION_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {destinationHint ? (
          <p className="text-[11px] text-muted-foreground">{destinationHint}</p>
        ) : null}
      </div>

      {isGitDestination ? (
        <GitDestinationFields
          idPrefix="store-artifact"
          gitRepositoryOpen={gitRepositoryOpen}
          onGitRepositoryOpenChange={onGitRepositoryOpenChange}
          values={{
            git_repository_id: gitRepositoryId,
            repository_subdirectory: repositorySubdirectory,
            pull_before_write: pullBeforeWrite,
            commit_after_write: commitAfterWrite,
            push_after_write: pushAfterWrite,
            commit_message_template: commitMessageTemplate,
          }}
          onChange={onGitDestinationChange}
        />
      ) : null}
    </>
  );
}
