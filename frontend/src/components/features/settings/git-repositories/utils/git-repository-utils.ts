import type { GitRepositoryAuthType } from "@/hooks/queries/use-git-repositories-query";

export const GIT_CATEGORIES = [
  {
    value: "workflow_steps",
    label: "Workflow steps (git-clone, get-git-devices, …)",
  },
  { value: "workflows", label: "Workflow Version Control" },
  { value: "device_configs", label: "Device configs" },
  { value: "cicd_pipeline", label: "CI/CD Pipeline" },
] as const;

export function gitCategoryLabel(category: string): string {
  return GIT_CATEGORIES.find((entry) => entry.value === category)?.label ?? category;
}

const AUTH_TYPE_LABELS: Record<GitRepositoryAuthType, string> = {
  none: "None",
  token: "Token / password",
  ssh_key: "SSH key",
  generic: "Generic",
};

export function gitAuthTypeLabel(authType: GitRepositoryAuthType | null): string {
  return AUTH_TYPE_LABELS[authType ?? "token"];
}

export function formatLastSync(lastSync: string | null): string {
  if (!lastSync) return "Never";
  return new Date(lastSync).toLocaleString();
}
