"use client";

import { ArrowLeft, FileCode, Play, RefreshCw, Save } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";

import { AddVariableDialog } from "./components/add-variable-dialog";
import { CodeEditorPanel } from "./components/code-editor-panel";
import { GeneralPanel } from "./components/general-panel";
import { NetmikoOptionsPanel } from "./components/netmiko-options-panel";
import { RenderedOutputDialog } from "./components/rendered-output-dialog";
import { VariablesPanel } from "./components/variables-panel";
import { TEMPLATE_CATEGORY } from "./constants";
import { useNautobotSources } from "./hooks/use-nautobot-sources";
import { useTemplateMutations } from "./hooks/use-template-mutations";
import { useTemplateQuery } from "./hooks/use-template-query";
import { useTemplateRender } from "./hooks/use-template-render";
import { useTemplateVariables } from "./hooks/use-template-variables";
import type { DeviceSummary, TemplateType, TemplateVariableRecord } from "./types";

function bareIp(value: string | null): string | null {
  if (!value) {
    return null;
  }
  return value.split("/")[0] || null;
}

function TemplateEditorContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { toast } = useToast();
  const { apiCall } = useApi();

  const idParam = searchParams.get("id");
  const templateId = idParam ? Number(idParam) : null;
  const isEditMode = templateId !== null;

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [templateType, setTemplateType] = useState<TemplateType>("jinja2");
  const [content, setContent] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [selectedDevice, setSelectedDevice] = useState<DeviceSummary | null>(null);
  const [preRunCommand, setPreRunCommand] = useState("");
  const [credentialId, setCredentialId] = useState("none");
  const [selectedVariableId, setSelectedVariableId] = useState<string | null>(null);
  const [addVariableOpen, setAddVariableOpen] = useState(false);

  const variableManager = useTemplateVariables();
  const renderer = useTemplateRender();
  const { createTemplate, updateTemplate } = useTemplateMutations();
  const { sources } = useNautobotSources();

  // Fall back to the first configured source until the user picks another.
  const effectiveSourceId = sourceId || sources[0]?.sourceId || "";
  const sourceCredentials = useNautobotSourceCredentials({
    sourceId: effectiveSourceId || undefined,
    enabled: Boolean(effectiveSourceId),
  });
  const templateQuery = useTemplateQuery({ templateId, enabled: isEditMode });

  const loadedRef = useRef(false);
  const lastDeviceIdRef = useRef<string | null>(null);
  const {
    updateDeviceData,
    togglePreRunVariables,
    setPreRunExecuting,
    setPreRunOutput,
    loadCustomVariables,
  } = variableManager;

  // Populate the editor once when an existing template loads.
  useEffect(() => {
    if (!isEditMode || loadedRef.current || !templateQuery.data) {
      return;
    }
    const template = templateQuery.data;
    loadedRef.current = true;
    setName(template.name);
    setDescription(template.description ?? "");
    setTemplateType((template.template_type as TemplateType) ?? "jinja2");
    setContent(template.content ?? "");
    setPreRunCommand(template.pre_run_command ?? "");
    setCredentialId(
      template.credential_id != null ? String(template.credential_id) : "none",
    );
    loadCustomVariables(template.variables ?? {});
  }, [isEditMode, templateQuery.data, loadCustomVariables]);

  // Show/hide the pre-run variables based on whether a command is set.
  useEffect(() => {
    togglePreRunVariables(preRunCommand.trim().length > 0);
  }, [preRunCommand, togglePreRunVariables]);

  // Fetch device context when the selected test device changes.
  useEffect(() => {
    if (!selectedDevice) {
      lastDeviceIdRef.current = null;
      updateDeviceData(null);
      return;
    }
    if (lastDeviceIdRef.current === selectedDevice.id) {
      return;
    }
    if (!sourceCredentials.isReady) {
      return;
    }

    lastDeviceIdRef.current = selectedDevice.id;
    const devices = [
      {
        id: selectedDevice.id,
        name: selectedDevice.name,
        primary_ip4: selectedDevice.primary_ip4,
        platform: selectedDevice.platform,
        network_driver: selectedDevice.network_driver,
      },
    ];

    let active = true;
    apiCall<Record<string, unknown>>("sources/nautobot/devices/details", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        nautobot_url: sourceCredentials.url,
        nautobot_token: sourceCredentials.token,
        device_id: selectedDevice.id,
      }),
    })
      .then((details) => {
        if (active) {
          updateDeviceData({ devices, device_details: details });
        }
      })
      .catch(() => {
        if (active) {
          updateDeviceData({ devices, device_details: {} });
        }
      });

    return () => {
      active = false;
    };
  }, [selectedDevice, sourceCredentials.isReady, sourceCredentials.url, sourceCredentials.token, apiCall, updateDeviceData]);

  const existingVariableNames = useMemo(
    () => variableManager.variables.map((variable) => variable.name),
    [variableManager.variables],
  );

  const canExecutePreRun = Boolean(
    selectedDevice && credentialId !== "none" && preRunCommand.trim(),
  );

  const handleExecutePreRun = useCallback(async () => {
    if (!selectedDevice) {
      toast({
        title: "Missing device",
        description: "Select a test device first",
        variant: "destructive",
      });
      return;
    }
    if (credentialId === "none") {
      toast({
        title: "Missing credentials",
        description: "Select SSH credentials to run the command",
        variant: "destructive",
      });
      return;
    }

    const host = bareIp(selectedDevice.primary_ip4) ?? selectedDevice.name ?? "";
    if (!host) {
      toast({
        title: "No device address",
        description: "The selected device has no primary IP or name",
        variant: "destructive",
      });
      return;
    }

    setPreRunExecuting(true);
    try {
      const response = await apiCall<{
        success: boolean;
        raw_output: string;
        parsed_output: unknown;
        error: string | null;
      }>("netmiko/run-command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          host,
          platform: selectedDevice.platform,
          network_driver: selectedDevice.network_driver,
          credential_id: Number(credentialId),
          command: preRunCommand.trim(),
        }),
      });

      if (!response.success) {
        throw new Error(response.error ?? "Command execution failed");
      }

      const parsed =
        typeof response.parsed_output === "string"
          ? response.parsed_output
          : JSON.stringify(response.parsed_output ?? "", null, 2);
      setPreRunOutput(response.raw_output ?? "", parsed);
      toast({
        title: "Command executed",
        description: "pre_run.raw and pre_run.parsed were populated",
      });
    } catch (error) {
      setPreRunExecuting(false);
      toast({
        title: "Execution failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    }
  }, [selectedDevice, credentialId, preRunCommand, apiCall, toast, setPreRunExecuting, setPreRunOutput]);

  const handleRender = useCallback(() => {
    renderer.render(content, variableManager.variables);
  }, [renderer, content, variableManager.variables]);

  const handleAddVariable = useCallback(
    (variableName: string, value: string) => {
      const id = variableManager.addVariable(variableName, value);
      setSelectedVariableId(id);
    },
    [variableManager],
  );

  const handleSave = useCallback(async () => {
    if (!name.trim()) {
      toast({
        title: "Validation error",
        description: "Template name is required",
        variant: "destructive",
      });
      return;
    }

    const variables: Record<string, TemplateVariableRecord> = {};
    for (const variable of variableManager.variables) {
      if (variable.name && !variable.isAutoFilled) {
        variables[variable.name] = {
          value: variable.value,
          type: variable.type || "custom",
        };
      }
    }

    const payload = {
      name: name.trim(),
      description: description || null,
      template_type: templateType,
      category: TEMPLATE_CATEGORY,
      content,
      variables,
      pre_run_command: preRunCommand.trim() || null,
      credential_id: credentialId !== "none" ? Number(credentialId) : null,
    };

    try {
      if (isEditMode && templateId !== null) {
        await updateTemplate.mutateAsync({ templateId, payload });
      } else {
        await createTemplate.mutateAsync(payload);
      }
      router.push("/templates");
    } catch {
      // error toast handled by mutation hooks
    }
  }, [
    name,
    description,
    templateType,
    content,
    preRunCommand,
    credentialId,
    variableManager.variables,
    isEditMode,
    templateId,
    updateTemplate,
    createTemplate,
    router,
    toast,
  ]);

  const isSaving = createTemplate.isPending || updateTemplate.isPending;

  if (isEditMode && templateQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <RefreshCw className="mr-2 size-5 animate-spin" />
        Loading template…
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <FileCode className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-foreground">
                {isEditMode ? "Edit Template" : "Template Editor"}
              </h1>
              <p className="mt-1 text-muted-foreground">
                Create and edit Jinja2 templates with variable support and live preview
              </p>
            </div>
          </div>
          <Button type="button" variant="outline" onClick={() => router.push("/templates")}>
            <ArrowLeft className="size-4" />
            Back
          </Button>
        </div>

        <GeneralPanel
          name={name}
          description={description}
          templateType={templateType}
          onNameChange={setName}
          onDescriptionChange={setDescription}
          onTemplateTypeChange={setTemplateType}
        />

        <NetmikoOptionsPanel
          sources={sources}
          sourceId={effectiveSourceId}
          nautobotUrl={sourceCredentials.url}
          nautobotToken={sourceCredentials.token}
          sourceReady={sourceCredentials.isReady}
          preRunCommand={preRunCommand}
          credentialId={credentialId}
          onSourceChange={setSourceId}
          onSelectDevice={setSelectedDevice}
          onPreRunCommandChange={setPreRunCommand}
          onCredentialChange={setCredentialId}
        />

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[340px_1fr]" style={{ minHeight: 480 }}>
          <div className="overflow-hidden rounded-lg border bg-card">
            <VariablesPanel
              variables={variableManager.variables}
              selectedId={selectedVariableId}
              canExecutePreRun={canExecutePreRun}
              onSelect={setSelectedVariableId}
              onAdd={() => setAddVariableOpen(true)}
              onRemove={variableManager.removeVariable}
              onUpdateValue={variableManager.updateVariableValue}
              onExecutePreRun={handleExecutePreRun}
            />
          </div>

          <div className="min-h-[480px] overflow-hidden rounded-lg border">
            <CodeEditorPanel value={content} language={templateType} onChange={setContent} />
          </div>
        </div>

        <div className="flex items-center justify-between border-t pt-4">
          <Button
            type="button"
            variant="outline"
            disabled={renderer.isRendering || !content.trim()}
            onClick={handleRender}
          >
            {renderer.isRendering ? (
              <RefreshCw className="size-4 animate-spin" />
            ) : (
              <Play className="size-4" />
            )}
            Show Rendered Template
          </Button>

          <Button type="button" disabled={isSaving} onClick={handleSave}>
            {isSaving ? <RefreshCw className="size-4 animate-spin" /> : <Save className="size-4" />}
            {isEditMode ? "Update Template" : "Save Template"}
          </Button>
        </div>
      </div>

      <RenderedOutputDialog
        open={renderer.showDialog}
        result={renderer.result}
        onOpenChange={renderer.setShowDialog}
      />

      <AddVariableDialog
        open={addVariableOpen}
        existingNames={existingVariableNames}
        onClose={() => setAddVariableOpen(false)}
        onAdd={handleAddVariable}
      />
    </div>
  );
}

export function TemplateEditorPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <RefreshCw className="mr-2 size-5 animate-spin" />
          Loading editor…
        </div>
      }
    >
      <TemplateEditorContent />
    </Suspense>
  );
}
