"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useCallback, useMemo } from "react";
import { Controller, useForm, type Resolver } from "react-hook-form";
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
import { Label } from "@/components/ui/label";

import { RunInputAttributeField } from "../components/run-input-attribute-field";
import type { StaticAttributeDef } from "../types/workflow-persistence";
import {
  EMPTY_DEVICE_PARAM_CONFIGS,
  type DeviceParamConfig,
} from "../utils/device-param-hints";

type RunInputValues = Record<string, string | number | boolean>;

interface WorkflowRunInputsDialogProps {
  open: boolean;
  staticAttributes: StaticAttributeDef[];
  /** ``get-from-user`` nodes keyed by the static_attribute name they target. */
  deviceParamConfigs?: Record<string, DeviceParamConfig>;
  isSubmitting?: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: RunInputValues) => void;
}

function buildSchema(attrs: StaticAttributeDef[]) {
  const shape: Record<string, z.ZodTypeAny> = {};
  for (const attr of attrs) {
    if (attr.type === "number") {
      const number = z.coerce.number({ error: "Must be a number" });
      shape[attr.name] = attr.required ? number : number.optional();
    } else if (attr.type === "boolean") {
      shape[attr.name] = z.boolean();
    } else {
      shape[attr.name] = attr.required
        ? z.string().min(1, "Required")
        : z.string().optional();
    }
  }
  return z.object(shape);
}

function defaultValuesFor(attrs: StaticAttributeDef[]): RunInputValues {
  const values: RunInputValues = {};
  for (const attr of attrs) {
    if (attr.default !== undefined && attr.default !== null) {
      values[attr.name] = attr.default;
    } else if (attr.type === "boolean") {
      values[attr.name] = false;
    } else {
      values[attr.name] = "";
    }
  }
  return values;
}

/** Prompts for the workflow's declared static_attributes right before
 * dispatching a manual run — see doc/WORKFLOW-STEPS.md "Static attributes".
 * Distinct from the unsaved-changes "Run confirm" dialog: that one resolves
 * save-and-run vs. run-saved-version *before* the target workflow id is
 * known; this one collects values *after* the target is known and *before*
 * dispatch. */
export function WorkflowRunInputsDialog({
  open,
  staticAttributes,
  deviceParamConfigs = EMPTY_DEVICE_PARAM_CONFIGS,
  isSubmitting = false,
  onOpenChange,
  onSubmit,
}: WorkflowRunInputsDialogProps) {
  const schema = useMemo(() => buildSchema(staticAttributes), [staticAttributes]);
  const defaultValues = useMemo(() => defaultValuesFor(staticAttributes), [staticAttributes]);

  const {
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<RunInputValues>({
    resolver: zodResolver(schema) as unknown as Resolver<RunInputValues>,
    values: defaultValues,
  });

  const submit = useCallback((values: RunInputValues) => onSubmit(values), [onSubmit]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex flex-col gap-0 overflow-hidden p-0 sm:max-w-md">
        <DialogHeader className="border-b px-4 py-3">
          <DialogTitle>Run inputs</DialogTitle>
          <DialogDescription>
            This workflow declares values to supply before each manual run.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(submit)} className="flex min-h-0 flex-1 flex-col">
          <div className="grid gap-4 overflow-y-auto px-4 py-4">
            {staticAttributes.map((attr) => (
              <div key={attr.name} className="grid gap-1.5">
                <Label htmlFor={`run-input-${attr.name}`} className="font-mono text-xs font-medium">
                  {attr.name}
                  {attr.required ? <span className="text-destructive"> *</span> : null}
                </Label>
                <Controller
                  control={control}
                  name={attr.name}
                  render={({ field }) => (
                    <RunInputAttributeField
                      id={`run-input-${attr.name}`}
                      attr={attr}
                      value={field.value}
                      deviceParamConfigs={deviceParamConfigs}
                      onChange={field.onChange}
                    />
                  )}
                />
                {errors[attr.name] ? (
                  <p className="text-xs text-destructive">
                    {String(errors[attr.name]?.message ?? "Invalid value")}
                  </p>
                ) : null}
              </div>
            ))}
          </div>

          <DialogFooter className="shrink-0 border-t bg-card px-4 py-3">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Starting…" : "Run"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
