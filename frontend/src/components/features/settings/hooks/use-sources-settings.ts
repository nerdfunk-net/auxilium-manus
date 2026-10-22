"use client";

import { useMemo, useState } from "react";

import { useAgentSourcesQuery } from "@/hooks/queries/use-agent-sources-query";
import { useBatfishSourcesQuery } from "@/hooks/queries/use-batfish-sources-query";
import { useCatalystCenterSourcesQuery } from "@/hooks/queries/use-catalyst-center-sources-query";
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

  const { data: catalystCenterData, isLoading: isCatalystCenterLoading } =
    useCatalystCenterSourcesQuery();
  const catalystCenter = useMemo(
    () => catalystCenterData?.sources ?? [],
    [catalystCenterData],
  );
  const catalystCenterById = useMemo(
    () => new Map(catalystCenter.map((item) => [item.source_id, item])),
    [catalystCenter],
  );
  const existingCatalystCenterIds = useMemo(
    () => catalystCenter.map((item) => item.source_id),
    [catalystCenter],
  );

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

  const { data: batfishData, isLoading: isBatfishLoading } =
    useBatfishSourcesQuery();
  const batfish = useMemo(() => batfishData?.sources ?? [], [batfishData]);
  const batfishById = useMemo(
    () => new Map(batfish.map((item) => [item.source_id, item])),
    [batfish],
  );
  const existingBatfishIds = useMemo(
    () => batfish.map((item) => item.source_id),
    [batfish],
  );

  const { data: agentData, isLoading: isAgentLoading } = useAgentSourcesQuery();
  const agent = useMemo(() => agentData?.sources ?? [], [agentData]);
  const agentById = useMemo(
    () => new Map(agent.map((item) => [item.source_id, item])),
    [agent],
  );
  const existingAgentIds = useMemo(
    () => agent.map((item) => item.source_id),
    [agent],
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
  const catalystCenterDialogOpen =
    dialog.type === "catalyst_center" ? dialog : null;
  const pyatsDialogOpen = dialog.type === "pyats" ? dialog : null;
  const mattermostDialogOpen = dialog.type === "mattermost" ? dialog : null;
  const batfishDialogOpen = dialog.type === "batfish" ? dialog : null;
  const agentDialogOpen = dialog.type === "agent" ? dialog : null;
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
  const editingCatalystCenterValue = useMemo(() => {
    if (
      catalystCenterDialogOpen?.mode !== "edit" ||
      !catalystCenterDialogOpen.sourceId
    ) {
      return null;
    }
    const editing =
      catalystCenterById.get(catalystCenterDialogOpen.sourceId) ?? null;
    if (!editing) {
      return null;
    }
    return {
      sourceId: editing.source_id,
      url: editing.url,
      verifySsl: editing.verify_ssl,
      timeout: editing.timeout,
      credentialId: editing.credential_id,
    };
  }, [catalystCenterDialogOpen, catalystCenterById]);
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
  const editingBatfishValue = useMemo(() => {
    if (batfishDialogOpen?.mode !== "edit" || !batfishDialogOpen.sourceId) {
      return null;
    }
    const editingBatfish = batfishById.get(batfishDialogOpen.sourceId) ?? null;
    if (!editingBatfish) {
      return null;
    }
    return {
      sourceId: editingBatfish.source_id,
      host: editingBatfish.host,
      port: editingBatfish.port,
    };
  }, [batfishDialogOpen, batfishById]);

  const editingAgentValue = useMemo(() => {
    if (agentDialogOpen?.mode !== "edit" || !agentDialogOpen.sourceId) {
      return null;
    }
    const editingAgent = agentById.get(agentDialogOpen.sourceId) ?? null;
    if (!editingAgent) {
      return null;
    }
    return {
      sourceId: editingAgent.source_id,
      transport: editingAgent.transport,
      agentId: editingAgent.agent_id,
      url: editingAgent.url,
      credentialId: editingAgent.credential_id,
      maxConcurrency: editingAgent.max_concurrency,
      maxRequestBytes: editingAgent.max_request_bytes,
      maxTimeoutSeconds: editingAgent.max_timeout_seconds,
    };
  }, [agentDialogOpen, agentById]);

  const isDeletePending =
    deleteDialogOpen?.sourceType === "ise"
      ? saveHandlers.deleteIseSourceIsPending
      : deleteDialogOpen?.sourceType === "catalyst_center"
        ? saveHandlers.deleteCatalystCenterSourceIsPending
        : deleteDialogOpen?.sourceType === "pyats"
        ? saveHandlers.deletePyatsSourceIsPending
        : deleteDialogOpen?.sourceType === "mattermost"
          ? saveHandlers.deleteMattermostSourceIsPending
          : deleteDialogOpen?.sourceType === "batfish"
            ? saveHandlers.deleteBatfishSourceIsPending
            : deleteDialogOpen?.sourceType === "agent"
              ? saveHandlers.deleteAgentSourceIsPending
              : saveHandlers.deleteSettingIsPending;

  return useMemo(
    () => ({
      dialog,
      setDialog,
      isLoading,
      nautobot,
      ise,
      catalystCenter,
      pyats,
      mattermost,
      batfish,
      agent,
      isIseLoading,
      isCatalystCenterLoading,
      isPyatsLoading,
      isMattermostLoading,
      isBatfishLoading,
      isAgentLoading,
      existingNautobotIds,
      existingIseIds,
      existingCatalystCenterIds,
      existingPyatsIds,
      existingMattermostIds,
      existingBatfishIds,
      existingAgentIds,
      saveNautobot: saveHandlers.saveNautobot,
      saveIse: saveHandlers.saveIse,
      updateIse: saveHandlers.updateIse,
      saveCatalystCenter: saveHandlers.saveCatalystCenter,
      updateCatalystCenter: saveHandlers.updateCatalystCenter,
      savePyats: saveHandlers.savePyats,
      updatePyats: saveHandlers.updatePyats,
      saveMattermost: saveHandlers.saveMattermost,
      updateMattermost: saveHandlers.updateMattermost,
      saveBatfish: saveHandlers.saveBatfish,
      updateBatfish: saveHandlers.updateBatfish,
      saveAgent: saveHandlers.saveAgent,
      updateAgent: saveHandlers.updateAgent,
      confirmDelete: saveHandlers.confirmDelete,
      nautobotDialogOpen,
      iseDialogOpen,
      catalystCenterDialogOpen,
      pyatsDialogOpen,
      mattermostDialogOpen,
      batfishDialogOpen,
      agentDialogOpen,
      deleteDialogOpen,
      editingNautobot,
      editingIseValue,
      editingCatalystCenterValue,
      editingPyatsValue,
      editingMattermostValue,
      editingBatfishValue,
      editingAgentValue,
      isDeletePending,
      upsertSettingIsPending: saveHandlers.upsertSettingIsPending,
      createIseSourceIsPending: saveHandlers.createIseSourceIsPending,
      updateIseSourceIsPending: saveHandlers.updateIseSourceIsPending,
      createCatalystCenterSourceIsPending:
        saveHandlers.createCatalystCenterSourceIsPending,
      updateCatalystCenterSourceIsPending:
        saveHandlers.updateCatalystCenterSourceIsPending,
      createPyatsSourceIsPending: saveHandlers.createPyatsSourceIsPending,
      updatePyatsSourceIsPending: saveHandlers.updatePyatsSourceIsPending,
      createMattermostSourceIsPending: saveHandlers.createMattermostSourceIsPending,
      updateMattermostSourceIsPending: saveHandlers.updateMattermostSourceIsPending,
      createBatfishSourceIsPending: saveHandlers.createBatfishSourceIsPending,
      updateBatfishSourceIsPending: saveHandlers.updateBatfishSourceIsPending,
      createAgentSourceIsPending: saveHandlers.createAgentSourceIsPending,
      updateAgentSourceIsPending: saveHandlers.updateAgentSourceIsPending,
    }),
    [
      dialog,
      isLoading,
      nautobot,
      ise,
      catalystCenter,
      pyats,
      mattermost,
      batfish,
      agent,
      isIseLoading,
      isCatalystCenterLoading,
      isPyatsLoading,
      isMattermostLoading,
      isBatfishLoading,
      isAgentLoading,
      existingNautobotIds,
      existingIseIds,
      existingCatalystCenterIds,
      existingPyatsIds,
      existingMattermostIds,
      existingBatfishIds,
      existingAgentIds,
      saveHandlers,
      nautobotDialogOpen,
      iseDialogOpen,
      catalystCenterDialogOpen,
      pyatsDialogOpen,
      mattermostDialogOpen,
      batfishDialogOpen,
      agentDialogOpen,
      deleteDialogOpen,
      editingNautobot,
      editingIseValue,
      editingCatalystCenterValue,
      editingPyatsValue,
      editingMattermostValue,
      editingBatfishValue,
      editingAgentValue,
      isDeletePending,
    ],
  );
}
