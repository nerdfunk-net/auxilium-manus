"use client";

import { ArrowDown, ArrowUp, Minus, Pencil, Plus } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import { ContentReplaceRuleDialog } from "./content-replace-rule-dialog";
import { UpdateContentHelpPanel } from "./help-panel";
import { RegexProbePanel } from "./regex-probe-panel";
import {
  CONTENT_SOURCE_OPTIONS,
  buildUpdateContentConfig,
  createReplaceRule,
  parseUpdateContentConfig,
  summarizeReplaceRule,
  type ContentReplaceRule,
  type ContentSource,
} from "./update-content-config";

type EditorState =
  | { open: false }
  | { open: true; mode: "add" | "edit"; index: number | null; value: ContentReplaceRule };

const CLOSED_EDITOR: EditorState = { open: false };

function UpdateContentConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const parsed = useMemo(() => parseUpdateContentConfig(config), [config]);
  const [editor, setEditor] = useState<EditorState>(CLOSED_EDITOR);

  const handleContentSourceChange = useCallback(
    (next: ContentSource) => {
      onChange(buildUpdateContentConfig(config, { content_source: next }));
    },
    [config, onChange],
  );

  const handleAdd = useCallback(() => {
    setEditor({
      open: true,
      mode: "add",
      index: null,
      value: createReplaceRule(),
    });
  }, []);

  const handleEdit = useCallback(
    (index: number) => {
      const rule = parsed.replace_rules[index];
      if (!rule) {
        return;
      }
      setEditor({
        open: true,
        mode: "edit",
        index,
        value: { ...rule, regex_flags: { ...rule.regex_flags } },
      });
    },
    [parsed.replace_rules],
  );

  const handleRemove = useCallback(
    (index: number) => {
      const nextRules = parsed.replace_rules.filter((_, itemIndex) => itemIndex !== index);
      onChange(buildUpdateContentConfig(config, { replace_rules: nextRules }));
    },
    [config, onChange, parsed.replace_rules],
  );

  const handleMove = useCallback(
    (index: number, direction: -1 | 1) => {
      const targetIndex = index + direction;
      if (targetIndex < 0 || targetIndex >= parsed.replace_rules.length) {
        return;
      }
      const nextRules = [...parsed.replace_rules];
      [nextRules[index], nextRules[targetIndex]] = [nextRules[targetIndex], nextRules[index]];
      onChange(buildUpdateContentConfig(config, { replace_rules: nextRules }));
    },
    [config, onChange, parsed.replace_rules],
  );

  const handleSave = useCallback(
    (value: ContentReplaceRule) => {
      if (!editor.open) {
        return;
      }
      const nextRules =
        editor.mode === "add"
          ? [...parsed.replace_rules, value]
          : parsed.replace_rules.map((rule, index) => (index === editor.index ? value : rule));
      onChange(buildUpdateContentConfig(config, { replace_rules: nextRules }));
      setEditor(CLOSED_EDITOR);
    },
    [config, editor, onChange, parsed.replace_rules],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
        <p className="font-medium">Search and replace device config text</p>
        <p className="mt-1 text-[11px] text-step-surface-foreground">
          Choose which config to edit, then add one or more regex rules. Rules run in
          order for each device.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">content_source</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={parsed.content_source} onValueChange={handleContentSourceChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="Select content source" />
          </SelectTrigger>
          <SelectContent>
            {CONTENT_SOURCE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">replace_rules</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              object_list
            </Badge>
            {parsed.replace_rules.length > 0 ? (
              <Badge
                className="h-4 rounded bg-step-surface px-1 text-[10px] text-step-surface-foreground"
                variant="outline"
              >
                {parsed.replace_rules.length}
              </Badge>
            ) : null}
          </div>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-7"
            onClick={handleAdd}
            title="Add rule"
          >
            <Plus className="size-3.5" aria-hidden />
          </Button>
        </div>

        {parsed.replace_rules.length === 0 ? (
          <p className="text-[11px] text-warning-foreground">
            No replace rules yet. Click + to add one.
          </p>
        ) : (
          <div className="space-y-2">
            {parsed.replace_rules.map((rule, index) => (
              <div
                key={rule.id}
                className="flex items-start gap-1.5 rounded-lg border border-border bg-card p-2"
              >
                <div className="flex shrink-0 flex-col gap-0.5">
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="size-7"
                    onClick={() => handleMove(index, -1)}
                    disabled={index === 0}
                    title="Move up"
                  >
                    <ArrowUp className="size-3.5" aria-hidden />
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="size-7"
                    onClick={() => handleMove(index, 1)}
                    disabled={index === parsed.replace_rules.length - 1}
                    title="Move down"
                  >
                    <ArrowDown className="size-3.5" aria-hidden />
                  </Button>
                </div>
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge className="h-4 rounded px-1 text-[10px]" variant="outline">
                      #{index + 1}
                    </Badge>
                  </div>
                  <p className="truncate font-mono text-[11px] text-foreground">
                    {summarizeReplaceRule(rule)}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  className="size-7 shrink-0"
                  onClick={() => handleEdit(index)}
                  title="Edit rule"
                >
                  <Pencil className="size-3.5" aria-hidden />
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  className="size-7 shrink-0"
                  onClick={() => handleRemove(index)}
                  title="Remove rule"
                >
                  <Minus className="size-3.5" aria-hidden />
                </Button>
              </div>
            ))}
          </div>
        )}

        <p className="text-[11px] leading-4 text-muted-foreground">
          Rules run in list order for each device — use the arrows to reorder. A rule
          that does not match leaves the text unchanged and does not fail the step.
        </p>
      </div>

      <ContentReplaceRuleDialog
        open={editor.open}
        mode={editor.open ? editor.mode : "add"}
        initialValue={editor.open ? editor.value : null}
        onClose={() => setEditor(CLOSED_EDITOR)}
        onSave={handleSave}
      />
    </div>
  );
}

