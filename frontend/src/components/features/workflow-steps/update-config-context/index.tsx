"use client";

import { useCallback, useMemo, useState } from "react";

import { TemplateViewDialog } from "@/components/features/templates/components/template-view-dialog";
import { useTemplatesQuery } from "@/components/features/templates/hooks/use-templates-query";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { AttributePathPicker } from "@/components/features/workflow-steps/shared/attribute-path-picker";
import { AttributePathPreview } from "@/components/features/workflow-steps/shared/attribute-path-preview";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  type UpdateConfigContextMode,
  type ValueSourceType,
} from "./config";

const PATH_PLACEHOLDER_BY_MODE: Record<UpdateConfigContextMode, string> = {
  write: "",
  update: "credentials.0.password",
  append: "tacacs (leave empty to merge into the root)",
};

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
  const [pickerOpen, setPickerOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);

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

  const handleValueSourceTypeChange = useCallback(
    (value: string) => {
      onChange(
        buildUpdateConfigContextConfig(config, {
          value_source: { ...parsed.value_source, type: value as ValueSourceType },
        }),
      );
    },
    [config, onChange, parsed.value_source],
  );

  const handleAttributePathChange = useCallback(
    (value: string) => {
      onChange(
        buildUpdateConfigContextConfig(config, {
          value_source: { ...parsed.value_source, attribute_path: value },
        }),
      );
    },
    [config, onChange, parsed.value_source],
  );

  const handleTemplateChange = useCallback(
    (value: string) => {
      onChange(
        buildUpdateConfigContextConfig(config, {
          value_source: { ...parsed.value_source, template_id: Number(value) },
        }),
      );
    },
    [config, onChange, parsed.value_source],
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
  const isPathVisible = parsed.mode !== "write";
  const selectedTemplateId = parsed.value_source.template_id !== null
    ? String(parsed.value_source.template_id)
    : "";
  const selectedTemplate = templates.find(
    (template) => template.id === parsed.value_source.template_id,
  );
  const selectedTemplateMissing =
    parsed.value_source.template_id !== null &&
    !templatesLoading &&
    !templatesError &&
    !templates.some((template) => template.id === parsed.value_source.template_id);

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
              ? "Overwrites whatever is at path, leaving every other key untouched."
              : "Merges the new value into whatever is already at path — existing sibling keys are kept. Leave path empty to merge the value's own top-level keys directly into the document root."}
        </p>
      </div>

      {isPathVisible ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">path</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <Input
            value={parsed.path}
            onChange={(event) => handlePathChange(event.target.value)}
            placeholder={PATH_PLACEHOLDER_BY_MODE[parsed.mode]}
            className="h-8 font-mono text-xs"
          />
          <p className="text-[11px] leading-4 text-muted-foreground">
            {parsed.mode === "append"
              ? (
                <>
                  Dotted path into local_config_context_data. Use a numeric segment
                  for a list item, e.g.{" "}
                  <span className="font-mono">credentials.0.password</span>. Leave
                  empty to merge the resolved value&apos;s own top-level keys
                  directly into the document root instead of nesting them under a
                  new key. List indices must already exist — lists are never
                  extended.
                </>
              )
              : (
                <>
                  Dotted path into local_config_context_data. Use a numeric segment
                  for a list item, e.g.{" "}
                  <span className="font-mono">credentials.0.password</span>. List
                  indices must already exist — lists are never extended.
                </>
              )}
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
        <Select value={parsed.value_source.type} onValueChange={handleValueSourceTypeChange}>
          <SelectTrigger className="h-8 w-full text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="attribute" className="text-xs">
              Device attribute
            </SelectItem>
            <SelectItem value="template" className="text-xs">
              Rendered template
            </SelectItem>
          </SelectContent>
        </Select>

        {parsed.value_source.type === "attribute" ? (
          <div className="space-y-1.5 pl-1">
            <div className="flex items-center gap-1.5">
              <Input
                value={parsed.value_source.attribute_path}
                onChange={(event) => handleAttributePathChange(event.target.value)}
                placeholder="tacacs.shared_secret"
                className="h-8 font-mono text-xs"
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 shrink-0 text-xs"
                onClick={() => setPickerOpen(true)}
              >
                Browse attributes
              </Button>
            </div>
            <AttributePathPreview
              path={parsed.value_source.attribute_path}
              nodeId={nodeId}
              workflowNodes={workflowNodes ?? []}
              workflowEdges={workflowEdges ?? []}
            />
            <AttributePathPicker
              open={pickerOpen}
              onClose={() => setPickerOpen(false)}
              onSelect={handleAttributePathChange}
              nodeId={nodeId}
              workflowNodes={workflowNodes ?? []}
              workflowEdges={workflowEdges ?? []}
            />
          </div>
        ) : (
          <div className="space-y-1.5 pl-1">
            <Select
              value={selectedTemplateId}
              onValueChange={handleTemplateChange}
              disabled={templatesLoading || templates.length === 0}
            >
              <SelectTrigger className="h-8 w-full text-xs">
                <SelectValue
                  placeholder={templatesLoading ? "Loading templates…" : "Select a stored template"}
                />
              </SelectTrigger>
              <SelectContent>
                {templates.map((template) => (
                  <SelectItem key={template.id} value={String(template.id)} className="text-xs">
                    {template.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {templatesError ? (
              <p className="text-[11px] leading-4 text-destructive">
                Failed to load stored templates.
              </p>
            ) : null}
            {!templatesLoading && !templatesError && templates.length === 0 ? (
              <p className="text-[11px] leading-4 text-muted-foreground">
                No stored Jinja2 templates yet. Create one in the Templates section first.
              </p>
            ) : null}
            {selectedTemplateMissing ? (
              <p className="text-[11px] leading-4 text-destructive">
                The previously selected template no longer exists. Pick another one.
              </p>
            ) : null}
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 w-full text-xs"
              disabled={parsed.value_source.template_id === null || selectedTemplateMissing}
              onClick={() => setPreviewOpen(true)}
            >
              Preview Template
            </Button>
          </div>
        )}
        <p className="text-[11px] leading-4 text-muted-foreground">
          {parsed.mode === "write"
            ? "The resolved value must be a JSON object."
            : "A rendered template's output is parsed as JSON when possible, otherwise used as a plain string."}
        </p>
      </div>

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />

      <TemplateViewDialog
        templateId={parsed.value_source.template_id}
        templateName={selectedTemplate?.name}
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
      />
    </div>
  );
}

export const UpdateConfigContextPlugin: PluginUIComponent = {
  ConfigPanel: UpdateConfigContextConfigPanel,
  HelpPanel: UpdateConfigContextHelpPanel,
};
