"use client";

import { CredentialVisibilityBadge } from "@/components/features/settings/credentials/components/credential-visibility-badge";
import type { Credential } from "@/components/features/settings/credentials/types";
import type { CredentialVisibility } from "@/components/features/settings/credentials/types";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import type { CredentialRemapRequirement } from "../utils/workflow-import";

interface WorkflowImportCredentialRemapProps {
  requirements: CredentialRemapRequirement[];
  credentials: Credential[];
  value: Record<string, string>;
  onChange: (oldName: string, newName: string) => void;
  isLoading?: boolean;
}

export function WorkflowImportCredentialRemap({
  requirements,
  credentials,
  value,
  onChange,
  isLoading = false,
}: WorkflowImportCredentialRemapProps) {
  return (
    <div className="grid gap-3 rounded-md border p-3">
      <div className="grid gap-1">
        <Label>Credential mapping</Label>
        <p className="text-xs text-muted-foreground">
          Some credentials belong to another user or are not available in your
          vault. Choose a replacement for each before importing.
        </p>
      </div>
      {isLoading ? (
        <p className="text-xs text-muted-foreground">Loading credentials…</p>
      ) : credentials.length === 0 ? (
        <p className="text-xs text-warning-foreground">
          No SSH credentials available. Add credentials in Settings →
          Credentials first.
        </p>
      ) : (
        requirements.map((requirement) => (
          <div key={requirement.name} className="grid gap-1.5">
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="font-mono font-medium">{requirement.name}</span>
              {requirement.visibility === "unknown" ? (
                <Badge
                  className="h-4 rounded px-1 text-[10px]"
                  variant="secondary"
                >
                  Unknown
                </Badge>
              ) : (
                <CredentialVisibilityBadge
                  className="h-4 rounded px-1 text-[10px]"
                  visibility={requirement.visibility as CredentialVisibility}
                />
              )}
              {requirement.owner_username ? (
                <span className="text-muted-foreground">
                  owner: {requirement.owner_username}
                </span>
              ) : null}
            </div>
            <Select
              value={value[requirement.name] ?? ""}
              onValueChange={(selected) => onChange(requirement.name, selected)}
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue placeholder="Select replacement credential" />
              </SelectTrigger>
              <SelectContent>
                {credentials.map((credential) => (
                  <SelectItem key={credential.id} value={credential.name}>
                    {credential.name} ({credential.username}) ·{" "}
                    {credential.visibility === "global" ? "Global" : "Private"}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ))
      )}
    </div>
  );
}
