"use client";

import { useCallback, useEffect, useRef } from "react";
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
import { useBatfishSourcesMutations } from "@/hooks/queries/use-batfish-sources-mutations";

import { SOURCE_ID_REGEX } from "../constants/setting-keys";
import type {
  BatfishSourceCreatePayload,
  BatfishSourceUpdatePayload,
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

const batfishSchema = z.object({
  sourceId: sourceIdSchema,
  host: z.string().min(1, "Host is required"),
  port: z.number().int().min(1).max(65535),
});

type BatfishFormValues = z.infer<typeof batfishSchema>;

export interface BatfishSourceEditValue {
  sourceId: string;
  host: string;
  port: number;
}

interface BatfishSourceDialogProps {
  open: boolean;
  mode: "create" | "edit";
  initialValue?: BatfishSourceEditValue | null;
  existingSourceIds?: string[];
  isSaving?: boolean;
  onClose: () => void;
  onCreate: (values: BatfishSourceCreatePayload) => void;
  onUpdate: (sourceId: string, values: BatfishSourceUpdatePayload) => void;
}

const EMPTY_DEFAULTS: BatfishFormValues = {
  sourceId: "",
  host: "",
  port: 9996,
};

const EMPTY_SOURCE_IDS: string[] = [];

export function BatfishSourceDialog({
  open,
  mode,
  initialValue,
  existingSourceIds = EMPTY_SOURCE_IDS,
  isSaving = false,
  onClose,
  onCreate,
  onUpdate,
}: BatfishSourceDialogProps) {
  const { testConnection } = useBatfishSourcesMutations();

  const {
    register,
    handleSubmit,
    reset,
    getValues,
    formState: { errors },
  } = useForm<BatfishFormValues>({
    resolver: zodResolver(batfishSchema),
    defaultValues: EMPTY_DEFAULTS,
  });

  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      reset({
        sourceId: initialValue?.sourceId ?? "",
        host: initialValue?.host ?? "",
        port: initialValue?.port ?? 9996,
      });
    }
    wasOpenRef.current = open;
  }, [open, initialValue, reset]);

  const isEdit = mode === "edit";

  const onSubmit = useCallback(
    (values: BatfishFormValues) => {
      if (mode === "create" && existingSourceIds.includes(values.sourceId)) {
        return;
      }

      if (mode === "create") {
        onCreate({
          source_id: values.sourceId,
          host: values.host.trim(),
          port: values.port,
        });
        return;
      }

      onUpdate(initialValue?.sourceId ?? values.sourceId, {
        host: values.host.trim(),
        port: values.port,
      });
    },
    [existingSourceIds, initialValue?.sourceId, mode, onCreate, onUpdate],
  );

  const handleTestConnection = useCallback(() => {
    const values = getValues();
    if (isEdit && initialValue?.sourceId) {
      testConnection.mutate({ source_id: initialValue.sourceId });
      return;
    }
    if (!values.host?.trim()) {
      return;
    }
    testConnection.mutate({ host: values.host.trim(), port: values.port });
  }, [getValues, isEdit, initialValue, testConnection]);

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? `Edit Batfish: ${initialValue?.sourceId}` : "Add Batfish"}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update connection details. The source ID cannot be changed."
              : "Points at the Batfish coordinator container (see docker/batfish/) — no credential needed, it has no authentication of its own. Choose a unique source ID (e.g. lab-batfish)."}
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-2">
            <Label htmlFor="batfish-source-id">Source ID</Label>
            <Input
              id="batfish-source-id"
              placeholder="lab-batfish"
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
            <Label htmlFor="batfish-host">Host</Label>
            <Input
              id="batfish-host"
              placeholder="batfish (containerized backend) or 127.0.0.1 (native dev)"
              {...register("host")}
            />
            {errors.host ? (
              <p className="text-xs text-destructive">{errors.host.message}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="batfish-port">Port</Label>
            <Input
              id="batfish-port"
              type="number"
              min={1}
              max={65535}
              {...register("port", { valueAsNumber: true })}
            />
            {errors.port ? (
              <p className="text-xs text-destructive">{errors.port.message}</p>
            ) : null}
          </div>

          <div className="flex items-center justify-between rounded-lg border border-dashed px-4 py-3">
            <p className="text-xs text-muted-foreground">
              Confirms the coordinator answers pybatfish&apos;s RPC protocol.
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
