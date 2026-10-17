"use client";

import { useCallback, useMemo, useState } from "react";

import { TemplateViewDialog } from "@/components/features/templates/components/template-view-dialog";
import { useTemplatesQuery } from "@/components/features/templates/hooks/use-templates-query";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { AttributePathPicker } from "@/components/features/workflow-steps/shared/attribute-path-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";

import {
  NAUTOBOT_SOURCE_ID_KEY,
  isNautobotSourceConfigured,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import { UpdateConfigContextHelpPanel } from "./help-panel";
import {
  buildUpdateConfigContextConfig,
  parseUpdateConfigContextConfig,
  patchUpdateEntry,
  toLocalConfigContextPath,
  type UpdateConfigContextMode,
  type UpdateEntry,
  type ValueSourceConfig,
} from "./config";
import { PathInput, UpdateEntryRows } from "./update-entry-rows";
import { ValueSourceFields } from "./value-source-fields";

const APPEND_PATH_PLACEHOLDER = "tacacs (leave empty to merge into the root)";

/** Which field the single shared attribute picker is filling; `index` is null for the top-level (write/append) fields. */
interface PickerTarget {
  field: "path" | "value";
  index: number | null;
}

function PathHelpText({ mode }: { mode: UpdateConfigContextMode }) {
  return (
    <>
      Dotted path <em>inside</em> local_config_context_data (not the workflow attribute path — no{" "}
      <span className="font-mono">nautobot.config_context.</span> prefix; the picker strips it for
      you). Reach a list item by index, e.g.{" "}
      <span className="font-mono">credentials[0].password</span>, or by field value, e.g.{" "}
      <span className="font-mono">tacacs[address=1.2.3.4].key</span>. Use{" "}
      <span className="font-mono">{"{attribute.path}"}</span> to take that value from the device,
      e.g. <span className="font-mono">{"tacacs[server={custom.tacacs_server}].key"}</span>.
      {mode === "append"
        ? " Leave empty to merge the resolved value's own top-level keys directly into the document root instead of nesting them under a new key."
        : null}{" "}
      Lists are never extended — the item must already exist.
    </>
  );
}

function UpdateConfigContextConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes,
  workflowEdges,
}: PluginConfigPanelProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });
  const parsed = useMemo(() => parseUpdateConfigContextConfig(config), [config]);

  const [sourceOpen, setSourceOpen] = useState(false);
  const [pickerTarget, setPickerTarget] = useState<PickerTarget | null>(null);
  // Template whose content the read-only preview dialog shows; null = closed.
  const [previewTemplateId, setPreviewTemplateId] = useState<number | null>(null);

  const { data: templatesData, isLoading: templatesLoading, isError: templatesError } =
    useTemplatesQuery();
  const templates = useMemo(
    () => (templatesData?.templates ?? []).filter((template) => template.template_type === "jinja2"),
    [templatesData],
  );

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [NAUTOBOT_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleModeChange = useCallback(
    (value: string) => {
      onChange(buildUpdateConfigContextConfig(config, { mode: value as UpdateConfigContextMode }));
    },
    [config, onChange],
  );

  const handlePathChange = useCallback(
    (value: string) => {
      onChange(buildUpdateConfigContextConfig(config, { path: value }));
    },
    [config, onChange],
  );

  const handleValueSourceChange = useCallback(
    (value_source: ValueSourceConfig) => {
      onChange(buildUpdateConfigContextConfig(config, { value_source }));
    },
    [config, onChange],
  );

  const handleUpdatesChange = useCallback(
    (updates: UpdateEntry[]) => {
      onChange(buildUpdateConfigContextConfig(config, { updates }));
    },
    [config, onChange],
  );

  const handleCreateLocalChange = useCallback(
    (checked: boolean) => {
      onChange(buildUpdateConfigContextConfig(config, { create_local_if_missing: checked }));
    },
    [config, onChange],
  );

  const handlePickerClose = useCallback(() => setPickerTarget(null), []);

  const handlePicked = useCallback(
    (picked: string) => {
      if (pickerTarget === null) return;
      const { field, index } = pickerTarget;
      if (index === null) {
        onChange(
          buildUpdateConfigContextConfig(
            config,
            field === "path"
              ? { path: toLocalConfigContextPath(picked) }
              : { value_source: { ...parsed.value_source, attribute_path: picked } },
          ),
        );
        return;
      }
      const entry = parsed.updates[index];
      if (!entry) return;
      handleUpdatesChange(
        patchUpdateEntry(
          parsed.updates,
          index,
          field === "path"
            ? { path: toLocalConfigContextPath(picked) }
            : { value_source: { ...entry.value_source, attribute_path: picked } },
        ),
      );
    },
    [config, handleUpdatesChange, onChange, parsed.updates, parsed.value_source, pickerTarget],
  );

  const previewTemplateFor = useCallback(
    (source: ValueSourceConfig) => setPreviewTemplateId(source.template_id),
    [],
  );

  const handleIdentifierModeChange = useCallback(
    (value: string) => {
      onChange(
        buildUpdateConfigContextConfig(config, {
          device_identifier: {
            ...parsed.device_identifier,
            mode: value === "explicit" ? "explicit" : "from_context",
          },
        }),
      );
    },
    [config, onChange, parsed.device_identifier],
  );

  const handleExplicitIdChange = useCallback(
    (value: string) => {
      onChange(
        buildUpdateConfigContextConfig(config, {
          device_identifier: { ...parsed.device_identifier, id: value },
        }),
      );
    },
    [config, onChange, parsed.device_identifier],
  );

  const handleExplicitNameChange = useCallback(
    (value: string) => {
      onChange(
        buildUpdateConfigContextConfig(config, {
          device_identifier: { ...parsed.device_identifier, name: value },
        }),
      );
    },
    [config, onChange, parsed.device_identifier],
  );

  const isSourceConfigured = isNautobotSourceConfigured(config);
  const isUpdateMode = parsed.mode === "update";
  const isPathVisible = parsed.mode === "append";
  const hasAnyPath = isUpdateMode
    ? parsed.updates.some((entry) => entry.path.trim() !== "")
    : parsed.path.trim() !== "";
  const previewTemplate = templates.find((template) => template.id === previewTemplateId);
  const valueSourceShared = {
    templates,
    templatesLoading,
    templatesError,
    graph: { nodeId, workflowNodes, workflowEdges },
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{NAUTOBOT_SOURCE_ID_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            nautobot
          </Badge>
        </div>

        {isSourceConfigured ? (
          <p className="font-mono text-[11px] text-muted-foreground">
            {sourceId}
            {credentials.isReady ? (
              <span className="block truncate font-sans text-muted-foreground">
                {credentials.url}
              </span>
            ) : credentials.isLoading ? (
              <span className="block font-sans">Loading credentials…</span>
            ) : (
              <span className="block font-sans text-warning-foreground">
                Source not found in settings
              </span>
            )}
          </p>
        ) : (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
        )}

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setSourceOpen(true)}
        >
          {isSourceConfigured ? "Edit Source" : "Configure Source"}
        </Button>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">device_identifier</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            object
          </Badge>
        </div>
        <Select value={parsed.device_identifier.mode} onValueChange={handleIdentifierModeChange}>
          <SelectTrigger className="h-8 w-full text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="from_context" className="text-xs">
              From workflow context
            </SelectItem>
            <SelectItem value="explicit" className="text-xs">
              Explicit device
            </SelectItem>
          </SelectContent>
        </Select>
        {parsed.device_identifier.mode === "explicit" ? (
          <div className="space-y-1.5 pl-1">
            <Input
              value={parsed.device_identifier.id}
              onChange={(event) => handleExplicitIdChange(event.target.value)}
              placeholder="Device UUID"
              className="h-8 font-mono text-xs"
            />
            <Input
              value={parsed.device_identifier.name}
              onChange={(event) => handleExplicitNameChange(event.target.value)}
              placeholder="Device name"
              className="h-8 font-mono text-xs"
            />
          </div>
        ) : null}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">mode</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={parsed.mode} onValueChange={handleModeChange}>
          <SelectTrigger className="h-8 w-full text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="write" className="text-xs">
              Write (overwrite everything)
            </SelectItem>
            <SelectItem value="update" className="text-xs">
              Update (set a value at a path)
            </SelectItem>
            <SelectItem value="append" className="text-xs">
              Append (add a new key)
            </SelectItem>
          </SelectContent>
        </Select>
        <p className="text-[11px] leading-4 text-muted-foreground">
          {parsed.mode === "write"
            ? "Replaces the entire local config context, regardless of its current content."
            : parsed.mode === "update"
              ? "Sets the value at each path, leaving every other key untouched. All pairs are applied together in one request — if any fails, nothing is written for that device."
              : "Merges the new value into whatever is already at path — existing sibling keys are kept. Leave path empty to merge the value's own top-level keys directly into the document root."}
        </p>
      </div>

      {isUpdateMode ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">updates</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              array
            </Badge>
          </div>
          <UpdateEntryRows
            {...valueSourceShared}
            updates={parsed.updates}
            onChange={handleUpdatesChange}
            onBrowsePath={(index) => setPickerTarget({ field: "path", index })}
            onBrowseValue={(index) => setPickerTarget({ field: "value", index })}
            onPreviewTemplate={(index) => previewTemplateFor(parsed.updates[index].value_source)}
          />
          <p className="text-[11px] leading-4 text-muted-foreground">
            <PathHelpText mode="update" /> A rendered template&apos;s output is parsed as JSON when
            possible, otherwise used as a plain string.
          </p>
        </div>
      ) : (
        <>
          {isPathVisible ? (
            <div className="space-y-1.5">
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-xs font-medium">path</span>
                <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                  string
                </Badge>
              </div>
              <PathInput
                value={parsed.path}
                onChange={handlePathChange}
                onBrowse={() => setPickerTarget({ field: "path", index: null })}
                placeholder={APPEND_PATH_PLACEHOLDER}
                ariaLabel="Browse attributes for path"
              />
              <p className="text-[11px] leading-4 text-muted-foreground">
                <PathHelpText mode="append" />
              </p>
            </div>
          ) : null}

          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">value_source</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                object
              </Badge>
            </div>
            <ValueSourceFields
              {...valueSourceShared}
              value={parsed.value_source}
              onChange={handleValueSourceChange}
              onBrowse={() => setPickerTarget({ field: "value", index: null })}
              onPreviewTemplate={() => previewTemplateFor(parsed.value_source)}
              ariaLabel="value_source"
            />
            <p className="text-[11px] leading-4 text-muted-foreground">
              {parsed.mode === "write"
                ? "The resolved value must be a JSON object."
                : "A rendered template's output is parsed as JSON when possible, otherwise used as a plain string."}
            </p>
          </div>
        </>
      )}

      {hasAnyPath && parsed.mode !== "write" ? (
        <div className="space-y-1">
          <label className="flex items-center gap-1.5 text-xs font-medium">
            <Checkbox
              checked={parsed.create_local_if_missing}
              onCheckedChange={(checked) => handleCreateLocalChange(checked === true)}
            />
            Copy key from global config context if missing locally
          </label>
          <p className="text-[11px] leading-4 text-muted-foreground">
            Nautobot only lets this step change the device&apos;s local config context. If it
            doesn&apos;t contain a path&apos;s first key (e.g.{" "}
            <span className="font-mono">tacacs</span>) — or the device has no local context at
            all — that key is copied from the global config context first, then your change is
            applied. Other local keys are kept. If the key already exists locally, nothing is
            copied, and an entry that isn&apos;t in the local list is an error. The device keeps
            its own copy of the key.
          </p>
        </div>
      ) : null}

      <AttributePathPicker
        open={pickerTarget !== null}
        onClose={handlePickerClose}
        onSelect={handlePicked}
        nodeId={nodeId}
        workflowNodes={workflowNodes ?? []}
        workflowEdges={workflowEdges ?? []}
      />

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />

      <TemplateViewDialog
        templateId={previewTemplateId}
        templateName={previewTemplate?.name}
        open={previewTemplateId !== null}
        onClose={() => setPreviewTemplateId(null)}
      />
    </div>
  );
}

export const UpdateConfigContextPlugin: PluginUIComponent = {
  ConfigPanel: UpdateConfigContextConfigPanel,
  HelpPanel: UpdateConfigContextHelpPanel,
};
