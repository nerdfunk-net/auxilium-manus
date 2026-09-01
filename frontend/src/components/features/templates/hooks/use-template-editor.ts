"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useDeviceAttributesQuery } from "@/hooks/queries/use-device-attributes-query";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";
import { useWorkflowQuery } from "@/hooks/queries/use-workflow-query";
import { useWorkflowsQuery } from "@/hooks/queries/use-workflows-query";

import { useNautobotSources } from "./use-nautobot-sources";
import { useTemplateEditorDevice } from "./use-template-editor-device";
import { useTemplateEditorSave } from "./use-template-editor-save";
import { useTemplateQuery } from "./use-template-query";
import { useTemplateRender } from "./use-template-render";
import { useTemplateVariables } from "./use-template-variables";
import type { DeviceSummary, TemplateType } from "../types";

export function useTemplateEditor() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const idParam = searchParams.get("id");
  const templateId = idParam ? Number(idParam) : null;
  const isEditMode = templateId !== null;

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [templateType, setTemplateType] = useState<TemplateType>("jinja2");
  const [content, setContent] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [selectedDevice, setSelectedDevice] = useState<DeviceSummary | null>(null);
  const [commands, setCommands] = useState<string[]>([]);
  const [useTextfsm, setUseTextfsm] = useState(false);
  const [credentialId, setCredentialId] = useState("none");
  const [attributes, setAttributes] = useState<string[]>([]);
  const [selectedVariableId, setSelectedVariableId] = useState<string | null>(null);
  const [addVariableOpen, setAddVariableOpen] = useState(false);
  const [variablesHelpOpen, setVariablesHelpOpen] = useState(false);
  const [commandsDialogOpen, setCommandsDialogOpen] = useState(false);
  const [attributesDialogOpen, setAttributesDialogOpen] = useState(false);
  const [getDeviceConfigs, setGetDeviceConfigs] = useState(false);
  // Reference workflow whose static attributes are previewed as the
  // `run_input` variable — a per-session discovery aid, never persisted with
  // the template (see doc/WORKFLOW-STEPS.md "Static attributes").
  const [referenceWorkflowId, setReferenceWorkflowId] = useState<number | null>(null);
  const [linkWorkflowDialogOpen, setLinkWorkflowDialogOpen] = useState(false);

  const variableManager = useTemplateVariables();
  const renderer = useTemplateRender();
  const { sources } = useNautobotSources();
  const workflowsQuery = useWorkflowsQuery();
  const referenceWorkflowQuery = useWorkflowQuery(referenceWorkflowId);

  // Fall back to the first configured source until the user picks another.
  const effectiveSourceId = sourceId || sources[0]?.sourceId || "";
  const sourceCredentials = useNautobotSourceCredentials({
    sourceId: effectiveSourceId || undefined,
    enabled: Boolean(effectiveSourceId),
  });
  const templateQuery = useTemplateQuery({ templateId, enabled: isEditMode });
  const deviceAttributesQuery = useDeviceAttributesQuery({
    deviceId: selectedDevice?.id ?? null,
    sourceId: sourceCredentials.sourceId,
    attributes,
    enabled: sourceCredentials.isReady,
  });
  // Read the query result during render so React Query re-renders this hook when
  // the attributes-triggered refetch resolves — not only when the test device is
  // re-picked. Consuming `.data`/`.error` solely inside the effect below left the
  // `nautobot` variable stale until the device was re-selected.
  const { data: deviceAttributesData, error: deviceAttributesError } =
    deviceAttributesQuery;

  const loadedRef = useRef(false);
  const {
    setDeviceInfo,
    setNautobotAttributes,
    toggleCommandVariables,
    setCommandResults,
    toggleParsedConfigVariable,
    setParsedConfig,
    setRunInputSource,
    loadCustomVariables,
  } = variableManager;

  const cleanedCommands = useMemo(
    () => commands.map((command) => command.trim()).filter(Boolean),
    [commands],
  );

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
    setCommands(template.pre_run_commands ?? []);
    setUseTextfsm(Boolean(template.pre_run_use_textfsm));
    setAttributes(template.nautobot_attributes ?? []);
    setCredentialId(
      template.credential_id != null ? String(template.credential_id) : "none",
    );
    loadCustomVariables(template.variables ?? {});
  }, [isEditMode, templateQuery.data, loadCustomVariables]);

  // Show/hide the command variables based on whether any command is configured.
  useEffect(() => {
    toggleCommandVariables(cleanedCommands.length > 0);
  }, [cleanedCommands.length, toggleCommandVariables]);

  // Show/hide the parsed-config variable based on the "Get Configs" checkbox.
  useEffect(() => {
    toggleParsedConfigVariable(getDeviceConfigs);
  }, [getDeviceConfigs, toggleParsedConfigVariable]);

  // Build the `device` variable from the selected test device (matches the
  // workflow step's device.* namespace).
  useEffect(() => {
    if (!selectedDevice) {
      setDeviceInfo(null);
      return;
    }
    setDeviceInfo({
      name: selectedDevice.name,
      hostname: selectedDevice.name,
      id: selectedDevice.id,
      primary_ip4: selectedDevice.primary_ip4?.split("/")[0] ?? "",
      platform: selectedDevice.platform ?? "",
      network_driver: selectedDevice.network_driver ?? "",
      source: effectiveSourceId,
      source_id: selectedDevice.id,
    });
  }, [selectedDevice, effectiveSourceId, setDeviceInfo]);

  // Mirror the device-attributes query result into the `nautobot` variable
  // bag, using the same query as the workflow step.
  useEffect(() => {
    if (!selectedDevice) {
      setNautobotAttributes(null);
      return;
    }
    if (deviceAttributesData) {
      setNautobotAttributes(deviceAttributesData);
    } else if (deviceAttributesError) {
      setNautobotAttributes({});
    }
  }, [
    selectedDevice,
    deviceAttributesData,
    deviceAttributesError,
    setNautobotAttributes,
  ]);

  // Reset the parsed-config preview whenever the inputs that would
  // invalidate it change — but do NOT auto-fetch. Fetching live device
  // config over SSH is an explicit action (see fetchDeviceConfigsMutation /
  // the "Fetch configs" button).
  useEffect(() => {
    if (!getDeviceConfigs || !selectedDevice || credentialId === "none") {
      setParsedConfig(null);
    }
  }, [getDeviceConfigs, selectedDevice, credentialId, setParsedConfig]);

  const {
    isFetchingConfigs,
    canFetchConfigs,
    handleFetchConfigs,
    canExecuteCommands,
    isExecutingCommands,
    executeHint,
    handleExecuteCommands,
  } = useTemplateEditorDevice({
    selectedDevice,
    credentialId,
    cleanedCommands,
    useTextfsm,
    setCommandResults,
    setParsedConfig,
  });

  // Preview the linked reference workflow's static_attributes as the
  // `run_input` variable. Purely a discovery aid — never saved with the
  // template (see doc/WORKFLOW-STEPS.md "Static attributes").
  useEffect(() => {
    if (referenceWorkflowId === null) {
      setRunInputSource(null);
      return;
    }
    const workflow = referenceWorkflowQuery.data;
    if (!workflow) {
      return;
    }
    setRunInputSource({
      workflowName: workflow.name,
      attributes: workflow.static_attributes ?? [],
    });
  }, [referenceWorkflowId, referenceWorkflowQuery.data, setRunInputSource]);

  const existingVariableNames = useMemo(
    () => variableManager.variables.map((variable) => variable.name),
    [variableManager.variables],
  );

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

  const { handleSave, handleExport, isSaving } = useTemplateEditorSave({
    name,
    description,
    templateType,
    content,
    cleanedCommands,
    useTextfsm,
    attributes,
    credentialId,
    variableManager,
    isEditMode,
    templateId,
  });

  const isLoading = isEditMode && templateQuery.isLoading;

  return useMemo(
    () => ({
      router,
      isEditMode,
      isLoading,
      name,
      setName,
      description,
      setDescription,
      templateType,
      setTemplateType,
      content,
      setContent,
      sources,
      effectiveSourceId,
      sourceReady: sourceCredentials.isReady,
      cleanedCommandCount: cleanedCommands.length,
      attributeCount: attributes.length,
      credentialId,
      getDeviceConfigs,
      isFetchingConfigs,
      canFetchConfigs,
      handleFetchConfigs,
      setSourceId,
      setSelectedDevice,
      setCommandsDialogOpen,
      setAttributesDialogOpen,
      setCredentialId,
      setGetDeviceConfigs,
      variableManager,
      selectedVariableId,
      setSelectedVariableId,
      setAddVariableOpen,
      setVariablesHelpOpen,
      setLinkWorkflowDialogOpen,
      renderer,
      handleRender,
      handleExport,
      handleSave,
      isSaving,
      addVariableOpen,
      existingVariableNames,
      handleAddVariable,
      variablesHelpOpen,
      commandsDialogOpen,
      commands,
      useTextfsm,
      canExecuteCommands,
      isExecutingCommands,
      executeHint,
      setCommands,
      setUseTextfsm,
      handleExecuteCommands,
      attributesDialogOpen,
      attributes,
      setAttributes,
      linkWorkflowDialogOpen,
      workflows: workflowsQuery.data?.workflows ?? [],
      referenceWorkflowId,
      setReferenceWorkflowId,
    }),
    [
      router,
      isEditMode,
      isLoading,
      name,
      description,
      templateType,
      content,
      sources,
      effectiveSourceId,
      sourceCredentials.isReady,
      cleanedCommands.length,
      credentialId,
      getDeviceConfigs,
      isFetchingConfigs,
      canFetchConfigs,
      handleFetchConfigs,
      variableManager,
      selectedVariableId,
      renderer,
      handleRender,
      handleExport,
      handleSave,
      isSaving,
      addVariableOpen,
      existingVariableNames,
      handleAddVariable,
      variablesHelpOpen,
      commandsDialogOpen,
      commands,
      useTextfsm,
      canExecuteCommands,
      isExecutingCommands,
      executeHint,
      handleExecuteCommands,
      attributesDialogOpen,
      attributes,
      linkWorkflowDialogOpen,
      workflowsQuery.data?.workflows,
      referenceWorkflowId,
    ],
  );
}
