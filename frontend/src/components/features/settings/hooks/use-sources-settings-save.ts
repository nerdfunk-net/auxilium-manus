"use client";

import { useCallback, useMemo } from "react";

import { useAgentSourcesMutations } from "@/hooks/queries/use-agent-sources-mutations";
import { useBatfishSourcesMutations } from "@/hooks/queries/use-batfish-sources-mutations";
import { useCatalystCenterSourcesMutations } from "@/hooks/queries/use-catalyst-center-sources-mutations";
import { useISESourcesMutations } from "@/hooks/queries/use-ise-sources-mutations";
import { useMattermostSourcesMutations } from "@/hooks/queries/use-mattermost-sources-mutations";
import { usePyATSSourcesMutations } from "@/hooks/queries/use-pyats-sources-mutations";
import { useSettingsMutations } from "@/hooks/queries/use-settings-mutations";

import type {
  AgentSourceCreatePayload,
  AgentSourceUpdatePayload,
  BatfishSourceCreatePayload,
  BatfishSourceUpdatePayload,
  CatalystCenterSourceCreatePayload,
  CatalystCenterSourceUpdatePayload,
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
  | { type: "catalyst_center"; mode: "create" | "edit"; sourceId?: string }
  | { type: "pyats"; mode: "create" | "edit"; sourceId?: string }
  | { type: "mattermost"; mode: "create" | "edit"; sourceId?: string }
  | { type: "batfish"; mode: "create" | "edit"; sourceId?: string }
  | { type: "agent"; mode: "create" | "edit"; sourceId?: string }
  | {
      type: "delete";
      sourceType:
        | "nautobot"
        | "ise"
        | "catalyst_center"
        | "pyats"
        | "mattermost"
        | "batfish"
        | "agent";
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
  // useMutation returns a new result object on every render; only `mutateAsync`
  // is stable, so the callbacks and the returned object depend on those.
  const {
    upsertSetting: { mutateAsync: upsertSettingAsync, isPending: upsertSettingIsPending },
    deleteSetting: { mutateAsync: deleteSettingAsync, isPending: deleteSettingIsPending },
  } = useSettingsMutations();

  const {
    createSource: { mutateAsync: createIseSourceAsync, isPending: createIseSourceIsPending },
    updateSource: { mutateAsync: updateIseSourceAsync, isPending: updateIseSourceIsPending },
    deleteSource: { mutateAsync: deleteIseSourceAsync, isPending: deleteIseSourceIsPending },
  } = useISESourcesMutations();

  const {
    createSource: { mutateAsync: createCatalystCenterSourceAsync, isPending: createCatalystCenterSourceIsPending },
    updateSource: { mutateAsync: updateCatalystCenterSourceAsync, isPending: updateCatalystCenterSourceIsPending },
    deleteSource: { mutateAsync: deleteCatalystCenterSourceAsync, isPending: deleteCatalystCenterSourceIsPending },
  } = useCatalystCenterSourcesMutations();

  const {
    createSource: { mutateAsync: createPyatsSourceAsync, isPending: createPyatsSourceIsPending },
    updateSource: { mutateAsync: updatePyatsSourceAsync, isPending: updatePyatsSourceIsPending },
    deleteSource: { mutateAsync: deletePyatsSourceAsync, isPending: deletePyatsSourceIsPending },
  } = usePyATSSourcesMutations();

  const {
    createSource: { mutateAsync: createMattermostSourceAsync, isPending: createMattermostSourceIsPending },
    updateSource: { mutateAsync: updateMattermostSourceAsync, isPending: updateMattermostSourceIsPending },
    deleteSource: { mutateAsync: deleteMattermostSourceAsync, isPending: deleteMattermostSourceIsPending },
  } = useMattermostSourcesMutations();

  const {
    createSource: { mutateAsync: createBatfishSourceAsync, isPending: createBatfishSourceIsPending },
    updateSource: { mutateAsync: updateBatfishSourceAsync, isPending: updateBatfishSourceIsPending },
    deleteSource: { mutateAsync: deleteBatfishSourceAsync, isPending: deleteBatfishSourceIsPending },
  } = useBatfishSourcesMutations();

  const {
    createSource: { mutateAsync: createAgentSourceAsync, isPending: createAgentSourceIsPending },
    updateSource: { mutateAsync: updateAgentSourceAsync, isPending: updateAgentSourceIsPending },
    deleteSource: { mutateAsync: deleteAgentSourceAsync, isPending: deleteAgentSourceIsPending },
  } = useAgentSourcesMutations();

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
      await upsertSettingAsync({
        key: settingKey,
        value,
        description: `Nautobot source ${values.sourceId}`,
        exists,
      });
      setDialog({ type: "closed" });
    },
    [nautobotById, upsertSettingAsync, setDialog],
  );

  const saveIse = useCallback(
    async (values: ISESourceCreatePayload) => {
      await createIseSourceAsync(values);
      setDialog({ type: "closed" });
    },
    [createIseSourceAsync, setDialog],
  );

  const updateIse = useCallback(
    async (sourceId: string, values: ISESourceUpdatePayload) => {
      await updateIseSourceAsync({ sourceId, data: values });
      setDialog({ type: "closed" });
    },
    [updateIseSourceAsync, setDialog],
  );

  const saveCatalystCenter = useCallback(
    async (values: CatalystCenterSourceCreatePayload) => {
      await createCatalystCenterSourceAsync(values);
      setDialog({ type: "closed" });
    },
    [createCatalystCenterSourceAsync, setDialog],
  );

  const updateCatalystCenter = useCallback(
    async (sourceId: string, values: CatalystCenterSourceUpdatePayload) => {
      await updateCatalystCenterSourceAsync({ sourceId, data: values });
      setDialog({ type: "closed" });
    },
    [updateCatalystCenterSourceAsync, setDialog],
  );

  const savePyats = useCallback(
    async (values: PyATSSourceCreatePayload) => {
      await createPyatsSourceAsync(values);
      setDialog({ type: "closed" });
    },
    [createPyatsSourceAsync, setDialog],
  );

  const updatePyats = useCallback(
    async (sourceId: string, values: PyATSSourceUpdatePayload) => {
      await updatePyatsSourceAsync({ sourceId, data: values });
      setDialog({ type: "closed" });
    },
    [updatePyatsSourceAsync, setDialog],
  );

  const saveMattermost = useCallback(
    async (values: MattermostSourceCreatePayload) => {
      await createMattermostSourceAsync(values);
      setDialog({ type: "closed" });
    },
    [createMattermostSourceAsync, setDialog],
  );

  const updateMattermost = useCallback(
    async (sourceId: string, values: MattermostSourceUpdatePayload) => {
      await updateMattermostSourceAsync({ sourceId, data: values });
      setDialog({ type: "closed" });
    },
    [updateMattermostSourceAsync, setDialog],
  );

  const saveBatfish = useCallback(
    async (values: BatfishSourceCreatePayload) => {
      await createBatfishSourceAsync(values);
      setDialog({ type: "closed" });
    },
    [createBatfishSourceAsync, setDialog],
  );

  const updateBatfish = useCallback(
    async (sourceId: string, values: BatfishSourceUpdatePayload) => {
      await updateBatfishSourceAsync({ sourceId, data: values });
      setDialog({ type: "closed" });
    },
    [updateBatfishSourceAsync, setDialog],
  );

  const saveAgent = useCallback(
    async (values: AgentSourceCreatePayload) => {
      await createAgentSourceAsync(values);
      setDialog({ type: "closed" });
    },
    [createAgentSourceAsync, setDialog],
  );

  const updateAgent = useCallback(
    async (sourceId: string, values: AgentSourceUpdatePayload) => {
      await updateAgentSourceAsync({ sourceId, data: values });
      setDialog({ type: "closed" });
    },
    [updateAgentSourceAsync, setDialog],
  );

  const confirmDelete = useCallback(async () => {
    if (dialog.type !== "delete") {
      return;
    }
    if (dialog.sourceType === "ise") {
      await deleteIseSourceAsync(dialog.sourceId);
    } else if (dialog.sourceType === "catalyst_center") {
      await deleteCatalystCenterSourceAsync(dialog.sourceId);
    } else if (dialog.sourceType === "pyats") {
      await deletePyatsSourceAsync(dialog.sourceId);
    } else if (dialog.sourceType === "mattermost") {
      await deleteMattermostSourceAsync(dialog.sourceId);
    } else if (dialog.sourceType === "batfish") {
      await deleteBatfishSourceAsync(dialog.sourceId);
    } else if (dialog.sourceType === "agent") {
      await deleteAgentSourceAsync(dialog.sourceId);
    } else {
      await deleteSettingAsync(dialog.key);
    }
    setDialog({ type: "closed" });
  }, [
    dialog,
    deleteSettingAsync,
    deleteIseSourceAsync,
    deleteCatalystCenterSourceAsync,
    deletePyatsSourceAsync,
    deleteMattermostSourceAsync,
    deleteBatfishSourceAsync,
    deleteAgentSourceAsync,
    setDialog,
  ]);

  return useMemo(
    () => ({
      saveNautobot,
      saveIse,
      updateIse,
      saveCatalystCenter,
      updateCatalystCenter,
      savePyats,
      updatePyats,
      saveMattermost,
      updateMattermost,
      saveBatfish,
      updateBatfish,
      saveAgent,
      updateAgent,
      confirmDelete,
      upsertSettingIsPending,
      createIseSourceIsPending,
      updateIseSourceIsPending,
      createCatalystCenterSourceIsPending,
      updateCatalystCenterSourceIsPending,
      createPyatsSourceIsPending,
      updatePyatsSourceIsPending,
      createMattermostSourceIsPending,
      updateMattermostSourceIsPending,
      createBatfishSourceIsPending,
      updateBatfishSourceIsPending,
      createAgentSourceIsPending,
      updateAgentSourceIsPending,
      deleteIseSourceIsPending,
      deleteCatalystCenterSourceIsPending,
      deletePyatsSourceIsPending,
      deleteMattermostSourceIsPending,
      deleteBatfishSourceIsPending,
      deleteAgentSourceIsPending,
      deleteSettingIsPending,
    }),
    [
      saveNautobot,
      saveIse,
      updateIse,
      saveCatalystCenter,
      updateCatalystCenter,
      savePyats,
      updatePyats,
      saveMattermost,
      updateMattermost,
      saveBatfish,
      updateBatfish,
      saveAgent,
      updateAgent,
      confirmDelete,
      upsertSettingIsPending,
      createIseSourceIsPending,
      updateIseSourceIsPending,
      createCatalystCenterSourceIsPending,
      updateCatalystCenterSourceIsPending,
      createPyatsSourceIsPending,
      updatePyatsSourceIsPending,
      createMattermostSourceIsPending,
      updateMattermostSourceIsPending,
      createBatfishSourceIsPending,
      updateBatfishSourceIsPending,
      createAgentSourceIsPending,
      updateAgentSourceIsPending,
      deleteIseSourceIsPending,
      deleteCatalystCenterSourceIsPending,
      deletePyatsSourceIsPending,
      deleteMattermostSourceIsPending,
      deleteBatfishSourceIsPending,
      deleteAgentSourceIsPending,
      deleteSettingIsPending,
    ],
  );
}
