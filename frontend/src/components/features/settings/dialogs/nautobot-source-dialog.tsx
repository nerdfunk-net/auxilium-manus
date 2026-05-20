"use client";

import { useCallback, useEffect } from "react";
import { useForm } from "react-hook-form";
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
  token: z.string().optional(),
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
  token: "",
};

export function NautobotSourceDialog({
  open,
  mode,
  initialValue,
  existingSourceIds = [],
  isSaving = false,
  onClose,
  onSave,
}: NautobotSourceDialogProps) {
  const {
    register,
    handleSubmit,
    reset,
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
        token: "",
      });
    }
  }, [open, initialValue, reset]);

  const onSubmit = useCallback(
    (values: NautobotFormValues) => {
      const token = values.token?.trim()
        ? values.token.trim()
        : (initialValue?.token ?? "");

      if (!token) {
        return;
      }

      if (
        mode === "create" &&
        existingSourceIds.includes(values.sourceId)
      ) {
        return;
      }

      const payload: NautobotSourceValue = {
        sourceId: values.sourceId,
        url: values.url.trim(),
        token,
      };

      onSave(payload, buildSourceSettingKey("nautobot", values.sourceId));
    },
    [existingSourceIds, initialValue?.token, mode, onSave],
  );

  const hasExistingToken = Boolean(initialValue?.token);
  const isEdit = mode === "edit";

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
            <Label htmlFor="nautobot-token">Token</Label>
            <Input
              id="nautobot-token"
              type="password"
              placeholder={
                hasExistingToken
                  ? "Leave blank to keep existing token"
                  : "API token"
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
