"use client";

import { useCallback, useEffect, useRef } from "react";
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
import { useMattermostSourcesMutations } from "@/hooks/queries/use-mattermost-sources-mutations";

import { SOURCE_ID_REGEX } from "../constants/setting-keys";
import type {
  MattermostSourceCreatePayload,
  MattermostSourceUpdatePayload,
} from "../types/settings-api";

const sourceIdSchema = z
  .string()
  .min(1, "Source ID is required")
  .max(64)
  .regex(
    SOURCE_ID_REGEX,
    "Use lowercase letters, numbers, underscores, and hyphens. Must start with a letter.",
  )
  .transform((value) => value.trim().toLowerCase());

const mattermostSchema = z.object({
  sourceId: sourceIdSchema,
  url: z.string().min(1, "URL is required").url("Enter a valid URL"),
  token: z.string().optional(),
  verifySsl: z.boolean(),
  timeout: z.number().min(1).max(120),
});

type MattermostFormValues = z.infer<typeof mattermostSchema>;

export interface MattermostSourceEditValue {
  sourceId: string;
  url: string;
  verifySsl: boolean;
  timeout: number;
}

interface MattermostSourceDialogProps {
  open: boolean;
  mode: "create" | "edit";
  initialValue?: MattermostSourceEditValue | null;
  existingSourceIds?: string[];
  isSaving?: boolean;
  onClose: () => void;
  onCreate: (values: MattermostSourceCreatePayload) => void;
  onUpdate: (sourceId: string, values: MattermostSourceUpdatePayload) => void;
}

const EMPTY_DEFAULTS: MattermostFormValues = {
  sourceId: "",
  url: "",
  token: "",
  verifySsl: true,
  timeout: 30,
};

const EMPTY_SOURCE_IDS: string[] = [];

export function MattermostSourceDialog({
  open,
  mode,
  initialValue,
  existingSourceIds = EMPTY_SOURCE_IDS,
  isSaving = false,
  onClose,
  onCreate,
  onUpdate,
}: MattermostSourceDialogProps) {
  const { testConnection } = useMattermostSourcesMutations();

  const {
    register,
    control,
    handleSubmit,
    reset,
    getValues,
    formState: { errors },
  } = useForm<MattermostFormValues>({
    resolver: zodResolver(mattermostSchema),
    defaultValues: EMPTY_DEFAULTS,
  });

  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      reset({
        sourceId: initialValue?.sourceId ?? "",
        url: initialValue?.url ?? "",
        token: "",
        verifySsl: initialValue?.verifySsl ?? true,
        timeout: initialValue?.timeout ?? 30,
      });
    }
    wasOpenRef.current = open;
  }, [open, initialValue, reset]);

  const isEdit = mode === "edit";

  const onSubmit = useCallback(
    (values: MattermostFormValues) => {
      if (mode === "create" && existingSourceIds.includes(values.sourceId)) {
        return;
      }

      if (mode === "create") {
        if (!values.token?.trim()) {
          return;
        }
        onCreate({
          source_id: values.sourceId,
          url: values.url.trim(),
          token: values.token.trim(),
          verify_ssl: values.verifySsl,
          timeout: values.timeout,
        });
        return;
      }

      const update: MattermostSourceUpdatePayload = {
        url: values.url.trim(),
        verify_ssl: values.verifySsl,
        timeout: values.timeout,
      };
      if (values.token?.trim()) {
        update.token = values.token.trim();
      }
      onUpdate(initialValue?.sourceId ?? values.sourceId, update);
    },
    [existingSourceIds, initialValue?.sourceId, mode, onCreate, onUpdate],
  );

  const handleTestConnection = useCallback(() => {
    if (!initialValue?.sourceId) {
      return;
    }
    const values = getValues();
    const overrides: MattermostSourceUpdatePayload = {
      verify_ssl: values.verifySsl,
    };
    if (values.url?.trim()) {
      overrides.url = values.url.trim();
    }
    if (values.token?.trim()) {
      overrides.token = values.token.trim();
    }
    if (!Number.isNaN(values.timeout)) {
      overrides.timeout = values.timeout;
    }
    testConnection.mutate({ sourceId: initialValue.sourceId, overrides });
  }, [initialValue, testConnection, getValues]);

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? `Edit Mattermost: ${initialValue?.sourceId}` : "Add Mattermost"}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update connection details. The source ID cannot be changed."
              : "Choose a unique source ID (e.g. team-chat). Authenticate with a bot's personal access token; it is encrypted at rest."}
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-2">
            <Label htmlFor="mattermost-source-id">Source ID</Label>
            <Input
              id="mattermost-source-id"
              placeholder="team-chat"
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
              <p className="text-xs text-destructive">{errors.sourceId.message}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="mattermost-url">URL</Label>
            <Input
              id="mattermost-url"
              placeholder="https://mattermost.example.com"
              {...register("url")}
            />
            {errors.url ? (
              <p className="text-xs text-destructive">{errors.url.message}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="mattermost-token">Personal access token</Label>
            <Input
              id="mattermost-token"
              type="password"
              placeholder={isEdit ? "Leave blank to keep existing token" : "Personal access token"}
              autoComplete="off"
              {...register("token", {
                validate: (value) => {
                  if (isEdit || value?.trim()) {
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
              <Label htmlFor="mattermost-verify-ssl" className="mb-0">
                Verify TLS certificate
              </Label>
              <p className="text-xs text-muted-foreground">
                Disable only for self-signed or local development servers.
              </p>
            </div>
            <Controller
              control={control}
              name="verifySsl"
              render={({ field }) => (
                <Switch
                  id="mattermost-verify-ssl"
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              )}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="mattermost-timeout">Timeout (seconds)</Label>
            <Input
              id="mattermost-timeout"
              type="number"
              min={1}
              max={120}
              {...register("timeout", { valueAsNumber: true })}
            />
            {errors.timeout ? (
              <p className="text-xs text-destructive">{errors.timeout.message}</p>
            ) : null}
          </div>

          {isEdit ? (
            <div className="flex items-center justify-between rounded-lg border border-dashed px-4 py-3">
              <p className="text-xs text-muted-foreground">
                Verifies the token against Mattermost&apos;s API.
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
          ) : null}

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
