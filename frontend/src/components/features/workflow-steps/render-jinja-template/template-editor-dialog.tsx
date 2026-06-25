"use client";

import dynamic from "next/dynamic";
import { Loader2, Play, ShieldCheck } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { AttributesDialog } from "@/components/features/workflow-steps/get-nautobot-attributes/attributes-dialog";
import {
  ATTRIBUTE_GROUPS,
  type AttributeGroupKey,
} from "@/components/features/workflow-steps/get-nautobot-attributes/types";
import { NautobotSourceSelectDialog } from "@/components/features/workflow-steps/shared/nautobot-source-select-dialog";
import type { WorkflowCanvasNode } from "@/components/features/workflows/types/workflow-canvas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useGetNautobotDevicesPreviewMutation } from "@/hooks/queries/use-get-nautobot-devices-preview-mutation";
import {
  useJinjaDeviceSampleContextMutation,
  useJinjaNautobotSampleContextMutation,
  useJinjaPreviewMutation,
  useJinjaValidateMutation,
} from "@/hooks/queries/use-jinja-template-mutations";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";
import { useToast } from "@/hooks/use-toast";

import {
  buildRenderJinjaTemplateConfig,
  parseRenderJinjaTemplateConfig,
  type RenderJinjaTemplateConfig,
} from "./template-config";
import {
  devicePreviewToPayload,
  inventoryOperationsFromNode,
  listInventorySteps,
} from "./workflow-device-samples";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full min-h-[320px] items-center justify-center rounded-md border bg-muted/30 text-sm text-muted-foreground">
      Loading editor…
    </div>
  ),
});

interface TemplateEditorDialogProps {
  open: boolean;
  config: Record<string, unknown>;
  workflowNodes: WorkflowCanvasNode[];
  onClose: () => void;
  onSave: (patch: Partial<RenderJinjaTemplateConfig>) => void;
}

