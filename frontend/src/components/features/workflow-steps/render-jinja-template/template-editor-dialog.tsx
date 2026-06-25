"use client";

import dynamic from "next/dynamic";
import { GripHorizontal, Loader2, Play, ShieldCheck } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

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
import { cn } from "@/lib/utils";

import {
  buildRenderJinjaTemplateConfig,
  parseRenderJinjaTemplateConfig,
  type RenderJinjaTemplateConfig,
} from "./template-config";
import { constrainFloatingPosition } from "./draggable-panel-position";
import {
  devicePreviewToPayload,
  inventoryOperationsFromNode,
  listInventorySteps,
} from "./workflow-device-samples";
import {
  preventTemplateEditorDismissForSamplePanel,
  SampleContextAttributesDialog,
} from "./sample-context-attributes-dialog";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full min-h-[320px] items-center justify-center rounded-md border bg-muted/30 text-sm text-muted-foreground">
      Loading editor…
    </div>
  ),
});

type ForegroundWindow = "editor" | "attributes";

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
  const [nautobotSampleContext, setNautobotSampleContext] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [previewOutput, setPreviewOutput] = useState("");
  const [sourceOpen, setSourceOpen] = useState(false);
  const [attributeGroupsOpen, setAttributeGroupsOpen] = useState(false);
  const [showAttributesOpen, setShowAttributesOpen] = useState(false);
  const [foregroundWindow, setForegroundWindow] = useState<ForegroundWindow>("editor");
  const [editorPosition, setEditorPosition] = useState<{ x: number; y: number } | null>(null);
  const [isEditorDragging, setIsEditorDragging] = useState(false);
  const editorDialogRef = useRef<HTMLDivElement>(null);
  const editorDragOffsetRef = useRef({ x: 0, y: 0 });
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
      setNautobotSampleContext(context);
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

  const bringAttributesToFront = useCallback(() => {
    setForegroundWindow("attributes");
  }, []);

  const closeEditor = useCallback(() => {
    setShowAttributesOpen(false);
    setEditorPosition(null);
    setIsEditorDragging(false);
    setForegroundWindow("editor");
    onClose();
  }, [onClose]);

  const handleSave = useCallback(() => {
    onSave(
      buildRenderJinjaTemplateConfig(config, {
        template,
        editor_nautobot_source_id: nautobotSourceId,
        editor_sample_device_name: deviceName,
        editor_list_of_attributes: attributes,
      }),
    );
    closeEditor();
  }, [attributes, closeEditor, config, deviceName, nautobotSourceId, onSave, template]);

  const workflowDevices = inventoryPreviewMutation.data?.devices ?? [];
  const isBusy =
    validateMutation.isPending ||
    previewMutation.isPending ||
    nautobotSampleMutation.isPending ||
    deviceSampleMutation.isPending ||
    inventoryPreviewMutation.isPending;

  const handleDialogPointerDownOutside = useCallback(
    (event: { target: EventTarget | null; preventDefault: () => void; detail?: { originalEvent?: Event } }) => {
      preventTemplateEditorDismissForSamplePanel(event);
    },
    [],
  );

  const handleDialogFocusOutside = useCallback(
    (event: { target: EventTarget | null; preventDefault: () => void; detail?: { originalEvent?: Event } }) => {
      preventTemplateEditorDismissForSamplePanel(event);
    },
    [],
  );

  const bringEditorToFront = useCallback(() => {
    setForegroundWindow("editor");
  }, []);

  const handleEditorDragPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      bringEditorToFront();
      const dialog = editorDialogRef.current;
      if (!dialog) {
        return;
      }
      const rect = dialog.getBoundingClientRect();
      const startPosition = editorPosition ?? { x: rect.left, y: rect.top };
      if (!editorPosition) {
        setEditorPosition(startPosition);
      }
      editorDragOffsetRef.current = {
        x: event.clientX - startPosition.x,
        y: event.clientY - startPosition.y,
      };
      setIsEditorDragging(true);
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    [editorPosition, bringEditorToFront],
  );

  const handleEditorDragPointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!isEditorDragging) {
        return;
      }
      event.preventDefault();
      const dialog = editorDialogRef.current;
      const width = dialog?.offsetWidth ?? 960;
      const height = dialog?.offsetHeight ?? 640;
      setEditorPosition(
        constrainFloatingPosition(
          {
            x: event.clientX - editorDragOffsetRef.current.x,
            y: event.clientY - editorDragOffsetRef.current.y,
          },
          width,
          height,
        ),
      );
    },
    [isEditorDragging],
  );

  const handleEditorDragPointerUp = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!isEditorDragging) {
      return;
    }
    setIsEditorDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, [isEditorDragging]);

  const mounted = typeof window !== "undefined";

  return (
    <>
      {mounted && open
        ? createPortal(
            <div
              aria-hidden
              className="fixed inset-0 z-[80] bg-black/50 transition-opacity duration-200"
            />,
            document.body,
          )
        : null}

      <Dialog
        open={open}
        modal={!showAttributesOpen}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            closeEditor();
          }
        }}
      >
        <DialogContent
          ref={editorDialogRef}
          showOverlay={false}
          style={
            editorPosition
              ? { left: editorPosition.x, top: editorPosition.y }
              : undefined
          }
          className={cn(
            "flex max-h-[90vh] w-[min(96vw,72rem)] max-w-none flex-col gap-0 overflow-hidden border p-0 shadow-lg transition-[box-shadow,border-color] duration-200 [&>button]:z-30",
            foregroundWindow === "editor" ? "z-[110]" : "z-[90]",
            editorPosition
              ? "translate-x-0 translate-y-0"
              : "left-[50%] top-[50%] translate-x-[-50%] translate-y-[-50%]",
            showAttributesOpen && "border-border/60",
            isEditorDragging && "select-none",
          )}
          onPointerDownCapture={bringEditorToFront}
          onPointerDownOutside={handleDialogPointerDownOutside}
          onFocusOutside={handleDialogFocusOutside}
        >
          <DialogHeader className="border-b px-6 py-4 pr-14">
            <div
              className={cn(
                "flex cursor-grab items-center gap-2 active:cursor-grabbing",
                isEditorDragging && "cursor-grabbing",
              )}
              onPointerDown={handleEditorDragPointerDown}
              onPointerMove={handleEditorDragPointerMove}
              onPointerUp={handleEditorDragPointerUp}
              onPointerCancel={handleEditorDragPointerUp}
            >
              <GripHorizontal className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <DialogTitle className="flex-1">Template editor</DialogTitle>
            </div>
          </DialogHeader>

          <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 lg:grid-cols-[minmax(0,1.4fr)_minmax(18rem,0.8fr)]">
            <div className="min-h-[360px] border-b p-4 lg:border-b-0 lg:border-r">
              <MonacoEditor
                height="min(52vh, 560px)"
                defaultLanguage="jinja"
                theme="vs-dark"
                value={template}
                onChange={(value) => setTemplate(value ?? "")}
                onMount={(editor) => {
                  editor.onDidFocusEditorWidget(() => {
                    bringEditorToFront();
                  });
                }}
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
                  <Label className="text-xs text-muted-foreground">Attribute groups</Label>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 w-full text-xs"
                    onClick={() => setAttributeGroupsOpen(true)}
                  >
                    {attributes.length} group{attributes.length === 1 ? "" : "s"} selected
                  </Button>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    className="h-7 shrink-0 px-3 text-xs"
                    disabled={isBusy}
                    onClick={() => void handleLoadNautobotSample()}
                  >
                    {nautobotSampleMutation.isPending ? (
                      <Loader2 className="mr-1.5 size-3.5 animate-spin" />
                    ) : null}
                    Load from Nautobot
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 flex-1 text-xs"
                    disabled={!nautobotSampleContext}
                    onClick={() => {
                      setShowAttributesOpen(true);
                      bringAttributesToFront();
                    }}
                  >
                    Show Attributes
                  </Button>
                </div>
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
            <Button type="button" variant="outline" onClick={closeEditor}>
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
        open={attributeGroupsOpen}
        onClose={() => setAttributeGroupsOpen(false)}
        value={attributes}
        onChange={setAttributes}
      />

      {open && nautobotSampleContext ? (
        <SampleContextAttributesDialog
          open={showAttributesOpen}
          context={nautobotSampleContext}
          deviceName={deviceName.trim() || undefined}
          isForeground={foregroundWindow === "attributes"}
          onFocus={bringAttributesToFront}
          onClose={() => setShowAttributesOpen(false)}
        />
      ) : null}
    </>
  );
}
