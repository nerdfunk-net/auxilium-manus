"use client";

import { useCallback, useMemo, useState } from "react";

import { useCredentialsQuery } from "@/components/features/settings/credentials/hooks/use-credentials-query";
import type { Credential } from "@/components/features/settings/credentials/types";
import { useNautobotSources } from "@/components/features/templates/hooks/use-nautobot-sources";
import { useBatfishSourcesQuery } from "@/hooks/queries/use-batfish-sources-query";
import { useGitRepositoriesQuery } from "@/hooks/queries/use-git-repositories-query";
import { useMattermostSourcesQuery } from "@/hooks/queries/use-mattermost-sources-query";
import { usePyATSSourcesQuery } from "@/hooks/queries/use-pyats-sources-query";
import { useAuthStore } from "@/lib/auth-store";

import type { WorkflowExportCredentialRef } from "../types/workflow-export";
import {
  collectCredentialReferencesFromCanvas,
  collectGitRepositoryIdsFromCanvas,
  collectSourceIdsFromCanvas,
} from "../utils/workflow-export";
import {
  buildCredentialRemapRequirements,
  buildGitRepositoryRemapRequirements,
  buildSourceRemapRequirements,
  type CredentialRemapRequirement,
  type GitRepositoryRemapRequirement,
  type SourceRemapRequirement,
} from "../utils/workflow-import";
import type { SourceRemapType } from "../dialogs/workflow-import-save";
import { SOURCE_CONFIG_KEY_BY_TYPE } from "../dialogs/workflow-import-save";
import type { WorkflowImportReferenceOption } from "../dialogs/workflow-import-reference-remap";

export interface SourceRemapSection {
  requirements: SourceRemapRequirement[];
  options: WorkflowImportReferenceOption[];
  value: Record<string, string>;
  onChange: (oldSourceId: string, newSourceId: string) => void;
  isLoading: boolean;
  /** The list of available sources could not be fetched (for example a 403). */
  loadFailed: boolean;
}

interface UseWorkflowImportRemapArgs {
  canvasNodesList: Record<string, unknown>[][];
  credentialReferencesList: WorkflowExportCredentialRef[][];
  enabled: boolean;
}

const EMPTY_ARRAY: never[] = [];

const SOURCE_TYPES: SourceRemapType[] = ["nautobot", "mattermost", "batfish", "pyats"];

/**
 * Shared remap state (credentials, git repositories, and the four
 * nautobot/mattermost/batfish/pyats source types) for the manual
 * WorkflowImportDialog and the multi-file WorkflowGalleryDialog. Both render
 * the same WorkflowImportCredentialRemap / WorkflowImportReferenceRemap
 * components off this hook's output.
 */
