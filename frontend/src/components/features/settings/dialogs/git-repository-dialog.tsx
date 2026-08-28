"use client";

import { useCallback, useEffect } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type {
  GitRepositoryAuthType,
  GitRepositoryRecord,
} from "@/hooks/queries/use-git-repositories-query";
import {
  useGitRepositoriesMutations,
  type GitConnectionTestPayload,
} from "@/hooks/queries/use-git-repositories-mutations";

import { useCredentialsQuery } from "../credentials/hooks/use-credentials-query";

const GIT_CATEGORIES = [
  {
    value: "workflow_steps",
    label: "Workflow steps (git-clone, get-git-devices, …)",
  },
  { value: "workflows", label: "Workflow Version Control" },
  { value: "device_configs", label: "Device configs" },
] as const;

const repositorySchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  category: z.string().min(1, "Category is required"),
  url: z.string().min(1, "URL is required"),
  branch: z.string().min(1, "Branch is required").max(255),
  authType: z.enum(["token", "ssh_key"]),
  credentialName: z.string().optional(),
  verifySsl: z.boolean(),
  description: z.string().max(1000).optional(),
});

type RepositoryFormValues = z.infer<typeof repositorySchema>;

const EMPTY_DEFAULTS: RepositoryFormValues = {
  name: "",
  category: "workflow_steps",
  url: "",
  branch: "main",
  authType: "token",
  credentialName: "",
  verifySsl: true,
  description: "",
};

interface GitRepositoryDialogProps {
  open: boolean;
  repository: GitRepositoryRecord | null;
  onClose: () => void;
}

function credentialTypeForAuth(authType: GitRepositoryAuthType): string {
  return authType === "ssh_key" ? "ssh_key" : "token";
}