interface IndexedRule {
  rule: ContentReplaceRule;
  position: number;
}

function describeRule({ rule, position }: IndexedRule): string {
  const pattern = rule.pattern.trim();
  return pattern ? `#${position} · ${pattern}` : `#${position} · (empty pattern)`;
}

function UpdateContentProbeTabPanel({ config }: PluginConfigPanelProps) {
  const parsed = useMemo(() => parseUpdateContentConfig(config), [config]);
  const indexedRules = useMemo(
    () => parsed.replace_rules.map((rule, index) => ({ rule, position: index + 1 })),
    [parsed.replace_rules],
  );
  const [selectedId, setSelectedId] = useState<string>("");

  const effectiveSelectedId = useMemo(() => {
    if (indexedRules.length === 0) {
      return "";
    }
    if (indexedRules.some(({ rule }) => rule.id === selectedId)) {
      return selectedId;
    }
    return indexedRules[0].rule.id;
  }, [indexedRules, selectedId]);

  const selectedEntry = useMemo(
    () => indexedRules.find(({ rule }) => rule.id === effectiveSelectedId) ?? null,
    [indexedRules, effectiveSelectedId],
  );
  const selected = selectedEntry?.rule ?? null;

  if (indexedRules.length === 0) {
    return (
      <p className="text-[11px] text-muted-foreground">
        Add a replace rule in Configuration to use Probe.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {indexedRules.length > 1 ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">probe_rule</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <Select value={effectiveSelectedId} onValueChange={setSelectedId}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Select rule to probe">
                {selectedEntry ? describeRule(selectedEntry) : undefined}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {indexedRules.map((entry) => (
                <SelectItem key={entry.rule.id} value={entry.rule.id}>
                  {describeRule(entry)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : null}

      {selected ? (
        <RegexProbePanel
          pattern={selected.pattern}
          replacement={selected.replacement}
          regexFlags={selected.regex_flags}
          replaceAll={selected.replace_all}
        />
      ) : null}
    </div>
  );
}

export const UpdateContentPlugin = {
  ConfigPanel: UpdateContentConfigPanel,
  HelpPanel: UpdateContentHelpPanel,
  modalTabs: [
    {
      id: "probe",
      label: "Probe",
      Panel: UpdateContentProbeTabPanel,
      isVisible: (config: Record<string, unknown>) =>
        parseUpdateContentConfig(config).replace_rules.length > 0,
    },
  ],
};
