"use client";

import { useCallback, useEffect } from "react";
import { Controller, useForm } from "react-hook-form";
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
import { Switch } from "@/components/ui/switch";
import { useGitSourceTestConnectionMutation } from "@/hooks/queries/use-source-test-connection-mutations";
import { useToast } from "@/hooks/use-toast";

import {
  SOURCE_ID_REGEX,
  SOURCE_KEY_PREFIXES,
  buildSourceSettingKey,
} from "../constants/setting-keys";
import type { GitSourceValue } from "../types/settings-api";

const sourceIdSchema = z
  .string()
  .min(1, "Source ID is required")
  .max(64)
  .regex(
    SOURCE_ID_REGEX,
    "Use lowercase letters, numbers, underscores, and hyphens. Must start with a letter.",
  )
  .transform((value) => value.trim().toLowerCase());

const gitSchema = z.object({
  sourceId: sourceIdSchema,
  url: z.string().min(1, "URL is required").url("Enter a valid repository URL"),
  branch: z.string().min(1, "Branch is required").max(255),
  username: z.string().max(255).optional(),
  repository_path: z.string().max(500).optional(),
  token: z.string().optional(),
  verifySsl: z.boolean(),
});

type GitFormValues = z.infer<typeof gitSchema>;

interface GitSourceDialogProps {
  open: boolean;
  mode: "create" | "edit";
  initialValue?: GitSourceValue | null;
  existingSourceIds?: string[];
  isSaving?: boolean;
  onClose: () => void;
  onSave: (values: GitSourceValue, settingKey: string, token?: string) => void;
}

const EMPTY_DEFAULTS: GitFormValues = {
  sourceId: "",
  url: "",
  branch: "main",
  username: "",
  repository_path: "",
  token: "",
  verifySsl: true,
};

const EMPTY_SOURCE_IDS: string[] = [];

