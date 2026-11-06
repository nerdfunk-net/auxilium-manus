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
import { useAciSourcesMutations } from "@/hooks/queries/use-aci-sources-mutations";

import { CredentialSelect } from "../credentials/components/credential-select";
import { SOURCE_ID_REGEX } from "../constants/setting-keys";
import type {
  AciSourceCreatePayload,
  AciSourceUpdatePayload,
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

const aciSchema = z.object({
  sourceId: sourceIdSchema,
  url: z.string().min(1, "URL is required").url("Enter a valid URL"),
  credentialId: z.number().int().positive().optional(),
  verifySsl: z.boolean(),
  timeout: z.number().min(1).max(120),
});

type AciFormValues = z.infer<typeof aciSchema>;

export interface AciSourceEditValue {
  sourceId: string;
  url: string;
  verifySsl: boolean;
  timeout: number;
  credentialId: number | null;
}

interface AciSourceDialogProps {
  open: boolean;
  mode: "create" | "edit";
  initialValue?: AciSourceEditValue | null;
  existingSourceIds?: string[];
  isSaving?: boolean;
  onClose: () => void;
  onCreate: (values: AciSourceCreatePayload) => void;
  onUpdate: (
    sourceId: string,
    values: AciSourceUpdatePayload,
  ) => void;
}

const EMPTY_DEFAULTS: AciFormValues = {
  sourceId: "",
  url: "",
  credentialId: undefined,
  verifySsl: true,
  timeout: 30,
};

const EMPTY_SOURCE_IDS: string[] = [];

export function AciSourceDialog({
  open,
  mode,
  initialValue,
  existingSourceIds = EMPTY_SOURCE_IDS,
  isSaving = false,
  onClose,
  onCreate,
  onUpdate,
}: AciSourceDialogProps) {
  const { testConnection } = useAciSourcesMutations();

  const {
    register,
    control,
    handleSubmit,
    reset,
    getValues,
    formState: { errors },
  } = useForm<AciFormValues>({
    resolver: zodResolver(aciSchema),
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
    (values: AciFormValues) => {
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

      const update: AciSourceUpdatePayload = {
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
              ? `Edit Cisco ACI: ${initialValue?.sourceId}`
              : "Add Cisco ACI"}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update connection details. The source ID cannot be changed."
              : "Choose a unique source ID (e.g. lab-aci). The APIC login uses the username and secret from the selected credential. Only read access is used; no data is ever written to ACI."}
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-2">
            <Label htmlFor="aci-source-id">Source ID</Label>
            <Input
              id="aci-source-id"
              placeholder="lab-aci"
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
            <Label htmlFor="aci-url">URL</Label>
            <Input
              id="aci-url"
              placeholder="https://apic.example.com"
              {...register("url")}
            />
            {errors.url ? (
              <p className="text-xs text-destructive">{errors.url.message}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="aci-credential">Credential</Label>
            <Controller
              control={control}
              name="credentialId"
              render={({ field }) => (
                <CredentialSelect
                  id="aci-credential"
                  value={field.value ?? null}
                  onChange={(next) => field.onChange(next ?? undefined)}
                  credentialType="generic"
                />
              )}
            />
            <p className="text-xs text-muted-foreground">
              The APIC login takes a username and password — pick a Basic Auth
              credential with both set. Use a read-only APIC user. For a remote
              (non-local) user, enter the username as{" "}
              <code className="rounded bg-muted px-1">apic:&lt;domain&gt;\&lt;user&gt;</code>.
            </p>
            {errors.credentialId ? (
              <p className="text-xs text-destructive">Select a credential.</p>
            ) : null}
          </div>

          <div className="flex items-center justify-between rounded-lg border px-4 py-3">
            <div>
              <Label htmlFor="aci-verify-ssl" className="mb-0">
                Verify TLS certificate
              </Label>
              <p className="text-xs text-muted-foreground">
                Disable for self-signed APIC certificates (e.g. a lab or the DevNet sandbox).
              </p>
            </div>
            <Controller
              control={control}
              name="verifySsl"
              render={({ field }) => (
                <Switch
                  id="aci-verify-ssl"
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              )}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="aci-timeout">Timeout (seconds)</Label>
            <Input
              id="aci-timeout"
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
              Logs in, reads one fabric node and shows the APIC version.
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
