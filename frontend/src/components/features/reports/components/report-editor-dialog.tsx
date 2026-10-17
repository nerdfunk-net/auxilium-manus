"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Controller, useFieldArray, useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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
import { Textarea } from "@/components/ui/textarea";

import {
  MAX_SECTIONS,
  PRESENTATION_LABELS,
  type Presentation,
  type ReportDefinition,
  type ReportDefinitionInput,
} from "../types/report-definition";
import type { ReportQuerySpec } from "../types/report-query";
import { formatRecipients, MAX_RECIPIENTS, parseRecipients } from "../utils/recipients";
import { moveSection, newSectionId } from "../utils/report-sections";
import { useReportTemplatesQuery } from "@/hooks/queries/use-report-templates-query";

import { LabeledSelect } from "./labeled-select";
import { SectionQueryDialog } from "./section-query-dialog";

const PRESENTATIONS = ["table", "number", "bar", "line"] as const;

const sectionSchema = z.object({
  id: z.string(),
  title: z.string().trim().min(1, "Give every section a title").max(200),
  presentation: z.enum(PRESENTATIONS),
  text: z.string().max(5000),
  query: z.custom<ReportQuerySpec>(),
});

const DEFAULT_TEMPLATE_VALUE = "default";

const formSchema = z.object({
  name: z.string().trim().min(1, "Name is required").max(255),
  description: z.string().max(2000),
  // "default" or the id of a report template, as the Select holds text.
  template: z.string(),
  // Addresses typed as text (see utils/recipients.ts); validated below.
  recipients: z.string().superRefine((text, ctx) => {
    const parsed = parseRecipients(text);
    if (parsed.invalid.length > 0) {
      ctx.addIssue({ code: "custom", message: `Not an email address: ${parsed.invalid.join(", ")}` });
    } else if (parsed.tooMany) {
      ctx.addIssue({ code: "custom", message: `At most ${MAX_RECIPIENTS} recipients` });
    }
  }),
  sections: z.array(sectionSchema).max(MAX_SECTIONS),
});

type FormValues = z.infer<typeof formSchema>;

const EMPTY_FORM: FormValues = {
  name: "",
  description: "",
  template: DEFAULT_TEMPLATE_VALUE,
  recipients: "",
  sections: [],
};

const PRESENTATION_OPTIONS = PRESENTATIONS.map((value) => ({
  value,
  label: PRESENTATION_LABELS[value],
}));

/** A prefilled draft for a new report (for example from the AI assistant); nothing is saved. */
export type ReportDraft = Pick<ReportDefinitionInput, "name" | "description" | "sections">;

function toFormValues(definition: ReportDefinition | undefined, draft?: ReportDraft): FormValues {
  if (!definition && draft) {
    return {
      ...EMPTY_FORM,
      name: draft.name,
      description: draft.description ?? "",
      sections: draft.sections.map((s) => ({ ...s, text: s.text ?? "" })),
    };
  }
  if (!definition) return EMPTY_FORM;
  return {
    name: definition.name,
    description: definition.description ?? "",
    template:
      definition.template_id === null ? DEFAULT_TEMPLATE_VALUE : String(definition.template_id),
    recipients: formatRecipients(definition.default_recipients),
    sections: definition.sections.map((s) => ({ ...s, text: s.text ?? "" })),
  };
}

function toInput(values: FormValues): ReportDefinitionInput {
  return {
    name: values.name.trim(),
    description: values.description.trim() === "" ? null : values.description.trim(),
    template_id: values.template === DEFAULT_TEMPLATE_VALUE ? null : Number(values.template),
    default_recipients: parseRecipients(values.recipients).addresses,
    sections: values.sections.map((s) => ({
      ...s,
      title: s.title.trim(),
      text: s.text.trim() === "" ? null : s.text,
    })),
  };
}

interface ReportEditorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Undefined creates a new report. */
  definition?: ReportDefinition;
  /** Prefills a new report; ignored when `definition` is given. Keep it referentially stable. */
  draft?: ReportDraft;
  isSaving: boolean;
  onSave: (input: ReportDefinitionInput) => void;
}