export function useWorkflowImportRemap({
  canvasNodesList,
  credentialReferencesList,
  enabled,
}: UseWorkflowImportRemapArgs) {
  const currentUsername = useAuthStore((state) => state.user?.username ?? "");

  const {
    data: credentialsData,
    isLoading: credentialsLoading,
    isError: credentialsFailed,
  } = useCredentialsQuery({ enabled });
  const {
    data: gitReposData,
    isLoading: gitReposLoading,
    isError: gitReposFailed,
  } = useGitRepositoriesQuery({ activeOnly: true, enabled });
  const {
    sources: nautobotSources,
    isLoading: nautobotLoading,
    isError: nautobotFailed,
  } = useNautobotSources({ enabled });
  const {
    data: mattermostData,
    isLoading: mattermostLoading,
    isError: mattermostFailed,
  } = useMattermostSourcesQuery({ enabled });
  const {
    data: batfishData,
    isLoading: batfishLoading,
    isError: batfishFailed,
  } = useBatfishSourcesQuery({ enabled });
  const {
    data: pyatsData,
    isLoading: pyatsLoading,
    isError: pyatsFailed,
  } = usePyATSSourcesQuery({ enabled });

  const visibleCredentials = useMemo(
    () => credentialsData?.credentials ?? EMPTY_ARRAY,
    [credentialsData?.credentials],
  );
  const gitRepositories = useMemo(
    () => gitReposData?.repositories ?? EMPTY_ARRAY,
    [gitReposData?.repositories],
  );

  const combinedCanvasNodes = useMemo(
    () => canvasNodesList.flat(),
    [canvasNodesList],
  );
  const combinedCredentialRefs = useMemo(
    () => credentialReferencesList.flat(),
    [credentialReferencesList],
  );

  const [credentialRemap, setCredentialRemap] = useState<Record<string, string>>({});
  const [gitRepositoryRemap, setGitRepositoryRemap] = useState<Record<string, string>>(
    {},
  );
  const [sourceRemapValues, setSourceRemapValues] = useState<
    Record<SourceRemapType, Record<string, string>>
  >({ nautobot: {}, mattermost: {}, batfish: {}, pyats: {} });

  const resetRemapState = useCallback(() => {
    setCredentialRemap({});
    setGitRepositoryRemap({});
    setSourceRemapValues({ nautobot: {}, mattermost: {}, batfish: {}, pyats: {} });
  }, []);

  const onCredentialRemapChange = useCallback((oldName: string, newName: string) => {
    setCredentialRemap((previous) => ({ ...previous, [oldName]: newName }));
  }, []);

  const onGitRepositoryRemapChange = useCallback(
    (oldId: string, newRepositoryId: string) => {
      setGitRepositoryRemap((previous) => ({ ...previous, [oldId]: newRepositoryId }));
    },
    [],
  );

  const makeSourceRemapChangeHandler = useCallback(
    (sourceType: SourceRemapType) => (oldSourceId: string, newSourceId: string) => {
      setSourceRemapValues((previous) => ({
        ...previous,
        [sourceType]: { ...previous[sourceType], [oldSourceId]: newSourceId },
      }));
    },
    [],
  );

  const credentialRequirements: CredentialRemapRequirement[] = useMemo(() => {
    if (!enabled || credentialsLoading) return EMPTY_ARRAY;
    return buildCredentialRemapRequirements(
      combinedCredentialRefs,
      combinedCanvasNodes,
      visibleCredentials,
      currentUsername,
    );
  }, [
    enabled,
    credentialsLoading,
    combinedCredentialRefs,
    combinedCanvasNodes,
    visibleCredentials,
    currentUsername,
  ]);

  const gitRepositoryRequirements: GitRepositoryRemapRequirement[] = useMemo(() => {
    if (!enabled || gitReposLoading) return EMPTY_ARRAY;
    return buildGitRepositoryRemapRequirements(
      combinedCanvasNodes,
      gitRepositories.map((repo) => repo.id),
    );
  }, [enabled, gitReposLoading, combinedCanvasNodes, gitRepositories]);

  const gitRepositoryOptions: WorkflowImportReferenceOption[] = useMemo(
    () =>
      gitRepositories.map((repo) => ({
        value: String(repo.id),
        label: `${repo.name} (${repo.category})`,
      })),
    [gitRepositories],
  );

  const sourceAvailableIds: Record<SourceRemapType, string[]> = useMemo(
    () => ({
      nautobot: nautobotSources.map((source) => source.sourceId),
      mattermost: (mattermostData?.sources ?? EMPTY_ARRAY).map((s) => s.source_id),
      batfish: (batfishData?.sources ?? EMPTY_ARRAY).map((s) => s.source_id),
      pyats: (pyatsData?.sources ?? EMPTY_ARRAY).map((s) => s.source_id),
    }),
    [nautobotSources, mattermostData, batfishData, pyatsData],
  );

  const sourceLoading: Record<SourceRemapType, boolean> = useMemo(
    () => ({
      nautobot: nautobotLoading,
      mattermost: mattermostLoading,
      batfish: batfishLoading,
      pyats: pyatsLoading,
    }),
    [nautobotLoading, mattermostLoading, batfishLoading, pyatsLoading],
  );

  const sourceFailed: Record<SourceRemapType, boolean> = useMemo(
    () => ({
      nautobot: nautobotFailed === true,
      mattermost: mattermostFailed,
      batfish: batfishFailed,
      pyats: pyatsFailed,
    }),
    [nautobotFailed, mattermostFailed, batfishFailed, pyatsFailed],
  );

  const sourceSections: Record<SourceRemapType, SourceRemapSection> = useMemo(() => {
    const build = (sourceType: SourceRemapType): SourceRemapSection => {
      const configKey = SOURCE_CONFIG_KEY_BY_TYPE[sourceType];
      const requirements =
        !enabled || sourceLoading[sourceType]
          ? EMPTY_ARRAY
          : buildSourceRemapRequirements(
              combinedCanvasNodes,
              configKey,
              sourceAvailableIds[sourceType],
            );
      return {
        requirements,
        options: sourceAvailableIds[sourceType].map((id) => ({ value: id, label: id })),
        value: sourceRemapValues[sourceType],
        onChange: makeSourceRemapChangeHandler(sourceType),
        isLoading: sourceLoading[sourceType],
        loadFailed: sourceFailed[sourceType],
      };
    };
    return {
      nautobot: build("nautobot"),
      mattermost: build("mattermost"),
      batfish: build("batfish"),
      pyats: build("pyats"),
    };
  }, [
    enabled,
    sourceLoading,
    sourceFailed,
    combinedCanvasNodes,
    sourceAvailableIds,
    sourceRemapValues,
    makeSourceRemapChangeHandler,
  ]);

  const isLoading =
    credentialsLoading ||
    gitReposLoading ||
    nautobotLoading ||
    mattermostLoading ||
    batfishLoading ||
    pyatsLoading;

  const hasAnyRequirements =
    credentialRequirements.length > 0 ||
    gitRepositoryRequirements.length > 0 ||
    SOURCE_TYPES.some((type) => sourceSections[type].requirements.length > 0);

  const allSelected = useMemo(() => {
    const credentialsOk = credentialRequirements.every((requirement) =>
      Boolean(credentialRemap[requirement.name]?.trim()),
    );
    const gitOk = gitRepositoryRequirements.every((requirement) =>
      Boolean(gitRepositoryRemap[String(requirement.id)]?.trim()),
    );
    const sourcesOk = SOURCE_TYPES.every((type) =>
      sourceSections[type].requirements.every((requirement) =>
        Boolean(sourceSections[type].value[requirement.sourceId]?.trim()),
      ),
    );
    return credentialsOk && gitOk && sourcesOk;
  }, [
    credentialRequirements,
    credentialRemap,
    gitRepositoryRequirements,
    gitRepositoryRemap,
    sourceSections,
  ]);

  // The requirements of a lookup are unknown until its list has loaded, and `hasAnyRequirements`
  // stays false meanwhile. Import must wait for every lookup this workflow actually needs, or a
  // click during loading would skip the mapping. Lookups for references the workflow does not
  // contain are not waited for.
  const isCheckingReferences = useMemo(() => {
    if (!enabled) return false;
    const referencesCredentials =
      collectCredentialReferencesFromCanvas(combinedCanvasNodes).length > 0;
    const referencesGit = collectGitRepositoryIdsFromCanvas(combinedCanvasNodes).length > 0;
    const referencesSource = (type: SourceRemapType) =>
      collectSourceIdsFromCanvas(combinedCanvasNodes, SOURCE_CONFIG_KEY_BY_TYPE[type]).length > 0;
    return (
      (referencesCredentials && credentialsLoading) ||
      (referencesGit && gitReposLoading) ||
      SOURCE_TYPES.some((type) => referencesSource(type) && sourceLoading[type])
    );
  }, [enabled, combinedCanvasNodes, credentialsLoading, gitReposLoading, sourceLoading]);

  /** True when the import may go ahead: nothing is still being checked and every reference that
   * needs a replacement has one. Use this, not `hasAnyRequirements`, to enable the Import button. */
  const canProceed = !isCheckingReferences && (!hasAnyRequirements || allSelected);

  const buildRemapArgs = useCallback(() => {
    const credentialMap = new Map<string, string>();
    for (const requirement of credentialRequirements) {
      const selected = credentialRemap[requirement.name]?.trim();
      if (selected) credentialMap.set(requirement.name, selected);
    }

    const gitMap = new Map<number, number>();
    for (const requirement of gitRepositoryRequirements) {
      const selected = gitRepositoryRemap[String(requirement.id)]?.trim();
      if (selected) gitMap.set(requirement.id, Number(selected));
    }

    const sourceMaps = {} as Record<SourceRemapType, Map<string, string>>;
    for (const type of SOURCE_TYPES) {
      const map = new Map<string, string>();
      for (const requirement of sourceSections[type].requirements) {
        const selected = sourceSections[type].value[requirement.sourceId]?.trim();
        if (selected) map.set(requirement.sourceId, selected);
      }
      sourceMaps[type] = map;
    }

    return {
      credentialRemap: credentialMap,
      gitRepositoryRemap: gitMap,
      sourceRemaps: sourceMaps,
    };
  }, [
    credentialRequirements,
    credentialRemap,
    gitRepositoryRequirements,
    gitRepositoryRemap,
    sourceSections,
  ]);

  return {
    isLoading,
    hasAnyRequirements,
    allSelected,
    isCheckingReferences,
    canProceed,
    resetRemapState,
    buildRemapArgs,
    credential: {
      requirements: credentialRequirements,
      credentials: visibleCredentials,
      value: credentialRemap,
      onChange: onCredentialRemapChange,
      isLoading: credentialsLoading,
      loadFailed: credentialsFailed,
    },
    gitRepository: {
      requirements: gitRepositoryRequirements,
      options: gitRepositoryOptions,
      value: gitRepositoryRemap,
      onChange: onGitRepositoryRemapChange,
      isLoading: gitReposLoading,
      loadFailed: gitReposFailed,
    },
    sources: sourceSections,
  } as const;
}

export type { Credential };
