"use client";

import { Minus, Pencil, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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

import { AttributeUpdateDialog } from "./attribute-update-dialog";
import { UpdateAttributeHelpPanel } from "./help-panel";
import { RegexProbePanel } from "./regex-probe-panel";
import {
  buildUpdateAttributeConfig,
  createAttributeUpdate,
  parseUpdateAttributeConfig,
  summarizeAttributeUpdate,
  type AttributeUpdate,
} from "./update-attribute-config";

type EditorState =
  | { open: false }
  | { open: true; mode: "add" | "edit"; index: number | null; value: AttributeUpdate };

const CLOSED_EDITOR: EditorState = { open: false };

function UpdateAttributeConfigPanel({
  config,
  onChange,
  nodeId,
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const parsed = useMemo(() => parseUpdateAttributeConfig(config), [config]);
  const [editor, setEditor] = useState<EditorState>(CLOSED_EDITOR);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    // Migrate legacy flat configs and ensure new nodes start with attributes: [].
    if (!Array.isArray(config.attributes)) {
      onChange(buildUpdateAttributeConfig(config, parsed));
    }
  }, [nodeId, config, onChange, parsed]);

  const handleAdd = useCallback(() => {
    setEditor({
      open: true,
      mode: "add",
      index: null,
      value: createAttributeUpdate(),
    });
  }, []);

  const handleEdit = useCallback(
    (index: number) => {
      const attribute = parsed.attributes[index];
      if (!attribute) {
        return;
      }
      setEditor({
        open: true,
        mode: "edit",
        index,
        value: { ...attribute, regex_flags: { ...attribute.regex_flags } },
      });
    },
    [parsed.attributes],
  );

  const handleRemove = useCallback(
    (index: number) => {
      const nextAttributes = parsed.attributes.filter((_, itemIndex) => itemIndex !== index);
      onChange(buildUpdateAttributeConfig(config, { attributes: nextAttributes }));
    },
    [config, onChange, parsed.attributes],
  );

  const handleSave = useCallback(
    (value: AttributeUpdate) => {
      if (!editor.open) {
        return;
      }
      const nextAttributes =
        editor.mode === "add"
          ? [...parsed.attributes, value]
          : parsed.attributes.map((attribute, index) =>
              index === editor.index ? value : attribute,
            );
      onChange(buildUpdateAttributeConfig(config, { attributes: nextAttributes }));
      setEditor(CLOSED_EDITOR);
    },
    [config, editor, onChange, parsed.attributes],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-teal-50 px-3 py-2 text-xs text-teal-900">
        <p className="font-medium">Update one or more device attributes</p>
        <p className="mt-1 text-[11px] text-teal-800">
          Add attribute updates below. Each entry writes a fixed value or a regex-derived
          value into the workflow device context.
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">attributes</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              object_list
            </Badge>
            {parsed.attributes.length > 0 ? (
              <Badge className="h-4 rounded bg-teal-50 px-1 text-[10px] text-teal-900" variant="outline">
                {parsed.attributes.length}
              </Badge>
            ) : null}
          </div>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-7"
            onClick={handleAdd}
            title="Add attribute"
          >
            <Plus className="size-3.5" aria-hidden />
          </Button>
        </div>

        {parsed.attributes.length === 0 ? (
          <p className="text-[11px] text-amber-600">
            No attribute updates yet. Click + to add one.
          </p>
        ) : (
          <div className="space-y-2">
            {parsed.attributes.map((attribute, index) => (
              <div
                key={attribute.id}
                className="flex items-start gap-1.5 rounded-lg border border-slate-200 bg-white p-2"
              >
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge
                      className="h-4 rounded px-1 text-[10px]"
                      variant={attribute.mode === "fixed" ? "secondary" : "outline"}
                    >
                      {attribute.mode === "fixed" ? "fixed" : "regex"}
                    </Badge>
                    <span className="truncate font-mono text-[11px] text-foreground">
                      {attribute.destination_path}
                    </span>
                  </div>
                  <p className="truncate text-[11px] text-muted-foreground">
                    {summarizeAttributeUpdate(attribute)}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  className="size-7 shrink-0"
                  onClick={() => handleEdit(index)}
                  title="Edit attribute"
                >
                  <Pencil className="size-3.5" aria-hidden />
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  className="size-7 shrink-0"
                  onClick={() => handleRemove(index)}
                  title="Remove attribute"
                >
                  <Minus className="size-3.5" aria-hidden />
                </Button>
              </div>
            ))}
          </div>
        )}

        <p className="text-[11px] leading-4 text-muted-foreground">
          Updates run in list order for each device. Regex entries that do not match are
          skipped; fixed-value entries always write.
        </p>
      </div>

      <AttributeUpdateDialog
        open={editor.open}
        mode={editor.open ? editor.mode : "add"}
        initialValue={editor.open ? editor.value : null}
        onClose={() => setEditor(CLOSED_EDITOR)}
        onSave={handleSave}
      />
    </div>
  );
}

function UpdateAttributeProbeTabPanel({ config }: PluginConfigPanelProps) {
  const parsed = useMemo(() => parseUpdateAttributeConfig(config), [config]);
  const regexAttributes = useMemo(
    () => parsed.attributes.filter((attribute) => attribute.mode === "regex"),
    [parsed.attributes],
  );
  const [selectedId, setSelectedId] = useState<string>("");

  useEffect(() => {
    if (regexAttributes.length === 0) {
      setSelectedId("");
      return;
    }
    if (!regexAttributes.some((attribute) => attribute.id === selectedId)) {
      setSelectedId(regexAttributes[0].id);
    }
  }, [regexAttributes, selectedId]);

  const selected = useMemo(
    () => regexAttributes.find((attribute) => attribute.id === selectedId) ?? null,
    [regexAttributes, selectedId],
  );

  if (regexAttributes.length === 0) {
    return (
      <p className="text-[11px] text-muted-foreground">
        Add a regex attribute update in Configuration to use Probe.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {regexAttributes.length > 1 ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">probe_attribute</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <Select value={selectedId} onValueChange={setSelectedId}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Select attribute to probe" />
            </SelectTrigger>
            <SelectContent>
              {regexAttributes.map((attribute) => (
                <SelectItem key={attribute.id} value={attribute.id}>
                  {attribute.destination_path || attribute.id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : null}

      {selected ? (
        <RegexProbePanel
          pattern={selected.pattern}
          destinationTemplate={selected.destination_template}
          regexFlags={selected.regex_flags}
          sourcePath={selected.source_path}
        />
      ) : null}
    </div>
  );
}

export const UpdateAttributePlugin = {
  ConfigPanel: UpdateAttributeConfigPanel,
  HelpPanel: UpdateAttributeHelpPanel,
  modalTabs: [
    {
      id: "probe",
      label: "Probe",
      Panel: UpdateAttributeProbeTabPanel,
      isVisible: (config: Record<string, unknown>) =>
        parseUpdateAttributeConfig(config).attributes.some(
          (attribute) => attribute.mode === "regex",
        ),
    },
  ],
};