export function TemplateEditorDialog({
  open,
  config,
  workflowNodes,
  onClose,
  onSave,
}: TemplateEditorDialogProps) {
  const parsed = useMemo(() => parseRenderJinjaTemplateConfig(config), [config]);
  const { toast } = useToast();

  const [template, setTemplate] = useState(() => parsed.template);
  const [nautobotSourceId, setNautobotSourceId] = useState(
    () => parsed.editor_nautobot_source_id,
  );
  const [deviceName, setDeviceName] = useState(() => parsed.editor_sample_device_name);
  const [attributes, setAttributes] = useState<AttributeGroupKey[]>(() =>
    parsed.editor_list_of_attributes.filter((item): item is AttributeGroupKey =>
      ATTRIBUTE_GROUPS.some((group) => group.key === item),
    ),
  );
  const [sampleContext, setSampleContext] = useState<Record<string, unknown> | null>(null);
  const [previewOutput, setPreviewOutput] = useState("");
  const [sourceOpen, setSourceOpen] = useState(false);
  const [attributesOpen, setAttributesOpen] = useState(false);
  const [selectedInventoryNodeId, setSelectedInventoryNodeId] = useState(
    () => listInventorySteps(workflowNodes)[0]?.nodeId ?? "",
  );
  const [selectedWorkflowDeviceId, setSelectedWorkflowDeviceId] = useState("");

  const validateMutation = useJinjaValidateMutation();
  const previewMutation = useJinjaPreviewMutation();
  const nautobotSampleMutation = useJinjaNautobotSampleContextMutation();
  const deviceSampleMutation = useJinjaDeviceSampleContextMutation();
  const inventoryPreviewMutation = useGetNautobotDevicesPreviewMutation();

  const inventorySteps = useMemo(() => listInventorySteps(workflowNodes), [workflowNodes]);
  const selectedInventoryNode = useMemo(
    () => workflowNodes.find((node) => node.id === selectedInventoryNodeId) ?? null,
    [workflowNodes, selectedInventoryNodeId],
  );
  const selectedInventoryStep = useMemo(
    () => inventorySteps.find((step) => step.nodeId === selectedInventoryNodeId) ?? null,
    [inventorySteps, selectedInventoryNodeId],
  );
  const inventoryCredentials = useNautobotSourceCredentials({
    sourceId: selectedInventoryStep?.sourceId ?? "",
  });

  const handleValidate = useCallback(async () => {
    try {
      await validateMutation.mutateAsync({ template });
      toast({ title: "Template valid", description: "Jinja syntax looks good." });
    } catch (error) {
      toast({
        title: "Template error",
        description: error instanceof Error ? error.message : "Validation failed",
        variant: "destructive",
      });
    }
  }, [template, toast, validateMutation]);

  const handlePreview = useCallback(async () => {
    if (!sampleContext) {
      toast({
        title: "Load sample data first",
        description: "Pick a Nautobot or workflow device before previewing.",
        variant: "destructive",
      });
      return;
    }
    try {
      const rendered = await previewMutation.mutateAsync({
        template,
        context: sampleContext,
      });
      setPreviewOutput(rendered);
    } catch (error) {
      toast({
        title: "Preview failed",
        description: error instanceof Error ? error.message : "Could not render template",
        variant: "destructive",
      });
    }
  }, [previewMutation, sampleContext, template, toast]);

  const handleLoadNautobotSample = useCallback(async () => {
    if (!nautobotSourceId.trim()) {
      toast({
        title: "Nautobot source required",
        description: "Configure a Nautobot source for sample data.",
        variant: "destructive",
      });
      return;
    }
    if (!deviceName.trim()) {
      toast({
        title: "Device name required",
        description: "Enter a device name to load from Nautobot.",
        variant: "destructive",
      });
      return;
    }
    try {
      const context = await nautobotSampleMutation.mutateAsync({
        nautobot_source_id: nautobotSourceId.trim(),
        device_name: deviceName.trim(),
        list_of_attributes: attributes,
      });
      setSampleContext(context);
      toast({
        title: "Sample data loaded",
        description: `Loaded Nautobot context for ${deviceName.trim()}.`,
      });
    } catch (error) {
      toast({
        title: "Failed to load sample data",
        description: error instanceof Error ? error.message : "Nautobot lookup failed",
        variant: "destructive",
      });
    }
  }, [attributes, deviceName, nautobotSampleMutation, nautobotSourceId, toast]);

  const handleLoadWorkflowDevices = useCallback(async () => {
    if (!selectedInventoryNode || !selectedInventoryStep) {
      return;
    }
    if (!inventoryCredentials.isReady) {
      toast({
        title: "Inventory source unavailable",
        description: "Configure credentials for the selected inventory step.",
        variant: "destructive",
      });
      return;
    }
    try {
      await inventoryPreviewMutation.mutateAsync({
        nautobot_url: inventoryCredentials.url,
        nautobot_token: inventoryCredentials.token,
        operations: inventoryOperationsFromNode(selectedInventoryNode),
      });
    } catch (error) {
      toast({
        title: "Failed to load workflow devices",
        description: error instanceof Error ? error.message : "Inventory preview failed",
        variant: "destructive",
      });
    }
  }, [
    inventoryCredentials.isReady,
    inventoryCredentials.token,
    inventoryCredentials.url,
    inventoryPreviewMutation,
    selectedInventoryNode,
    selectedInventoryStep,
    toast,
  ]);

  const handleWorkflowDeviceSelect = useCallback(
    async (deviceId: string) => {
      setSelectedWorkflowDeviceId(deviceId);
      const device = inventoryPreviewMutation.data?.devices.find((item) => item.id === deviceId);
      const sourceId = selectedInventoryStep?.sourceId ?? "";
      if (!device || !sourceId) {
        return;
      }
      try {
        const context = await deviceSampleMutation.mutateAsync({
          device: devicePreviewToPayload(device, sourceId),
        });
        setSampleContext(context);
        toast({
          title: "Workflow device loaded",
          description: `Using ${device.name ?? device.id} as sample context.`,
        });
      } catch (error) {
        toast({
          title: "Failed to build device context",
          description: error instanceof Error ? error.message : "Sample context failed",
          variant: "destructive",
        });
      }
    },
    [deviceSampleMutation, inventoryPreviewMutation.data?.devices, selectedInventoryStep?.sourceId, toast],
  );

  const handleSave = useCallback(() => {
    onSave(
      buildRenderJinjaTemplateConfig(config, {
        template,
        editor_nautobot_source_id: nautobotSourceId,
        editor_sample_device_name: deviceName,
        editor_list_of_attributes: attributes,
      }),
    );
    onClose();
  }, [attributes, config, deviceName, nautobotSourceId, onClose, onSave, template]);

  const workflowDevices = inventoryPreviewMutation.data?.devices ?? [];
  const isBusy =
    validateMutation.isPending ||
    previewMutation.isPending ||
    nautobotSampleMutation.isPending ||
    deviceSampleMutation.isPending ||
    inventoryPreviewMutation.isPending;

  return (
    <>
      <Dialog open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
        <DialogContent className="flex max-h-[90vh] w-[min(96vw,72rem)] max-w-none flex-col gap-0 overflow-hidden p-0">
          <DialogHeader className="border-b px-6 py-4">
            <DialogTitle>Template editor</DialogTitle>
          </DialogHeader>

          <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 lg:grid-cols-[minmax(0,1.4fr)_minmax(18rem,0.8fr)]">
            <div className="min-h-[360px] border-b p-4 lg:border-b-0 lg:border-r">
              <MonacoEditor
                height="min(52vh, 560px)"
                defaultLanguage="jinja"
                theme="vs-dark"
                value={template}
                onChange={(value) => setTemplate(value ?? "")}
                options={{
                  minimap: { enabled: false },
                  fontSize: 13,
                  wordWrap: "on",
                  scrollBeyondLastLine: false,
                }}
              />
            </div>

            <div className="flex min-h-0 flex-col gap-4 overflow-y-auto p-4">
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">Nautobot sample data</span>
                  <Badge variant="secondary">editor only</Badge>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground">Source</Label>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 w-full justify-start font-mono text-xs"
                    onClick={() => setSourceOpen(true)}
                  >
                    {nautobotSourceId || "Select Nautobot source"}
                  </Button>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground">Device name</Label>
                  <Input
                    value={deviceName}
                    onChange={(event) => setDeviceName(event.target.value)}
                    placeholder="router1"
                    className="h-8 font-mono text-xs"
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground">Attributes</Label>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 w-full text-xs"
                    onClick={() => setAttributesOpen(true)}
                  >
                    {attributes.length} group{attributes.length === 1 ? "" : "s"} selected
                  </Button>
                </div>
                <Button
                  type="button"
                  size="sm"
                  className="w-full"
                  disabled={isBusy}
                  onClick={() => void handleLoadNautobotSample()}
                >
                  {nautobotSampleMutation.isPending ? (
                    <Loader2 className="mr-2 size-4 animate-spin" />
                  ) : null}
                  Load from Nautobot
                </Button>
              </div>

              <div className="space-y-3 border-t pt-4">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">Workflow device</span>
                  <Badge variant="secondary">canvas inventory</Badge>
                </div>
                {inventorySteps.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    Add a Get Nautobot Devices step to pick a device from your workflow
                    inventory filter.
                  </p>
                ) : (
                  <>
                    <div className="space-y-2">
                      <Label className="text-xs text-muted-foreground">Inventory step</Label>
                      <Select
                        value={selectedInventoryNodeId}
                        onValueChange={setSelectedInventoryNodeId}
                      >
                        <SelectTrigger className="h-8 text-xs">
                          <SelectValue placeholder="Select inventory step" />
                        </SelectTrigger>
                        <SelectContent>
                          {inventorySteps.map((step) => (
                            <SelectItem key={step.nodeId} value={step.nodeId}>
                              {step.title}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="w-full"
                      disabled={isBusy}
                      onClick={() => void handleLoadWorkflowDevices()}
                    >
                      {inventoryPreviewMutation.isPending ? (
                        <Loader2 className="mr-2 size-4 animate-spin" />
                      ) : null}
                      Load devices from step
                    </Button>
                    {workflowDevices.length > 0 ? (
                      <div className="space-y-2">
                        <Label className="text-xs text-muted-foreground">Device</Label>
                        <Select
                          value={selectedWorkflowDeviceId}
                          onValueChange={(value) => void handleWorkflowDeviceSelect(value)}
                        >
                          <SelectTrigger className="h-8 text-xs">
                            <SelectValue placeholder="Select workflow device" />
                          </SelectTrigger>
                          <SelectContent>
                            {workflowDevices.slice(0, 50).map((device) => (
                              <SelectItem key={device.id} value={device.id}>
                                {device.name ?? device.id}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    ) : null}
                  </>
                )}
              </div>

              <div className="space-y-2 border-t pt-4">
                <Label className="text-xs text-muted-foreground">Preview output</Label>
                <pre className="max-h-48 overflow-auto rounded-md border bg-muted/30 p-3 font-mono text-[11px] leading-5 whitespace-pre-wrap break-all">
                  {previewOutput || "Run preview to see rendered output."}
                </pre>
              </div>
            </div>
          </div>

          <DialogFooter className="border-t px-6 py-4">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={isBusy}
              onClick={() => void handleValidate()}
            >
              {validateMutation.isPending ? (
                <Loader2 className="mr-2 size-4 animate-spin" />
              ) : (
                <ShieldCheck className="mr-2 size-4" />
              )}
              Validate
            </Button>
            <Button type="button" variant="outline" disabled={isBusy} onClick={() => void handlePreview()}>
              {previewMutation.isPending ? (
                <Loader2 className="mr-2 size-4 animate-spin" />
              ) : (
                <Play className="mr-2 size-4" />
              )}
              Preview
            </Button>
            <Button type="button" onClick={handleSave}>
              Save template
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={nautobotSourceId}
        onClose={() => setSourceOpen(false)}
        onSave={setNautobotSourceId}
      />

      <AttributesDialog
        open={attributesOpen}
        onClose={() => setAttributesOpen(false)}
        value={attributes}
        onChange={setAttributes}
      />
    </>
  );
}
