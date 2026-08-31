"use client";

import { useMemo, useState } from "react";

import { useISESourcesQuery } from "@/hooks/queries/use-ise-sources-query";
import { useMattermostSourcesQuery } from "@/hooks/queries/use-mattermost-sources-query";
import { usePyATSSourcesQuery } from "@/hooks/queries/use-pyats-sources-query";
import { useSettingsListQuery } from "@/hooks/queries/use-settings-query";

import { SOURCES_KEY_PREFIX } from "../constants/setting-keys";
import type { NautobotSourceConfig } from "../types/settings-api";
import {
  collectExistingSourceIds,
  groupSourceSettings,
} from "../utils/parse-source-settings";
import {
  useSourcesSettingsSave,
  type SourcesDialogState,
} from "./use-sources-settings-save";

export type { SourcesDialogState };

export function useSourcesSettings() {
  const [dialog, setDialog] = useState<SourcesDialogState>({ type: "closed" });
  const { data, isLoading } = useSettingsListQuery({
    keyPrefix: SOURCES_KEY_PREFIX,
  });

  const { data: iseData, isLoading: isIseLoading } = useISESourcesQuery();
  const ise = useMemo(() => iseData?.sources ?? [], [iseData]);
  const iseById = useMemo(
    () => new Map(ise.map((item) => [item.source_id, item])),
    [ise],
  );
  const existingIseIds = useMemo(() => ise.map((item) => item.source_id), [ise]);

  const { data: pyatsData, isLoading: isPyatsLoading } = usePyATSSourcesQuery();
  const pyats = useMemo(() => pyatsData?.sources ?? [], [pyatsData]);
  const pyatsById = useMemo(
    () => new Map(pyats.map((item) => [item.source_id, item])),
    [pyats],
  );
  const existingPyatsIds = useMemo(
    () => pyats.map((item) => item.source_id),
    [pyats],
  );

  const { data: mattermostData, isLoading: isMattermostLoading } =
    useMattermostSourcesQuery();
  const mattermost = useMemo(
    () => mattermostData?.sources ?? [],
    [mattermostData],
  );
  const mattermostById = useMemo(
    () => new Map(mattermost.map((item) => [item.source_id, item])),
    [mattermost],
  );
  const existingMattermostIds = useMemo(
    () => mattermost.map((item) => item.source_id),
    [mattermost],
  );

  const { nautobot } = useMemo(
    () => groupSourceSettings(data?.settings ?? []),
    [data?.settings],
  );

  const nautobotById = useMemo(
    () => new Map(nautobot.map((item) => [item.sourceId, item])),
    [nautobot],
  );

  const existingNautobotIds = useMemo(
    () => collectExistingSourceIds(data?.settings ?? [], "nautobot"),
    [data?.settings],
  );

  const saveHandlers = useSourcesSettingsSave({
    dialog,
    setDialog,
    nautobotById,
  });

  const nautobotDialogOpen = dialog.type === "nautobot" ? dialog : null;
  const iseDialogOpen = dialog.type === "ise" ? dialog : null;
  const pyatsDialogOpen = dialog.type === "pyats" ? dialog : null;
  const mattermostDialogOpen = dialog.type === "mattermost" ? dialog : null;
  const deleteDialogOpen = dialog.type === "delete" ? dialog : null;

  const editingNautobot: NautobotSourceConfig | null =
    nautobotDialogOpen?.mode === "edit" && nautobotDialogOpen.sourceId
      ? (nautobotById.get(nautobotDialogOpen.sourceId) ?? null)
      : null;
  const editingIseValue = useMemo(() => {
    if (iseDialogOpen?.mode !== "edit" || !iseDialogOpen.sourceId) {
      return null;
    }
    const editingIse = iseById.get(iseDialogOpen.sourceId) ?? null;
    if (!editingIse) {
      return null;
    }
    return {
      sourceId: editingIse.source_id,
      url: editingIse.url,
      verifySsl: editingIse.verify_ssl,
      timeout: editingIse.timeout,
      credentialId: editingIse.credential_id,
    };
  }, [iseDialogOpen, iseById]);
  const editingPyatsValue = useMemo(() => {
    if (pyatsDialogOpen?.mode !== "edit" || !pyatsDialogOpen.sourceId) {
      return null;
    }
    const editingPyats = pyatsById.get(pyatsDialogOpen.sourceId) ?? null;
    if (!editingPyats) {
      return null;
    }
    return {
      sourceId: editingPyats.source_id,
      url: editingPyats.url,
      verifySsl: editingPyats.verify_ssl,
      timeout: editingPyats.timeout,
      credentialId: editingPyats.credential_id,
    };
  }, [pyatsDialogOpen, pyatsById]);
  const editingMattermostValue = useMemo(() => {
    if (mattermostDialogOpen?.mode !== "edit" || !mattermostDialogOpen.sourceId) {
      return null;
    }
    const editingMattermost = mattermostById.get(mattermostDialogOpen.sourceId) ?? null;
    if (!editingMattermost) {
      return null;
    }
    return {
      sourceId: editingMattermost.source_id,
      url: editingMattermost.url,
      verifySsl: editingMattermost.verify_ssl,
      timeout: editingMattermost.timeout,
      credentialId: editingMattermost.credential_id,
    };
  }, [mattermostDialogOpen, mattermostById]);

  const isDeletePending =
    deleteDialogOpen?.sourceType === "ise"
      ? saveHandlers.deleteIseSourceIsPending
      : deleteDialogOpen?.sourceType === "pyats"
        ? saveHandlers.deletePyatsSourceIsPending
        : deleteDialogOpen?.sourceType === "mattermost"
          ? saveHandlers.deleteMattermostSourceIsPending
          : saveHandlers.deleteSettingIsPending;

  return useMemo(
    () => ({
      dialog,
      setDialog,
      isLoading,
      nautobot,
      ise,
      pyats,
      mattermost,
      isIseLoading,
      isPyatsLoading,
      isMattermostLoading,
      existingNautobotIds,
      existingIseIds,
      existingPyatsIds,
      existingMattermostIds,
      saveNautobot: saveHandlers.saveNautobot,
      saveIse: saveHandlers.saveIse,
      updateIse: saveHandlers.updateIse,
      savePyats: saveHandlers.savePyats,
      updatePyats: saveHandlers.updatePyats,
      saveMattermost: saveHandlers.saveMattermost,
      updateMattermost: saveHandlers.updateMattermost,
      confirmDelete: saveHandlers.confirmDelete,
      nautobotDialogOpen,
      iseDialogOpen,
      pyatsDialogOpen,
      mattermostDialogOpen,
      deleteDialogOpen,
      editingNautobot,
      editingIseValue,
      editingPyatsValue,
      editingMattermostValue,
      isDeletePending,
      upsertSettingIsPending: saveHandlers.upsertSettingIsPending,
      createIseSourceIsPending: saveHandlers.createIseSourceIsPending,
      updateIseSourceIsPending: saveHandlers.updateIseSourceIsPending,
      createPyatsSourceIsPending: saveHandlers.createPyatsSourceIsPending,
      updatePyatsSourceIsPending: saveHandlers.updatePyatsSourceIsPending,
      createMattermostSourceIsPending: saveHandlers.createMattermostSourceIsPending,
      updateMattermostSourceIsPending: saveHandlers.updateMattermostSourceIsPending,
    }),
    [
      dialog,
      isLoading,
      nautobot,
      ise,
      pyats,
      mattermost,
      isIseLoading,
      isPyatsLoading,
      isMattermostLoading,
      existingNautobotIds,
      existingIseIds,
      existingPyatsIds,
      existingMattermostIds,
      saveHandlers,
      nautobotDialogOpen,
      iseDialogOpen,
      pyatsDialogOpen,
      mattermostDialogOpen,
      deleteDialogOpen,
      editingNautobot,
      editingIseValue,
      editingPyatsValue,
      editingMattermostValue,
      isDeletePending,
    ],
  );
}
