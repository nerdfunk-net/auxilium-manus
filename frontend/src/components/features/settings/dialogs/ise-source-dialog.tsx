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
import { useISESourcesMutations } from "@/hooks/queries/use-ise-sources-mutations";

import { CredentialSelect } from "../credentials/components/credential-select";
import { SOURCE_ID_REGEX } from "../constants/setting-keys";
import type {
  ISESourceCreatePayload,
  ISESourceUpdatePayload,
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

const iseSchema = z.object({
  sourceId: sourceIdSchema,
  url: z.string().min(1, "URL is required").url("Enter a valid URL"),
  credentialId: z.number().int().positive().optional(),
  verifySsl: z.boolean(),
  timeout: z.number().min(1).max(120),
});

type ISEFormValues = z.infer<typeof iseSchema>;

export interface ISESourceEditValue {
  sourceId: string;
  url: string;
  verifySsl: boolean;
  timeout: number;
  credentialId: number | null;
}

interface ISESourceDialogProps {
  open: boolean;
  mode: "create" | "edit";
  initialValue?: ISESourceEditValue | null;
  existingSourceIds?: string[];
  isSaving?: boolean;
  onClose: () => void;
  onCreate: (values: ISESourceCreatePayload) => void;
  onUpdate: (sourceId: string, values: ISESourceUpdatePayload) => void;
}

const EMPTY_DEFAULTS: ISEFormValues = {
  sourceId: "",
  url: "",
  credentialId: undefined,
  verifySsl: true,
  timeout: 30,
};

const EMPTY_SOURCE_IDS: string[] = [];

export function ISESourceDialog({
  open,
  mode,
  initialValue,
  existingSourceIds = EMPTY_SOURCE_IDS,
  isSaving = false,
  onClose,
  onCreate,
  onUpdate,
}: ISESourceDialogProps) {
  const { testConnection } = useISESourcesMutations();

  const {
    register,
    control,
    handleSubmit,
    reset,
    getValues,
    formState: { errors },
  } = useForm<ISEFormValues>({
    resolver: zodResolver(iseSchema),
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
    (values: ISEFormValues) => {
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

      const update: ISESourceUpdatePayload = {
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
            {isEdit ? `Edit Cisco ISE: ${initialValue?.sourceId}` : "Add Cisco ISE"}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update connection details. The source ID cannot be changed."
              : "Choose a unique source ID (e.g. lab-ise). ISE authenticates with the username and secret from the selected credential."}
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-2">
            <Label htmlFor="ise-source-id">Source ID</Label>
            <Input
              id="ise-source-id"
              placeholder="lab-ise"
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
            <Label htmlFor="ise-url">URL</Label>
            <Input
              id="ise-url"
              placeholder="https://10.10.20.77"
              {...register("url")}
            />
            {errors.url ? (
              <p className="text-xs text-destructive">{errors.url.message}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="ise-credential">Credential</Label>
            <Controller
              control={control}
              name="credentialId"
              render={({ field }) => (
                <CredentialSelect
                  id="ise-credential"
                  value={field.value ?? null}
                  onChange={(next) => field.onChange(next ?? undefined)}
                  credentialType="token"
                />
              )}
            />
            <p className="text-xs text-muted-foreground">
              ISE uses this credential&apos;s username and secret — pick a token
              credential that has a username set.
            </p>
            {errors.credentialId ? (
              <p className="text-xs text-destructive">Select a credential.</p>
            ) : null}
          </div>

          <div className="flex items-center justify-between rounded-lg border px-4 py-3">
            <div>
              <Label htmlFor="ise-verify-ssl" className="mb-0">
                Verify TLS certificate
              </Label>
              <p className="text-xs text-muted-foreground">
                Disable for self-signed ISE sandbox/lab certificates.
              </p>
            </div>
            <Controller
              control={control}
              name="verifySsl"
              render={({ field }) => (
                <Switch
                  id="ise-verify-ssl"
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              )}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="ise-timeout">Timeout (seconds)</Label>
            <Input
              id="ise-timeout"
              type="number"
              min={1}
              max={120}
              {...register("timeout", { valueAsNumber: true })}
            />
            {errors.timeout ? (
              <p className="text-xs text-destructive">{errors.timeout.message}</p>
            ) : null}
          </div>

          <div className="flex items-center justify-between rounded-lg border border-dashed px-4 py-3">
            <p className="text-xs text-muted-foreground">
              Tests the connection against Cisco ISE.
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
