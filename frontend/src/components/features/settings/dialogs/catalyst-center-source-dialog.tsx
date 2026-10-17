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
import { useCatalystCenterSourcesMutations } from "@/hooks/queries/use-catalyst-center-sources-mutations";

import { CredentialSelect } from "../credentials/components/credential-select";
import { SOURCE_ID_REGEX } from "../constants/setting-keys";
import type {
  CatalystCenterSourceCreatePayload,
  CatalystCenterSourceUpdatePayload,
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

const catalystCenterSchema = z.object({
  sourceId: sourceIdSchema,
  url: z.string().min(1, "URL is required").url("Enter a valid URL"),
  credentialId: z.number().int().positive().optional(),
  verifySsl: z.boolean(),
  timeout: z.number().min(1).max(120),
});

type CatalystCenterFormValues = z.infer<typeof catalystCenterSchema>;

export interface CatalystCenterSourceEditValue {
  sourceId: string;
  url: string;
  verifySsl: boolean;
  timeout: number;
  credentialId: number | null;
}

interface CatalystCenterSourceDialogProps {
  open: boolean;
  mode: "create" | "edit";
  initialValue?: CatalystCenterSourceEditValue | null;
  existingSourceIds?: string[];
  isSaving?: boolean;
  onClose: () => void;
  onCreate: (values: CatalystCenterSourceCreatePayload) => void;
  onUpdate: (
    sourceId: string,
    values: CatalystCenterSourceUpdatePayload,
  ) => void;
}

const EMPTY_DEFAULTS: CatalystCenterFormValues = {
  sourceId: "",
  url: "",
  credentialId: undefined,
  verifySsl: true,
  timeout: 30,
};

const EMPTY_SOURCE_IDS: string[] = [];

export function CatalystCenterSourceDialog({
  open,
  mode,
  initialValue,
  existingSourceIds = EMPTY_SOURCE_IDS,
  isSaving = false,
  onClose,
  onCreate,
  onUpdate,
}: CatalystCenterSourceDialogProps) {
  const { testConnection } = useCatalystCenterSourcesMutations();

  const {
    register,
    control,
    handleSubmit,
    reset,
    getValues,
    formState: { errors },
  } = useForm<CatalystCenterFormValues>({
    resolver: zodResolver(catalystCenterSchema),
    defaultValues: EMPTY_DEFAULTS,
  });

  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      reset({
        sourceId: initialValue?.sourceId ?? "",
        url: initialValue?.url ?? "",
        credentialId: initialValue?.credentialId ?? undefined,
        verifySsl: initialValue?.verifySsl ?? true,
        timeout: initialValue?.timeout ?? 30,
      });
    }
    wasOpenRef.current = open;
  }, [open, initialValue, reset]);

  const isEdit = mode === "edit";

  const onSubmit = useCallback(
    (values: CatalystCenterFormValues) => {
      if (mode === "create" && existingSourceIds.includes(values.sourceId)) {
        return;
      }

      if (mode === "create") {
        if (!values.credentialId) {
          return;
        }
        onCreate({
          source_id: values.sourceId,
          url: values.url.trim(),
          credential_id: values.credentialId,
          verify_ssl: values.verifySsl,
          timeout: values.timeout,
        });
        return;
      }

      const update: CatalystCenterSourceUpdatePayload = {
        url: values.url.trim(),
        verify_ssl: values.verifySsl,
        timeout: values.timeout,
      };
      if (values.credentialId) {
        update.credential_id = values.credentialId;
      }
      onUpdate(initialValue?.sourceId ?? values.sourceId, update);
    },
    [existingSourceIds, initialValue?.sourceId, mode, onCreate, onUpdate],
  );

  const handleTestConnection = useCallback(() => {
    const values = getValues();
    if (isEdit && initialValue?.sourceId) {
      testConnection.mutate({ source_id: initialValue.sourceId });
      return;
    }
    if (!values.url?.trim() || !values.credentialId) {
      return;
    }
    testConnection.mutate({
      url: values.url.trim(),
      credential_id: values.credentialId,
      verify_ssl: values.verifySsl,
      timeout: values.timeout,
    });
  }, [getValues, isEdit, initialValue, testConnection]);

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isEdit
              ? `Edit Cisco Catalyst Center: ${initialValue?.sourceId}`
              : "Add Cisco Catalyst Center"}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update connection details. The source ID cannot be changed."
              : "Choose a unique source ID (e.g. lab-catalyst). Catalyst Center authenticates with the username and secret from the selected credential."}
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-2">
            <Label htmlFor="catalyst-center-source-id">Source ID</Label>
            <Input
              id="catalyst-center-source-id"
              placeholder="lab-catalyst"
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
            <Label htmlFor="catalyst-center-url">URL</Label>
            <Input
              id="catalyst-center-url"
              placeholder="https://catalyst-center.example.com"
              {...register("url")}
            />
            {errors.url ? (
              <p className="text-xs text-destructive">{errors.url.message}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="catalyst-center-credential">Credential</Label>
            <Controller
              control={control}
              name="credentialId"
              render={({ field }) => (
                <CredentialSelect
                  id="catalyst-center-credential"
                  value={field.value ?? null}
                  onChange={(next) => field.onChange(next ?? undefined)}
                  credentialType="generic"
                />
              )}
            />
            <p className="text-xs text-muted-foreground">
              Catalyst Center issues an API token via HTTP Basic Auth — pick a
              Basic Auth credential with a username and password set.
            </p>
            {errors.credentialId ? (
              <p className="text-xs text-destructive">Select a credential.</p>
            ) : null}
          </div>

          <div className="flex items-center justify-between rounded-lg border px-4 py-3">
            <div>
              <Label htmlFor="catalyst-center-verify-ssl" className="mb-0">
                Verify TLS certificate
              </Label>
              <p className="text-xs text-muted-foreground">
                Disable for self-signed Catalyst Center lab certificates.
              </p>
            </div>
            <Controller
              control={control}
              name="verifySsl"
              render={({ field }) => (
                <Switch
                  id="catalyst-center-verify-ssl"
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              )}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="catalyst-center-timeout">Timeout (seconds)</Label>
            <Input
              id="catalyst-center-timeout"
              type="number"
              min={1}
              max={120}
              {...register("timeout", { valueAsNumber: true })}
            />
            {errors.timeout ? (
              <p className="text-xs text-destructive">
                {errors.timeout.message}
              </p>
            ) : null}
          </div>

          <div className="flex items-center justify-between rounded-lg border border-dashed px-4 py-3">
            <p className="text-xs text-muted-foreground">
              Tests the connection and reads the Catalyst Center release.
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
