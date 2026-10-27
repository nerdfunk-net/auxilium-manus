"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import type {
  GlossaryFilter,
  GlossaryKind,
  GlossaryTerm,
  GlossaryTermInput,
} from "@/components/features/ai-assistant/types/ai-assistant";
import { Button } from "@/components/ui/button";
import { Combobox } from "@/components/ui/combobox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useAiGlossaryMutations } from "@/hooks/queries/use-ai-glossary-mutations";
import { useWorkflowStepsQuery } from "@/hooks/queries/use-workflow-steps-query";

import {
  EMPTY_GLOSSARY_FILTER,
  GlossaryFilterEditor,
} from "../components/glossary-filter-editor";

// One explicit ASCII set, the same as the API (models/ai_glossary.py): no commas, because aliases
// are separated by them.
const TERM_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 ._/+&-]*$/;
const TERM_MESSAGE = "Use letters, digits, spaces and . _ / + & - only";
const MAX_TERM_CHARS = 64;
const MAX_ALIASES = 10;

const conditionSchema = z
  .object({
    field: z.string().min(1),
    operator: z.string().min(1),
    value: z.string().trim().min(1, "Every condition needs a value").max(200),
  })
  .refine((c) => !c.field.startsWith("cf_") || c.field.length > 3, {
    message: "Name the custom field",
    path: ["field"],
  });

const filterSchema = z
  .object({
    logic: z.enum(["AND", "OR"]),
    conditions: z.array(conditionSchema).max(20),
    groups: z
      .array(
        z.object({
          logic: z.enum(["AND", "OR"]),
          negate: z.boolean(),
          conditions: z.array(conditionSchema).min(1).max(20),
        }),
      )
      .max(10),
  })
  .refine(
    (f) => f.conditions.length > 0 || f.groups.some((g) => !g.negate),
    "The filter needs at least one condition or a group that is not excluded",
  );

const baseSchema = z.object({
  term: z
    .string()
    .trim()
    .min(1, "A term is required")
    .max(MAX_TERM_CHARS)
    .regex(TERM_PATTERN, TERM_MESSAGE),
  aliases: z.string().max(1000),
  note: z.string().max(300),
  // Inventory entries only:
  source_id: z.string(),
  filter: z.custom<GlossaryFilter>(),
  // Step aliases only:
  step_id: z.string(),
});

/** The rules that depend on what the entry is: a filter and a source, or a step. */
function makeSchema(kind: GlossaryKind) {
  return baseSchema.superRefine((values, ctx) => {
    const problem = aliasProblem(values.term, parseAliases(values.aliases));
    if (problem) {
      ctx.addIssue({ code: "custom", path: ["aliases"], message: problem });
    }
    if (kind === "workflow_step") {
      if (!values.step_id) {
        ctx.addIssue({
          code: "custom",
          path: ["step_id"],
          message: "Choose a step",
        });
      }
      return;
    }
    if (!values.source_id) {
      ctx.addIssue({
        code: "custom",
        path: ["source_id"],
        message: "Choose a Nautobot source",
      });
    }
    const parsed = filterSchema.safeParse(values.filter);
    if (!parsed.success) {
      for (const issue of parsed.error.issues) {
        ctx.addIssue({
          code: "custom",
          path: ["filter", ...issue.path],
          message: issue.message,
        });
      }
    }
  });
}

type FormValues = z.infer<typeof baseSchema>;

/** "a, b" -> ["a", "b"] (commas separate; spaces inside an alias are kept). */
export function parseAliases(raw: string): string[] {
  return raw
    .split(",")
    .map((alias) => alias.trim())
    .filter((alias) => alias.length > 0);
}

/** Why a list of aliases cannot be saved, or null. Mirrors the API's rules. */
export function aliasProblem(term: string, aliases: string[]): string | null {
  if (aliases.length > MAX_ALIASES) {
    return `At most ${MAX_ALIASES} aliases`;
  }
  const seen = new Set([term.trim().toLowerCase().replace(/\s+/g, " ")]);
  for (const alias of aliases) {
    if (alias.length > MAX_TERM_CHARS || !TERM_PATTERN.test(alias)) {
      return `"${alias}": ${TERM_MESSAGE.toLowerCase()}, up to ${MAX_TERM_CHARS} characters`;
    }
    const key = alias.toLowerCase().replace(/\s+/g, " ");
    if (seen.has(key)) {
      return `"${alias}" is used twice`;
    }
    seen.add(key);
  }
  return null;
}

/** First message anywhere in a (nested) react-hook-form error object. */
export function firstErrorMessage(error: unknown): string | undefined {
  if (!error || typeof error !== "object") {
    return undefined;
  }
  const node = error as { message?: unknown };
  if (typeof node.message === "string" && node.message) {
    return node.message;
  }
  for (const child of Object.values(error)) {
    const found = firstErrorMessage(child);
    if (found) {
      return found;
    }
  }
  return undefined;
}