export function GitSourceDialog({
  open,
  mode,
  initialValue,
  existingSourceIds = EMPTY_SOURCE_IDS,
  isSaving = false,
  onClose,
  onSave,
}: GitSourceDialogProps) {
  const { toast } = useToast();
  const testConnection = useGitSourceTestConnectionMutation();

  const {
    register,
    control,
    handleSubmit,
    reset,
    getValues,
    trigger,
    formState: { errors },
  } = useForm<GitFormValues>({
    resolver: zodResolver(gitSchema),
    defaultValues: EMPTY_DEFAULTS,
  });

  useEffect(() => {
    if (open) {
      reset({
        sourceId: initialValue?.sourceId ?? "",
        url: initialValue?.url ?? "",
        branch: initialValue?.branch ?? "main",
        username: initialValue?.username ?? "",
        repository_path: initialValue?.repository_path ?? "",
        token: "",
        verifySsl: initialValue?.verifySsl ?? true,
      });
    }
  }, [open, initialValue, reset]);

  const resolveEnteredToken = useCallback((entered: string | undefined) => {
    return entered?.trim() ?? "";
  }, []);

  const onSubmit = useCallback(
    (values: GitFormValues) => {
      const token = resolveEnteredToken(values.token);

      if (mode === "create" && !token) {
        return;
      }

      if (
        mode === "create" &&
        existingSourceIds.includes(values.sourceId)
      ) {
        return;
      }

      const payload: GitSourceValue = {
        sourceId: values.sourceId,
        url: values.url.trim(),
        branch: values.branch.trim(),
        username: values.username?.trim() ?? "",
        repository_path: values.repository_path?.trim() ?? "",
        tokenConfigured: mode === "edit" ? Boolean(initialValue?.tokenConfigured) || Boolean(token) : Boolean(token),
        verifySsl: values.verifySsl,
      };

      onSave(
        payload,
        buildSourceSettingKey("git", values.sourceId),
        token || undefined,
      );
    },
    [existingSourceIds, initialValue?.tokenConfigured, mode, onSave, resolveEnteredToken],
  );

  const handleTestConnection = useCallback(async () => {
    const values = getValues();
    const token = resolveEnteredToken(values.token);
    const isEdit = mode === "edit";

    if (isEdit && !token) {
      const valid = await trigger(["url", "branch"]);
      if (!valid) {
        return;
      }
      testConnection.mutate({
        source_id: values.sourceId,
        verify_ssl: values.verifySsl,
      });
      return;
    }

    const valid = await trigger(["url", "branch", "token"]);
    if (!valid) {
      return;
    }

    if (!token) {
      toast({
        title: "Token required",
        description: "Enter a token or password to test the connection.",
        variant: "destructive",
      });
      return;
    }

    testConnection.mutate({
      url: values.url.trim(),
      branch: values.branch.trim(),
      username: values.username?.trim() || undefined,
      token,
      verify_ssl: values.verifySsl,
    });
  }, [getValues, mode, resolveEnteredToken, testConnection, toast, trigger]);

  const hasExistingToken = Boolean(initialValue?.tokenConfigured);
  const isEdit = mode === "edit";

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isEdit
              ? `Edit Git: ${initialValue?.sourceId}`
              : "Add Git repository"}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update repository connection. The source ID cannot be changed."
              : `Choose a unique source ID (e.g. network-configs). Stored as ${SOURCE_KEY_PREFIXES.git}<id> and referenced from workflow steps.`}
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-2">
            <Label htmlFor="git-source-id">Source ID</Label>
            <Input
              id="git-source-id"
              placeholder="network-configs"
              disabled={isEdit}
              {...register("sourceId", {
                validate: (value) => {
                  const normalized = value?.trim().toLowerCase() ?? "";
                  if (mode === "edit") {
                    return true;
                  }
                  if (existingSourceIds.includes(normalized)) {
                    return "This source ID is already in use";
                  }
                  return true;
                },
              })}
            />
            {errors.sourceId ? (
              <p className="text-xs text-destructive">
                {errors.sourceId.message}
              </p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="git-url">Repository URL</Label>
            <Input
              id="git-url"
              placeholder="https://github.com/org/repo.git"
              {...register("url")}
            />
            {errors.url ? (
              <p className="text-xs text-destructive">{errors.url.message}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="git-branch">Branch</Label>
            <Input id="git-branch" placeholder="main" {...register("branch")} />
            {errors.branch ? (
              <p className="text-xs text-destructive">{errors.branch.message}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="git-username">Username (optional)</Label>
            <Input
              id="git-username"
              placeholder="git"
              autoComplete="username"
              {...register("username")}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="git-path">Repository path (optional)</Label>
            <Input
              id="git-path"
              placeholder="configs/network"
              {...register("repository_path")}
            />
            <p className="text-xs text-muted-foreground">
              Subdirectory within the repository, if applicable.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="git-token">Token / password</Label>
            <Input
              id="git-token"
              type="password"
              placeholder={
                hasExistingToken
                  ? "Leave blank to keep existing token"
                  : "Personal access token"
              }
              autoComplete="off"
              {...register("token", {
                validate: (value) => {
                  const trimmed = value?.trim() ?? "";
                  if (trimmed || hasExistingToken) {
                    return true;
                  }
                  return "Token is required";
                },
              })}
            />
            {errors.token ? (
              <p className="text-xs text-destructive">{errors.token.message}</p>
            ) : null}
          </div>

          <div className="flex items-center justify-between rounded-lg border px-4 py-3">
            <div>
              <Label htmlFor="git-verify-ssl" className="mb-0">
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
                  id="git-verify-ssl"
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              )}
            />
          </div>

          <div className="flex items-center justify-between rounded-lg border border-dashed px-4 py-3">
            <p className="text-xs text-muted-foreground">
              Test with the URL, branch, credentials, and TLS settings entered above.
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

          <DialogFooter>
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