/** Edit a report's name, description and sections; each section has its own query. */
export function ReportEditorDialog({
  open,
  onOpenChange,
  definition,
  draft,
  isSaving,
  onSave,
}: ReportEditorDialogProps) {
  const {
    control,
    register,
    handleSubmit,
    reset,
    getValues,
    setValue,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(formSchema), defaultValues: EMPTY_FORM });
  const { fields, append, remove, replace } = useFieldArray({ control, name: "sections" });
  // useFieldArray's `fields` do not follow setValue, so current values come from the watch.
  const sections = useWatch({ control, name: "sections" });
  const { templates, isLoading: templatesLoading } = useReportTemplatesQuery();
  const selectedTemplate = useWatch({ control, name: "template" });
  const templateOptions = useMemo(() => {
    const options = [
      { value: DEFAULT_TEMPLATE_VALUE, label: "Default template" },
      ...templates.map((t) => ({ value: String(t.id), label: t.name })),
    ];
    // A template that was deleted or is no longer a report template stays selectable (and visible)
    // so the report can still be saved; the user can pick another one.
    if (!templatesLoading && !options.some((option) => option.value === selectedTemplate)) {
      options.push({ value: selectedTemplate, label: "Unavailable template (removed)" });
    }
    return options;
  }, [templates, templatesLoading, selectedTemplate]);
  // Index of the section whose query is being edited; -1 while adding a new section.
  const [editing, setEditing] = useState<number | null>(null);

  useEffect(() => {
    if (open) reset(toFormValues(definition, draft));
  }, [open, definition, draft, reset]);

  const submit = handleSubmit((values) => onSave(toInput(values)));

  const handleQuerySaved = useCallback(
    (query: ReportQuerySpec) => {
      if (editing === null) return;
      if (editing < 0) {
        const existing = getValues("sections").map((s) => s.id);
        append({
          id: newSectionId(existing),
          title: query.dataset,
          presentation: "table",
          text: "",
          query,
        });
      } else {
        setValue(`sections.${editing}.query`, query, { shouldDirty: true });
      }
    },
    [append, editing, getValues, setValue],
  );

  const handleMove = useCallback(
    (index: number, delta: number) => replace(moveSection(getValues("sections"), index, delta)),
    [getValues, replace],
  );

  const sectionsError = errors.sections?.message ?? errors.sections?.root?.message;

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="flex max-h-[90vh] flex-col gap-4 sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{definition ? "Edit report" : "New report"}</DialogTitle>
            <DialogDescription>
              A report is a list of sections. Each section runs one query when the report is generated.
            </DialogDescription>
          </DialogHeader>

          <form id="report-editor-form" onSubmit={submit} className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
            <div className="space-y-1.5">
              <Label htmlFor="report-name">Name</Label>
              <Input id="report-name" {...register("name")} />
              {errors.name ? <p className="text-xs text-destructive">{errors.name.message}</p> : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="report-description">Description</Label>
              <Textarea id="report-description" rows={2} {...register("description")} />
            </div>

            <div className="space-y-1.5">
              <Label>Report text template</Label>
              <Controller
                control={control}
                name="template"
                render={({ field }) => (
                  <LabeledSelect
                    value={field.value}
                    onChange={field.onChange}
                    options={templateOptions}
                    placeholder="Template"
                    ariaLabel="Report text template"
                    className="h-9 w-full text-sm"
                  />
                )}
              />
              <p className="text-xs text-muted-foreground">
                A Jinja2 template of category “report” turns the generated data into the report
                text. The default lists every section.
              </p>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="report-recipients">Default recipients</Label>
              <Textarea
                id="report-recipients"
                rows={2}
                placeholder="one address per line, or separated by commas"
                {...register("recipients")}
              />
              {errors.recipients ? (
                <p className="text-xs text-destructive">{errors.recipients.message}</p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Proposed when a snapshot of this report is sent by email.
                </p>
              )}
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">Sections</h3>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={fields.length >= MAX_SECTIONS}
                  onClick={() => setEditing(-1)}
                >
                  <Plus className="mr-1 size-4" /> Add section
                </Button>
              </div>
              {sectionsError ? <p className="text-xs text-destructive">{sectionsError}</p> : null}
              {fields.length === 0 ? (
                <p className="rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground">
                  No sections yet. Add one, or save a query from the Explore tab.
                </p>
              ) : null}
              {fields.map((field, index) => (
                <div key={field.id} className="space-y-2 rounded-md border p-3">
                  <div className="flex items-center gap-2">
                    <Input
                      aria-label={`Title of section ${index + 1}`}
                      placeholder="Section title"
                      {...register(`sections.${index}.title`)}
                    />
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      aria-label="Move section up"
                      disabled={index === 0}
                      onClick={() => handleMove(index, -1)}
                    >
                      <ArrowUp className="size-4" />
                    </Button>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      aria-label="Move section down"
                      disabled={index === fields.length - 1}
                      onClick={() => handleMove(index, 1)}
                    >
                      <ArrowDown className="size-4" />
                    </Button>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      aria-label="Remove section"
                      onClick={() => remove(index)}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                  {errors.sections?.[index]?.title ? (
                    <p className="text-xs text-destructive">{errors.sections[index]?.title?.message}</p>
                  ) : null}
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary" className="font-mono text-xs">
                      {sections[index]?.query.dataset}
                    </Badge>
                    <Button type="button" size="sm" variant="outline" onClick={() => setEditing(index)}>
                      <Pencil className="mr-1 size-3.5" /> Edit query
                    </Button>
                    <Controller
                      control={control}
                      name={`sections.${index}.presentation`}
                      render={({ field: select }) => (
                        <LabeledSelect
                          value={select.value}
                          onChange={(value) => select.onChange(value as Presentation)}
                          options={PRESENTATION_OPTIONS}
                          placeholder="Show as"
                          ariaLabel={`Presentation of section ${index + 1}`}
                          className="h-8 w-40 text-xs"
                        />
                      )}
                    />
                  </div>
                  <Textarea
                    rows={2}
                    placeholder="Optional text shown above the result"
                    aria-label={`Text of section ${index + 1}`}
                    {...register(`sections.${index}.text`)}
                  />
                </div>
              ))}
            </div>
          </form>

          {Object.keys(errors).length > 0 ? (
            <Alert variant="destructive">
              <AlertDescription>Fix the highlighted fields to save.</AlertDescription>
            </Alert>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" form="report-editor-form" disabled={isSaving}>
              Save report
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <SectionQueryDialog
        key={editing === null ? "closed" : editing}
        open={editing !== null}
        onOpenChange={(next) => {
          if (!next) setEditing(null);
        }}
        query={editing !== null && editing >= 0 ? sections[editing]?.query : undefined}
        onSave={handleQuerySaved}
      />
    </>
  );
}