interface AiGlossaryTermDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Which kind of entry this dialog edits or creates. */
  kind: GlossaryKind;
  /** The entry being edited; null creates a new one. */
  term: GlossaryTerm | null;
  /** Nautobot sources the values can be checked against (the first is the default). */
  sourceIds: string[];
}

export function AiGlossaryTermDialog({
  open,
  onOpenChange,
  kind,
  term,
  sourceIds,
}: AiGlossaryTermDialogProps) {
  const { createTerm, updateTerm } = useAiGlossaryMutations();
  const isStep = kind === "workflow_step";
  const { data: steps } = useWorkflowStepsQuery(open && isStep);
  const stepOptions = useMemo(
    () =>
      (steps?.plugins ?? [])
        .filter((p) => p.enabled && p.executable !== false)
        .map((p) => ({ value: p.id, label: `${p.name} (${p.id})` }))
        .sort((x, y) => x.label.localeCompare(y.label)),
    [steps],
  );
  const schema = useMemo(() => makeSchema(kind), [kind]);
  const values = useMemo<FormValues>(
    () => ({
      term: term?.term ?? "",
      aliases: term?.aliases.join(", ") ?? "",
      note: term?.note ?? "",
      source_id: sourceIds[0] ?? "",
      filter:
        term?.kind === "inventory_filter"
          ? term.payload
          : EMPTY_GLOSSARY_FILTER,
      step_id: term?.kind === "workflow_step" ? term.payload.step_id : "",
    }),
    [term, sourceIds],
  );
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    values,
  });
  const reset = form.reset;
  useEffect(() => {
    if (open) {
      reset(values);
    }
  }, [open, reset, values]);

  const sourceId = useWatch({ control: form.control, name: "source_id" });
  const filterError = firstErrorMessage(form.formState.errors.filter);
  const pending = createTerm.isPending || updateTerm.isPending;

  const handleSubmit = useCallback(
    (next: FormValues) => {
      const common = {
        term: next.term,
        aliases: parseAliases(next.aliases),
        note: next.note.trim() || null,
      };
      const data: GlossaryTermInput =
        kind === "workflow_step"
          ? { kind, ...common, step_id: next.step_id }
          : { kind, ...common, filter: next.filter, source_id: next.source_id };
      const options = { onSuccess: () => onOpenChange(false) };
      if (term) {
        updateTerm.mutate({ id: term.id, data }, options);
      } else {
        createTerm.mutate(data, options);
      }
    },
    [createTerm, kind, onOpenChange, term, updateTerm],
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {term ? "Edit" : "Add"}{" "}
            {isStep ? "workflow step alias" : "glossary term"}
          </DialogTitle>
          <DialogDescription>
            {isStep
              ? "When a user's word matches no step id or name, the workflow assistant looks it up here and uses this step."
              : "When a user's word matches no Nautobot name, the assistant looks it up here and combines this filter with the rest of the request."}
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            onSubmit={form.handleSubmit(handleSubmit)}
            className="space-y-4"
            aria-label="Glossary term"
          >
            <FormField
              control={form.control}
              name="term"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Term</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      placeholder={isStep ? "git devices" : "core"}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="aliases"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Aliases</FormLabel>
                  <FormControl>
                    <Input {...field} placeholder="backbone, spine" />
                  </FormControl>
                  <FormDescription>
                    Other words with the same meaning, separated by commas.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            {!isStep && sourceIds.length > 1 && (
              <FormField
                control={form.control}
                name="source_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel htmlFor="glossary-source">
                      Nautobot source
                    </FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger id="glossary-source">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {sourceIds.map((id) => (
                          <SelectItem key={id} value={id}>
                            {id}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      The values are checked against this source. The assistant
                      checks them again against the source of the inventory page
                      it runs on.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}
            {isStep && (
              <FormField
                control={form.control}
                name="step_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Step</FormLabel>
                    <Combobox
                      inline
                      options={stepOptions}
                      value={field.value}
                      onValueChange={field.onChange}
                      placeholder="Choose a step"
                      searchPlaceholder="Search steps"
                    />
                    <FormDescription>
                      The word and its aliases must differ from every step id
                      and display name.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}
            {!isStep && (
              <FormField
                control={form.control}
                name="filter"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Filter</FormLabel>
                    <GlossaryFilterEditor
                      value={field.value as GlossaryFilter}
                      sourceId={sourceId}
                      onChange={field.onChange}
                    />
                    {filterError && (
                      <p role="alert" className="text-sm text-destructive">
                        {filterError}
                      </p>
                    )}
                  </FormItem>
                )}
              />
            )}
            <FormField
              control={form.control}
              name="note"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Note</FormLabel>
                  <FormControl>
                    <Textarea {...field} rows={2} />
                  </FormControl>
                  <FormDescription>
                    For administrators only; never sent to the model.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={pending || (!isStep && sourceIds.length === 0)}
              >
                {pending && <Loader2 className="mr-2 size-4 animate-spin" />}
                Save term
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
