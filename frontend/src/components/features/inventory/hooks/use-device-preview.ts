import { useState, useEffect, useMemo, useCallback, useRef } from "react";

import { useGetNautobotDevicesPreviewMutation } from "@/hooks/queries/use-get-nautobot-devices-preview-mutation";
import { useToast } from "@/hooks/use-toast";

import type {
  ConditionGroup,
  ConditionItem,
  ConditionTree,
  DeviceInfo,
  LogicalCondition,
} from "../types/device-selector";
import { buildOperationsFromTree } from "../utils/tree-to-operations";

const EMPTY_DEVICES: DeviceInfo[] = [];
const EMPTY_DEVICE_IDS: string[] = [];

interface UseDevicePreviewOptions {
  nautobot_url: string;
  nautobot_token: string;
  sourceReady: boolean;
}

function mapPreviewDevices(
  devices: Array<{
    id: string;
    name: string | null;
    serial: string | null;
    location: string | null;
    role: string | null;
    tags: string[];
    device_type: string | null;
    manufacturer: string | null;
    platform: string | null;
    primary_ip4: string | null;
    status: string | null;
  }>,
): DeviceInfo[] {
  return devices.map((device) => ({
    id: device.id,
    name: device.name,
    serial: device.serial,
    location: device.location ?? undefined,
    role: device.role ?? undefined,
    device_type: device.device_type ?? undefined,
    manufacturer: device.manufacturer ?? undefined,
    platform: device.platform ?? undefined,
    primary_ip4: device.primary_ip4 ?? undefined,
    status: device.status ?? undefined,
    tags: device.tags ?? [],
  }));
}

export function useDevicePreview(
  conditionTree: ConditionTree,
  options: UseDevicePreviewOptions,
  initialDevices: DeviceInfo[] = EMPTY_DEVICES,
  selectedDeviceIds: string[] = EMPTY_DEVICE_IDS,
  onDevicesSelected?: (devices: DeviceInfo[], conditions: LogicalCondition[]) => void,
  onSelectionChange?: (selectedIds: string[], selectedDevices: DeviceInfo[]) => void,
) {
  const { nautobot_url, nautobot_token, sourceReady } = options;
  const previewMutation = useGetNautobotDevicesPreviewMutation();
  const { toast } = useToast();

  const previewDevices = useMemo(() => {
    if (!previewMutation.data?.devices) {
      return initialDevices;
    }
    return mapPreviewDevices(previewMutation.data.devices);
  }, [previewMutation.data, initialDevices]);

  const totalDevices = previewMutation.data?.total ?? initialDevices.length;
  const operationsExecuted = previewMutation.data?.operations_executed ?? 0;
  const isLoadingPreview = previewMutation.isPending;

  const [previewHidden, setPreviewHidden] = useState(false);
  const showPreviewResults = useMemo(() => {
    if (previewHidden) {
      return false;
    }
    return Boolean(previewMutation.data) || initialDevices.length > 0;
  }, [previewHidden, previewMutation.data, initialDevices.length]);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(selectedDeviceIds),
  );
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const onDevicesSelectedRef = useRef(onDevicesSelected);
  const onSelectionChangeRef = useRef(onSelectionChange);

  useEffect(() => {
    onDevicesSelectedRef.current = onDevicesSelected;
    onSelectionChangeRef.current = onSelectionChange;
  });

  const treeToFlatConditions = useCallback((tree: ConditionTree): LogicalCondition[] => {
    const flatConditions: LogicalCondition[] = [];

    const flatten = (
      items: (ConditionItem | ConditionGroup)[],
      logic: string = "AND",
    ) => {
      items.forEach((item, index) => {
        if ("type" in item && item.type === "group") {
          flatten(item.items, item.internalLogic);
        } else {
          const cond = item as ConditionItem;
          flatConditions.push({
            field: cond.field,
            operator: cond.operator,
            value: cond.value,
            logic: index === 0 ? "AND" : logic,
          });
        }
      });
    };

    flatten(tree.items, tree.internalLogic);
    return flatConditions;
  }, []);

  useEffect(() => {
    if (previewMutation.error) {
      toast({
        title: "Preview failed",
        description: previewMutation.error.message,
        variant: "destructive",
      });
    }
  }, [previewMutation.error, toast]);

  const loadPreview = useCallback(() => {
    if (!sourceReady) {
      toast({
        title: "Nautobot source required",
        description: "Configure a Nautobot source in Settings to preview devices.",
        variant: "destructive",
      });
      return;
    }

    if (conditionTree.items.length === 0) {
      toast({
        title: "No conditions",
        description: "Please add at least one condition.",
        variant: "destructive",
      });
      return;
    }

    const operations = buildOperationsFromTree(conditionTree);
    previewMutation.mutate(
      { nautobot_url, nautobot_token, operations },
      {
        onSuccess: (data) => {
          setPreviewHidden(false);
          setCurrentPage(1);
          const devices = mapPreviewDevices(data.devices);
          onDevicesSelectedRef.current?.(
            devices,
            treeToFlatConditions(conditionTree),
          );
        },
      },
    );
  }, [
    sourceReady,
    conditionTree,
    previewMutation,
    nautobot_url,
    nautobot_token,
    toast,
    treeToFlatConditions,
  ]);

  const handleSelectAll = useCallback(
    (checked: boolean) => {
      if (checked) {
        const allIds = new Set(previewDevices.map((d) => d.id));
        setSelectedIds(allIds);
        onSelectionChangeRef.current?.(Array.from(allIds), previewDevices);
      } else {
        setSelectedIds(new Set());
        onSelectionChangeRef.current?.([], []);
      }
    },
    [previewDevices],
  );

  const handleSelectDevice = useCallback(
    (deviceId: string, checked: boolean) => {
      const newSelectedIds = new Set(selectedIds);
      if (checked) {
        newSelectedIds.add(deviceId);
      } else {
        newSelectedIds.delete(deviceId);
      }
      setSelectedIds(newSelectedIds);

      if (onSelectionChangeRef.current) {
        const selectedDevices = previewDevices.filter((d) => newSelectedIds.has(d.id));
        onSelectionChangeRef.current(Array.from(newSelectedIds), selectedDevices);
      }
    },
    [selectedIds, previewDevices],
  );

  const totalPages = Math.ceil(previewDevices.length / pageSize);
  const startIndex = (currentPage - 1) * pageSize;
  const currentPageDevices = previewDevices.slice(startIndex, startIndex + pageSize);

  const handlePageChange = useCallback((page: number) => {
    setCurrentPage(page);
  }, []);

  const setShowPreviewResults = useCallback((show: boolean) => {
    setPreviewHidden(!show);
  }, []);

  return useMemo(
    () => ({
      previewDevices,
      totalDevices,
      operationsExecuted,
      showPreviewResults,
      setShowPreviewResults,
      isLoadingPreview,
      currentPage,
      setCurrentPage,
      pageSize,
      setPageSize,
      selectedIds,
      setSelectedIds,
      currentPageDevices,
      totalPages,
      handlePageChange,
      handleSelectAll,
      handleSelectDevice,
      loadPreview,
      treeToFlatConditions,
    }),
    [
      previewDevices,
      totalDevices,
      operationsExecuted,
      showPreviewResults,
      setShowPreviewResults,
      isLoadingPreview,
      currentPage,
      pageSize,
      selectedIds,
      currentPageDevices,
      totalPages,
      handlePageChange,
      handleSelectAll,
      handleSelectDevice,
      loadPreview,
      treeToFlatConditions,
    ],
  );
}