export function GitRepositoryDialog({
  open,
  repository,
  onClose,
}: GitRepositoryDialogProps) {
  const { createRepository, updateRepository, testConnection } =
    useGitRepositoriesMutations();
  const { data: credentialsData } = useCredentialsQuery();
  const isEdit = repository != null;

  const {
    register,
    control,
    handleSubmit,
    reset,
    getValues,
    formState: { errors },
  } = useForm<RepositoryFormValues>({
    resolver: zodResolver(repositorySchema),
    defaultValues: EMPTY_DEFAULTS,
  });

  const authType = useWatch({ control, name: "authType" });

  useEffect(() => {
    if (!open) return;
    reset({
      name: repository?.name ?? "",
      category: repository?.category ?? "workflow_steps",
      url: repository?.url ?? "",
      branch: repository?.branch ?? "main",
      authType: repository?.auth_type === "ssh_key" ? "ssh_key" : "token",
      credentialName: repository?.credential_name ?? "",
      verifySsl: repository?.verify_ssl ?? true,
      description: repository?.description ?? "",
    });
  }, [open, repository, reset]);

  const credentialsOfType = (credentialsData?.credentials ?? []).filter(
    (cred) => cred.type === credentialTypeForAuth(authType),
  );
  const hasPrivateOnly =
    credentialsOfType.length > 0 &&
    credentialsOfType.every((cred) => cred.visibility !== "global");

  const onSubmit = useCallback(
    (values: RepositoryFormValues) => {
      const payload = {
        name: values.name.trim(),
        category: values.category,
        url: values.url.trim(),
        branch: values.branch.trim(),
        auth_type: values.authType,
        credential_name: values.credentialName || null,
        verify_ssl: values.verifySsl,
        description: values.description?.trim() || null,
      };

      if (isEdit && repository) {
        updateRepository.mutate(
          { id: repository.id, data: payload },
          { onSuccess: onClose },
        );
      } else {
        createRepository.mutate(payload, { onSuccess: onClose });
      }
    },
    [createRepository, isEdit, onClose, repository, updateRepository],
  );

  const handleTestConnection = useCallback(() => {
    const values = getValues();
    const payload: GitConnectionTestPayload = {
      url: values.url.trim(),
      branch: values.branch.trim(),
      auth_type: values.authType,
      credential_name: values.credentialName || null,
      verify_ssl: values.verifySsl,
    };
    testConnection.mutate(payload);
  }, [getValues, testConnection]);

  const isSaving = createRepository.isPending || updateRepository.isPending;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? "Edit Git repository" : "Add Git repository"}
          </DialogTitle>
          <DialogDescription>
            Referenced by ID from workflow steps (git-clone, get-git-devices, …)
            and, when category is &quot;Workflow Version Control&quot;, by the
            workflow Manage dialog.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={handleSubmit(onSubmit)}
        >
          <div className="flex-1 space-y-4 overflow-y-auto px-1 py-1">
            <div className="space-y-2">
              <Label htmlFor="git-repo-name">Name</Label>
              <Input
                id="git-repo-name"
                placeholder="network-configs"
                {...register("name")}
              />
              {errors.name ? (
                <p className="text-xs text-destructive">
                  {errors.name.message}
                </p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label htmlFor="git-repo-category">Category</Label>
              <Controller
                control={control}
                name="category"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="git-repo-category">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {GIT_CATEGORIES.map((category) => (
                        <SelectItem key={category.value} value={category.value}>
                          {category.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="git-repo-url">Repository URL</Label>
              <Input
                id="git-repo-url"
                placeholder="https://github.com/org/repo.git"
                {...register("url")}
              />
              {errors.url ? (
                <p className="text-xs text-destructive">{errors.url.message}</p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label htmlFor="git-repo-branch">Branch</Label>
              <Input
                id="git-repo-branch"
                placeholder="main"
                {...register("branch")}
              />
              {errors.branch ? (
                <p className="text-xs text-destructive">
                  {errors.branch.message}
                </p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label htmlFor="git-repo-auth-type">Authentication</Label>
              <Controller
                control={control}
                name="authType"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="git-repo-auth-type">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="token">Token / password</SelectItem>
                      <SelectItem value="ssh_key">SSH key</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="git-repo-credential">Credential</Label>
              <Controller
                control={control}
                name="credentialName"
                render={({ field }) => (
                  <Select
                    value={field.value || undefined}
                    onValueChange={field.onChange}
                  >
                    <SelectTrigger id="git-repo-credential">
                      <SelectValue placeholder="Select a credential" />
                    </SelectTrigger>
                    <SelectContent>
                      {credentialsOfType.length === 0 ? (
                        <div className="px-2 py-1.5 text-xs text-muted-foreground">
                          No {authType === "ssh_key" ? "SSH key" : "token"}{" "}
                          credentials found. Add one in Settings → Credentials.
                        </div>
                      ) : (
                        credentialsOfType.map((cred) => (
                          <SelectItem
                            key={cred.id}
                            value={cred.name}
                            disabled={cred.visibility !== "global"}
                          >
                            {cred.name} ({cred.username})
                            {cred.visibility !== "global"
                              ? " — private, must be global"
                              : ""}
                          </SelectItem>
                        ))
                      )}
                    </SelectContent>
                  </Select>
                )}
              />
              <p className="text-xs text-muted-foreground">
                Only <strong>global</strong> credentials are usable here — Git
                operations run in the background, not as the signed-in user, so
                private credentials are not readable.
                {hasPrivateOnly
                  ? " Edit the credential in Settings → Credentials and turn on “Make this credential global”."
                  : ""}
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="git-repo-description">
                Description (optional)
              </Label>
              <Input
                id="git-repo-description"
                placeholder="Optional"
                {...register("description")}
              />
            </div>

            <div className="flex items-center justify-between rounded-lg border px-4 py-3">
              <div>
                <Label htmlFor="git-repo-verify-ssl" className="mb-0">
                  Verify TLS certificate
                </Label>
                <p className="text-xs text-muted-foreground">
                  Disable for self-signed Git server certificates.
                </p>
              </div>
              <Controller
                control={control}
                name="verifySsl"
                render={({ field }) => (
                  <Switch
                    id="git-repo-verify-ssl"
                    checked={field.value}
                    onCheckedChange={field.onChange}
                  />
                )}
              />
            </div>

            <div className="flex items-center justify-between rounded-lg border border-dashed px-4 py-3">
              <p className="text-xs text-muted-foreground">
                Test with the URL, branch, and credential entered above.
              </p>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={testConnection.isPending}
                onClick={handleTestConnection}
              >
                {testConnection.isPending ? "Testing…" : "Test connection"}
              </Button>
            </div>
          </div>

          <DialogFooter className="shrink-0 pt-4">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button disabled={isSaving} type="submit">
              {isSaving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
