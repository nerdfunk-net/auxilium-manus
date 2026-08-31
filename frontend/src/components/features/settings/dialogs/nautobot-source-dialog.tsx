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
import { useNautobotTestConnectionMutation } from "@/hooks/queries/use-source-test-connection-mutations";

import { CredentialSelect } from "../credentials/components/credential-select";
import {
  SOURCE_ID_REGEX,
  SOURCE_KEY_PREFIXES,
  buildSourceSettingKey,
} from "../constants/setting-keys";
import type { NautobotSourceValue } from "../types/settings-api";

const sourceIdSchema = z
  .string()
  .min(1, "Source ID is required")
  .max(64)
  .regex(
    SOURCE_ID_REGEX,
    "Use lowercase letters, numbers, underscores, and hyphens. Must start with a letter.",
  )
  .transform((value) => value.trim().toLowerCase());

const nautobotSchema = z.object({
  sourceId: sourceIdSchema,
  url: z.string().min(1, "URL is required").url("Enter a valid URL"),
  credentialId: z.number().int().positive().optional(),
  verifySsl: z.boolean(),
});

type NautobotFormValues = z.infer<typeof nautobotSchema>;

interface NautobotSourceDialogProps {
  open: boolean;
  mode: "create" | "edit";
  initialValue?: NautobotSourceValue | null;
  existingSourceIds?: string[];
  isSaving?: boolean;
  onClose: () => void;
  onSave: (values: NautobotSourceValue, settingKey: string) => void;
}

const EMPTY_DEFAULTS: NautobotFormValues = {
  sourceId: "",
  url: "",
  credentialId: undefined,
  verifySsl: true,
};

const EMPTY_SOURCE_IDS: string[] = [];

export function NautobotSourceDialog({
  open,
  mode,
  initialValue,
  existingSourceIds = EMPTY_SOURCE_IDS,
  isSaving = false,
  onClose,
  onSave,
}: NautobotSourceDialogProps) {
  const testConnection = useNautobotTestConnectionMutation();

  const {
    register,
    control,
    handleSubmit,
    reset,
    getValues,
    trigger,
    formState: { errors },
  } = useForm<NautobotFormValues>({
    resolver: zodResolver(nautobotSchema),
    defaultValues: EMPTY_DEFAULTS,
  });

  useEffect(() => {
    if (open) {
      reset({
        sourceId: initialValue?.sourceId ?? "",
        url: initialValue?.url ?? "",
        credentialId: initialValue?.credentialId ?? undefined,
        verifySsl: initialValue?.verifySsl ?? true,
      });
    }
  }, [open, initialValue, reset]);

  const isEdit = mode === "edit";

  const onSubmit = useCallback(
    (values: NautobotFormValues) => {
      if (!values.credentialId) {
        return;
      }
      if (mode === "create" && existingSourceIds.includes(values.sourceId)) {
        return;
      }

      const payload: NautobotSourceValue = {
        sourceId: values.sourceId,
        url: values.url.trim(),
        tokenConfigured: true,
        credentialId: values.credentialId,
        verifySsl: values.verifySsl,
      };

      onSave(payload, buildSourceSettingKey("nautobot", values.sourceId));
    },
    [existingSourceIds, mode, onSave],
  );

  const handleTestConnection = useCallback(async () => {
    const values = getValues();

    if (isEdit && initialValue?.sourceId && !values.credentialId) {
      const valid = await trigger(["url"]);
      if (!valid) {
        return;
      }
      testConnection.mutate({
        source_id: values.sourceId,
        verify_ssl: values.verifySsl,
      });
      return;
    }

    const valid = await trigger(["url"]);
    if (!valid || !values.credentialId) {
      return;
    }

    testConnection.mutate({
      url: values.url.trim(),
      credential_id: values.credentialId,
      verify_ssl: values.verifySsl,
    });
  }, [getValues, isEdit, initialValue, testConnection, trigger]);

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? `Edit Nautobot: ${initialValue?.sourceId}` : "Add Nautobot"}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update connection details. The source ID cannot be changed."
              : `Choose a unique source ID (e.g. prod-lab). Stored as ${SOURCE_KEY_PREFIXES.nautobot}<id> and referenced from workflow steps.`}
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-2">
            <Label htmlFor="nautobot-source-id">Source ID</Label>
            <Input
              id="nautobot-source-id"
              placeholder="prod-lab"
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
            <Label htmlFor="nautobot-url">URL</Label>
            <Input
              id="nautobot-url"
              placeholder="https://nautobot.example.com"
              {...register("url")}
            />
            {errors.url ? (
              <p className="text-xs text-destructive">{errors.url.message}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="nautobot-credential">Token credential</Label>
            <Controller
              control={control}
              name="credentialId"
              render={({ field }) => (
                <CredentialSelect
                  id="nautobot-credential"
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
              <Label htmlFor="nautobot-verify-ssl" className="mb-0">
                Verify TLS certificate
              </Label>
              <p className="text-xs text-muted-foreground">
                Disable for self-signed Nautobot lab/dev certificates.
              </p>
            </div>
            <Controller
              control={control}
              name="verifySsl"
              render={({ field }) => (
                <Switch
                  id="nautobot-verify-ssl"
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              )}
            />
          </div>

          <div className="flex items-center justify-between rounded-lg border border-dashed px-4 py-3">
            <p className="text-xs text-muted-foreground">
              Test with the URL, credential, and TLS settings entered above.
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
