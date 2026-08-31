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
import { usePyATSSourcesMutations } from "@/hooks/queries/use-pyats-sources-mutations";

import { CredentialSelect } from "../credentials/components/credential-select";
import { SOURCE_ID_REGEX } from "../constants/setting-keys";
import type {
  PyATSSourceCreatePayload,
  PyATSSourceUpdatePayload,
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

const pyatsSchema = z.object({
  sourceId: sourceIdSchema,
  url: z.string().min(1, "URL is required").url("Enter a valid URL"),
  credentialId: z.number().int().positive().optional(),
  verifySsl: z.boolean(),
  timeout: z.number().min(1).max(120),
});

type PyATSFormValues = z.infer<typeof pyatsSchema>;

export interface PyATSSourceEditValue {
  sourceId: string;
  url: string;
  verifySsl: boolean;
  timeout: number;
  credentialId: number | null;
}

interface PyATSSourceDialogProps {
  open: boolean;
  mode: "create" | "edit";
  initialValue?: PyATSSourceEditValue | null;
  existingSourceIds?: string[];
  isSaving?: boolean;
  onClose: () => void;
  onCreate: (values: PyATSSourceCreatePayload) => void;
  onUpdate: (sourceId: string, values: PyATSSourceUpdatePayload) => void;
}

const EMPTY_DEFAULTS: PyATSFormValues = {
  sourceId: "",
  url: "",
  credentialId: undefined,
  verifySsl: false,
  timeout: 30,
};

const EMPTY_SOURCE_IDS: string[] = [];

export function PyATSSourceDialog({
  open,
  mode,
  initialValue,
  existingSourceIds = EMPTY_SOURCE_IDS,
  isSaving = false,
  onClose,
  onCreate,
  onUpdate,
}: PyATSSourceDialogProps) {
  const { testConnection } = usePyATSSourcesMutations();

  const {
    register,
    control,
    handleSubmit,
    reset,
    getValues,
    formState: { errors },
  } = useForm<PyATSFormValues>({
    resolver: zodResolver(pyatsSchema),
    defaultValues: EMPTY_DEFAULTS,
  });

  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      reset({
        sourceId: initialValue?.sourceId ?? "",
        url: initialValue?.url ?? "",
        credentialId: initialValue?.credentialId ?? undefined,
        verifySsl: initialValue?.verifySsl ?? false,
        timeout: initialValue?.timeout ?? 30,
      });
    }
    wasOpenRef.current = open;
  }, [open, initialValue, reset]);

  const isEdit = mode === "edit";

  const onSubmit = useCallback(
    (values: PyATSFormValues) => {
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

      const update: PyATSSourceUpdatePayload = {
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
            {isEdit ? `Edit pyATS: ${initialValue?.sourceId}` : "Add pyATS"}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update connection details. The source ID cannot be changed."
              : "Choose a unique source ID (e.g. lab-pyats). Points at a pyATS shim container; the bearer token comes from a credential in the vault."}
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-2">
            <Label htmlFor="pyats-source-id">Source ID</Label>
            <Input
              id="pyats-source-id"
              placeholder="lab-pyats"
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
            <Label htmlFor="pyats-url">URL</Label>
            <Input
              id="pyats-url"
              placeholder="http://pyats-shim:8100"
              {...register("url")}
            />
            {errors.url ? (
              <p className="text-xs text-destructive">{errors.url.message}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="pyats-credential">Token credential</Label>
            <Controller
              control={control}
              name="credentialId"
              render={({ field }) => (
                <CredentialSelect
                  id="pyats-credential"
                  value={field.value ?? null}
                  onChange={(next) => field.onChange(next ?? undefined)}
                  credentialType="token"
                />
              )}
            />
            {errors.credentialId ? (
              <p className="text-xs text-destructive">Select a credential.</p>
            ) : null}
          </div>

          <div className="flex items-center justify-between rounded-lg border px-4 py-3">
            <div>
              <Label htmlFor="pyats-verify-ssl" className="mb-0">
                Verify TLS certificate
              </Label>
              <p className="text-xs text-muted-foreground">
                Leave off for the default plain-HTTP shim on the internal Docker network.
              </p>
            </div>
            <Controller
              control={control}
              name="verifySsl"
              render={({ field }) => (
                <Switch
                  id="pyats-verify-ssl"
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              )}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="pyats-timeout">Timeout (seconds)</Label>
            <Input
              id="pyats-timeout"
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
              Checks the shim&apos;s HTTP layer, then whether pyATS is functional inside it.
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
