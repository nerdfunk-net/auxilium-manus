import { useCallback, useMemo, useState } from "react";

import type { DeviceInfo } from "../types/device-selector";

export function useSelectedInventory() {
  const [selectedDevicesMap, setSelectedDevicesMap] = useState<Map<string, DeviceInfo>>(
    () => new Map(),
  );
  const [removalSelectedIds, setRemovalSelectedIds] = useState<Set<string>>(() => new Set());

  const addDevices = useCallback((devices: DeviceInfo[]) => {
    setSelectedDevicesMap((prev) => {
      const next = new Map(prev);
      devices.forEach((device) => next.set(device.id, device));
      return next;
    });
  }, []);

  const removeDevice = useCallback((id: string) => {
    setSelectedDevicesMap((prev) => {
      const next = new Map(prev);
      next.delete(id);
      return next;
    });
    setRemovalSelectedIds((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }, []);

  const removeDevices = useCallback((ids: string[]) => {
    setSelectedDevicesMap((prev) => {
      const next = new Map(prev);
      ids.forEach((id) => next.delete(id));
      return next;
    });
    setRemovalSelectedIds((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.delete(id));
      return next;
    });
  }, []);

  const replaceAll = useCallback((devices: DeviceInfo[]) => {
    setSelectedDevicesMap(new Map(devices.map((device) => [device.id, device])));
    setRemovalSelectedIds(new Set());
  }, []);

  const clear = useCallback(() => {
    setSelectedDevicesMap(new Map());
    setRemovalSelectedIds(new Set());
  }, []);

  const toggleRemovalSelect = useCallback((id: string, checked: boolean) => {
    setRemovalSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(id);
      } else {
        next.delete(id);
      }
      return next;
    });
  }, []);

  const selectAllForRemoval = useCallback(
    (checked: boolean) => {
      setRemovalSelectedIds(checked ? new Set(selectedDevicesMap.keys()) : new Set());
    },
    [selectedDevicesMap],
  );

  const removeSelectedDevices = useCallback(() => {
    removeDevices(Array.from(removalSelectedIds));
  }, [removalSelectedIds, removeDevices]);

  const selectedDevices = useMemo(
    () => Array.from(selectedDevicesMap.values()),
    [selectedDevicesMap],
  );

  return useMemo(
    () => ({
      selectedDevices,
      selectedCount: selectedDevicesMap.size,
      removalSelectedIds,
      addDevices,
      removeDevice,
      removeDevices,
      removeSelectedDevices,
      replaceAll,
      clear,
      toggleRemovalSelect,
      selectAllForRemoval,
    }),
    [
      selectedDevices,
      selectedDevicesMap.size,
      removalSelectedIds,
      addDevices,
      removeDevice,
      removeDevices,
      removeSelectedDevices,
      replaceAll,
      clear,
      toggleRemovalSelect,
      selectAllForRemoval,
    ],
  );
}
