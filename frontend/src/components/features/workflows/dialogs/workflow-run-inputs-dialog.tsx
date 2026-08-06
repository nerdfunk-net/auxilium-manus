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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

import type { StaticAttributeDef } from "../types/workflow-persistence";

type RunInputValues = Record<string, string | number | boolean>;

interface WorkflowRunInputsDialogProps {
  open: boolean;
  staticAttributes: StaticAttributeDef[];
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
  isSubmitting = false,
  onOpenChange,
  onSubmit,
}: WorkflowRunInputsDialogProps) {
  const schema = useMemo(() => buildSchema(staticAttributes), [staticAttributes]);
  const defaultValues = useMemo(() => defaultValuesFor(staticAttributes), [staticAttributes]);

  const {
    register,
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
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Run inputs</DialogTitle>
          <DialogDescription>
            This workflow declares values to supply before each manual run.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(submit)} className="grid gap-4 py-2">
          {staticAttributes.map((attr) => (
            <div key={attr.name} className="grid gap-1.5">
              <Label htmlFor={`run-input-${attr.name}`} className="font-mono text-xs">
                {attr.name}
                {attr.required ? <span className="text-destructive"> *</span> : null}
              </Label>
              {attr.type === "boolean" ? (
                <Controller
                  control={control}
                  name={attr.name}
                  render={({ field }) => (
                    <Switch
                      id={`run-input-${attr.name}`}
                      checked={field.value === true}
                      onCheckedChange={field.onChange}
                    />
                  )}
                />
              ) : (
                <Input
                  id={`run-input-${attr.name}`}
                  type={attr.type === "number" ? "number" : "text"}
                  {...register(attr.name)}
                />
              )}
              {errors[attr.name] ? (
                <p className="text-xs text-destructive">
                  {String(errors[attr.name]?.message ?? "Invalid value")}
                </p>
              ) : null}
            </div>
          ))}

          <DialogFooter>
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
