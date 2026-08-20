"use client";

import { useCallback, useMemo, useState } from "react";

import { useToast } from "@/hooks/use-toast";

import type { useSavedInventories } from "./use-saved-inventories";

interface UseDeviceSelectorModalsOptions {
  saved: ReturnType<typeof useSavedInventories>;
  conditionTreeItemCount: number;
  selectedDeviceCount: number;
}

export function useDeviceSelectorModals({
  saved,
  conditionTreeItemCount,
  selectedDeviceCount,
}: UseDeviceSelectorModalsOptions) {
  const { toast } = useToast();

  const [showSaveModal, setShowSaveModal] = useState(false);
  const [showSaveDeviceListModal, setShowSaveDeviceListModal] = useState(false);
  const [showLoadModal, setShowLoadModal] = useState(false);
  const [showManageModal, setShowManageModal] = useState(false);
  const [showLogicalTreeModal, setShowLogicalTreeModal] = useState(false);
  const [showHelpModal, setShowHelpModal] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);

  const handleOpenSaveModal = useCallback(async () => {
    if (conditionTreeItemCount === 0) {
      toast({
        title: "Nothing to save",
        description: "Please add at least one condition before saving.",
        variant: "destructive",
      });
      return;
    }
    await saved.loadSavedInventories();
    setShowSaveModal(true);
  }, [conditionTreeItemCount, saved, toast]);

  const handleOpenLoadModal = useCallback(async () => {
    await saved.loadSavedInventories();
    setShowLoadModal(true);
  }, [saved]);

  const handleOpenManageModal = useCallback(async () => {
    await saved.loadSavedInventories();
    setShowManageModal(true);
  }, [saved]);

  const handleOpenSaveDeviceListModal = useCallback(async () => {
    if (selectedDeviceCount === 0) {
      toast({
        title: "Nothing to save",
        description: "Add at least one device to the selection before saving.",
        variant: "destructive",
      });
      return;
    }
    await saved.loadSavedInventories();
    setShowSaveDeviceListModal(true);
  }, [selectedDeviceCount, saved, toast]);

  const openHelpModal = useCallback(() => setShowHelpModal(true), []);
  const closeHelpModal = useCallback(() => setShowHelpModal(false), []);
  const openLogicalTreeModal = useCallback(() => setShowLogicalTreeModal(true), []);
  const closeLogicalTreeModal = useCallback(() => setShowLogicalTreeModal(false), []);
  const closeSaveModal = useCallback(() => setShowSaveModal(false), []);
  const closeSaveDeviceListModal = useCallback(() => setShowSaveDeviceListModal(false), []);
  const closeLoadModal = useCallback(() => setShowLoadModal(false), []);
  const closeManageModal = useCallback(() => setShowManageModal(false), []);
  const toggleSelectionMode = useCallback(() => setSelectionMode((v) => !v), []);

  return useMemo(
    () => ({
      showSaveModal,
      showSaveDeviceListModal,
      showLoadModal,
      showManageModal,
      showLogicalTreeModal,
      showHelpModal,
      selectionMode,
      setSelectionMode,
      handleOpenSaveModal,
      handleOpenLoadModal,
      handleOpenManageModal,
      handleOpenSaveDeviceListModal,
      openHelpModal,
      closeHelpModal,
      openLogicalTreeModal,
      closeLogicalTreeModal,
      closeSaveModal,
      closeSaveDeviceListModal,
      closeLoadModal,
      closeManageModal,
      toggleSelectionMode,
    }),
    [
      showSaveModal,
      showSaveDeviceListModal,
      showLoadModal,
      showManageModal,
      showLogicalTreeModal,
      showHelpModal,
      selectionMode,
      handleOpenSaveModal,
      handleOpenLoadModal,
      handleOpenManageModal,
      handleOpenSaveDeviceListModal,
      openHelpModal,
      closeHelpModal,
      openLogicalTreeModal,
      closeLogicalTreeModal,
      closeSaveModal,
      closeSaveDeviceListModal,
      closeLoadModal,
      closeManageModal,
      toggleSelectionMode,
    ],
  );
}
