"use client";

import { useCallback } from "react";

import { useISESourcesMutations } from "@/hooks/queries/use-ise-sources-mutations";
import { useMattermostSourcesMutations } from "@/hooks/queries/use-mattermost-sources-mutations";
import { usePyATSSourcesMutations } from "@/hooks/queries/use-pyats-sources-mutations";
import { useSettingsMutations } from "@/hooks/queries/use-settings-mutations";

import type {
  ISESourceCreatePayload,
  ISESourceUpdatePayload,
  MattermostSourceCreatePayload,
  MattermostSourceUpdatePayload,
  NautobotSourceValue,
  PyATSSourceCreatePayload,
  PyATSSourceUpdatePayload,
} from "../types/settings-api";
export type SourcesDialogState =
  | { type: "closed" }
  | { type: "nautobot"; mode: "create" | "edit"; sourceId?: string }
  | { type: "ise"; mode: "create" | "edit"; sourceId?: string }
  | { type: "pyats"; mode: "create" | "edit"; sourceId?: string }
  | { type: "mattermost"; mode: "create" | "edit"; sourceId?: string }
  | {
      type: "delete";
      sourceType: "nautobot" | "ise" | "pyats" | "mattermost";
      sourceId: string;
      key: string;
    };

interface UseSourcesSettingsSaveOptions {
  dialog: SourcesDialogState;
  setDialog: (state: SourcesDialogState) => void;
  nautobotById: Map<string, unknown>;
}

export function useSourcesSettingsSave({
  dialog,
  setDialog,
  nautobotById,
}: UseSourcesSettingsSaveOptions) {
  const { upsertSetting, deleteSetting } = useSettingsMutations();

  const {
    createSource: createIseSource,
    updateSource: updateIseSource,
    deleteSource: deleteIseSource,
  } = useISESourcesMutations();

  const {
    createSource: createPyatsSource,
    updateSource: updatePyatsSource,
    deleteSource: deletePyatsSource,
  } = usePyATSSourcesMutations();

  const {
    createSource: createMattermostSource,
    updateSource: updateMattermostSource,
    deleteSource: deleteMattermostSource,
  } = useMattermostSourcesMutations();

  const saveNautobot = useCallback(
    async (values: NautobotSourceValue, settingKey: string) => {
      const exists = nautobotById.has(values.sourceId);
      const value: Record<string, unknown> = {
        url: values.url,
        verify_ssl: values.verifySsl,
      };
      if (values.credentialId != null) {
        value.credential_id = values.credentialId;
      }
      await upsertSetting.mutateAsync({
        key: settingKey,
        value,
        description: `Nautobot source ${values.sourceId}`,
        exists,
      });
      setDialog({ type: "closed" });
    },
    [nautobotById, upsertSetting, setDialog],
  );

  const saveIse = useCallback(
    async (values: ISESourceCreatePayload) => {
      await createIseSource.mutateAsync(values);
      setDialog({ type: "closed" });
    },
    [createIseSource, setDialog],
  );

  const updateIse = useCallback(
    async (sourceId: string, values: ISESourceUpdatePayload) => {
      await updateIseSource.mutateAsync({ sourceId, data: values });
      setDialog({ type: "closed" });
    },
    [updateIseSource, setDialog],
  );

  const savePyats = useCallback(
    async (values: PyATSSourceCreatePayload) => {
      await createPyatsSource.mutateAsync(values);
      setDialog({ type: "closed" });
    },
    [createPyatsSource, setDialog],
  );

  const updatePyats = useCallback(
    async (sourceId: string, values: PyATSSourceUpdatePayload) => {
      await updatePyatsSource.mutateAsync({ sourceId, data: values });
      setDialog({ type: "closed" });
    },
    [updatePyatsSource, setDialog],
  );

  const saveMattermost = useCallback(
    async (values: MattermostSourceCreatePayload) => {
      await createMattermostSource.mutateAsync(values);
      setDialog({ type: "closed" });
    },
    [createMattermostSource, setDialog],
  );

  const updateMattermost = useCallback(
    async (sourceId: string, values: MattermostSourceUpdatePayload) => {
      await updateMattermostSource.mutateAsync({ sourceId, data: values });
      setDialog({ type: "closed" });
    },
    [updateMattermostSource, setDialog],
  );

  const confirmDelete = useCallback(async () => {
    if (dialog.type !== "delete") {
      return;
    }
    if (dialog.sourceType === "ise") {
      await deleteIseSource.mutateAsync(dialog.sourceId);
    } else if (dialog.sourceType === "pyats") {
      await deletePyatsSource.mutateAsync(dialog.sourceId);
    } else if (dialog.sourceType === "mattermost") {
      await deleteMattermostSource.mutateAsync(dialog.sourceId);
    } else {
      await deleteSetting.mutateAsync(dialog.key);
    }
    setDialog({ type: "closed" });
  }, [dialog, deleteSetting, deleteIseSource, deletePyatsSource, deleteMattermostSource, setDialog]);

  return {
    saveNautobot,
    saveIse,
    updateIse,
    savePyats,
    updatePyats,
    saveMattermost,
    updateMattermost,
    confirmDelete,
    upsertSettingIsPending: upsertSetting.isPending,
    createIseSourceIsPending: createIseSource.isPending,
    updateIseSourceIsPending: updateIseSource.isPending,
    createPyatsSourceIsPending: createPyatsSource.isPending,
    updatePyatsSourceIsPending: updatePyatsSource.isPending,
    createMattermostSourceIsPending: createMattermostSource.isPending,
    updateMattermostSourceIsPending: updateMattermostSource.isPending,
    deleteIseSourceIsPending: deleteIseSource.isPending,
    deletePyatsSourceIsPending: deletePyatsSource.isPending,
    deleteMattermostSourceIsPending: deleteMattermostSource.isPending,
    deleteSettingIsPending: deleteSetting.isPending,
  };
}
