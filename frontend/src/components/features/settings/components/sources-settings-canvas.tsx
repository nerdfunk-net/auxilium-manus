"use client";

import { useCallback, useMemo, useState } from "react";
import { GitBranch, Network, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  usePullGitSourceMutation,
  useRemoveAndCloneGitSourceMutation,
} from "@/hooks/queries/use-git-source-operations-mutations";
import { useISESourcesMutations } from "@/hooks/queries/use-ise-sources-mutations";
import { useISESourcesQuery } from "@/hooks/queries/use-ise-sources-query";
import { useSettingsMutations } from "@/hooks/queries/use-settings-mutations";
import { useSettingsListQuery } from "@/hooks/queries/use-settings-query";

import {
  SOURCES_KEY_PREFIX,
  buildSourceSettingKey,
} from "../constants/setting-keys";
import { GitSourceDialog } from "../dialogs/git-source-dialog";
import { ISESourceDialog } from "../dialogs/ise-source-dialog";
import { NautobotSourceDialog } from "../dialogs/nautobot-source-dialog";
import type {
  GitSourceConfig,
  GitSourceValue,
  ISESourceCreatePayload,
  ISESourceUpdatePayload,
  NautobotSourceConfig,
  NautobotSourceValue,
} from "../types/settings-api";
import {
  collectExistingSourceIds,
  groupSourceSettings,
} from "../utils/parse-source-settings";
import { SourceListSection } from "./source-list-section";

type DialogState =
  | { type: "closed" }
  | { type: "nautobot"; mode: "create" | "edit"; sourceId?: string }
  | { type: "git"; mode: "create" | "edit"; sourceId?: string }
  | { type: "ise"; mode: "create" | "edit"; sourceId?: string }
  | {
      type: "delete";
      sourceType: "nautobot" | "git" | "ise";
      sourceId: string;
      key: string;
    }
  | { type: "remove-and-clone"; sourceId: string };

export function SourcesSettingsCanvas() {
  const [dialog, setDialog] = useState<DialogState>({ type: "closed" });
  const { data, isLoading } = useSettingsListQuery({
    keyPrefix: SOURCES_KEY_PREFIX,
  });
  const { upsertSetting, deleteSetting } = useSettingsMutations();
  const pullGitSource = usePullGitSourceMutation();
  const removeAndCloneGitSource = useRemoveAndCloneGitSourceMutation();

  const { data: iseData, isLoading: isIseLoading } = useISESourcesQuery();
  const {
    createSource: createIseSource,
    updateSource: updateIseSource,
    deleteSource: deleteIseSource,
  } = useISESourcesMutations();
  const ise = useMemo(() => iseData?.sources ?? [], [iseData]);
  const iseById = useMemo(
    () => new Map(ise.map((item) => [item.source_id, item])),
    [ise],
  );
  const existingIseIds = useMemo(() => ise.map((item) => item.source_id), [ise]);

  const { nautobot, git } = useMemo(
    () => groupSourceSettings(data?.settings ?? []),
    [data?.settings],
  );

  const nautobotById = useMemo(
    () => new Map(nautobot.map((item) => [item.sourceId, item])),
    [nautobot],
  );
  const gitById = useMemo(
    () => new Map(git.map((item) => [item.sourceId, item])),
    [git],
  );

  const existingNautobotIds = useMemo(
    () => collectExistingSourceIds(data?.settings ?? [], "nautobot"),
    [data?.settings],
  );
  const existingGitIds = useMemo(
    () => collectExistingSourceIds(data?.settings ?? [], "git"),
    [data?.settings],
  );

  const saveNautobot = useCallback(
    async (values: NautobotSourceValue, settingKey: string) => {
      const exists = nautobotById.has(values.sourceId);
      await upsertSetting.mutateAsync({
        key: settingKey,
        value: { ...values },
        description: `Nautobot source ${values.sourceId}`,
        exists,
      });
      setDialog({ type: "closed" });
    },
    [nautobotById, upsertSetting],
  );

  const saveGit = useCallback(
    async (values: GitSourceValue, settingKey: string) => {
      const exists = gitById.has(values.sourceId);
      await upsertSetting.mutateAsync({
        key: settingKey,
        value: { ...values },
        description: `Git source ${values.sourceId}`,
        exists,
      });
      setDialog({ type: "closed" });
    },
    [gitById, upsertSetting],
  );

  const saveIse = useCallback(
    async (values: ISESourceCreatePayload) => {
      await createIseSource.mutateAsync(values);
      setDialog({ type: "closed" });
    },
    [createIseSource],
  );

  const updateIse = useCallback(
    async (sourceId: string, values: ISESourceUpdatePayload) => {
      await updateIseSource.mutateAsync({ sourceId, data: values });
      setDialog({ type: "closed" });
    },
    [updateIseSource],
  );

  const confirmDelete = useCallback(async () => {
    if (dialog.type !== "delete") {
      return;
    }
    if (dialog.sourceType === "ise") {
      await deleteIseSource.mutateAsync(dialog.sourceId);
    } else {
      await deleteSetting.mutateAsync(dialog.key);
    }
    setDialog({ type: "closed" });
  }, [dialog, deleteSetting, deleteIseSource]);

  const handlePullGit = useCallback(
    async (sourceId: string) => {
      await pullGitSource.mutateAsync(sourceId);
    },
    [pullGitSource],
  );

  const confirmRemoveAndClone = useCallback(async () => {
    if (dialog.type !== "remove-and-clone") {
      return;
    }
    await removeAndCloneGitSource.mutateAsync(dialog.sourceId);
    setDialog({ type: "closed" });
  }, [dialog, removeAndCloneGitSource]);

  const nautobotDialogOpen =
    dialog.type === "nautobot" ? dialog : null;
  const gitDialogOpen = dialog.type === "git" ? dialog : null;
  const iseDialogOpen = dialog.type === "ise" ? dialog : null;
  const deleteDialogOpen = dialog.type === "delete" ? dialog : null;
  const removeAndCloneDialogOpen =
    dialog.type === "remove-and-clone" ? dialog : null;

  const editingNautobot: NautobotSourceConfig | null =
    nautobotDialogOpen?.mode === "edit" && nautobotDialogOpen.sourceId
      ? (nautobotById.get(nautobotDialogOpen.sourceId) ?? null)
      : null;
  const editingGit: GitSourceConfig | null =
    gitDialogOpen?.mode === "edit" && gitDialogOpen.sourceId
      ? (gitById.get(gitDialogOpen.sourceId) ?? null)
      : null;
  const editingIse =
    iseDialogOpen?.mode === "edit" && iseDialogOpen.sourceId
      ? (iseById.get(iseDialogOpen.sourceId) ?? null)
      : null;
  const editingIseValue = editingIse
    ? {
        sourceId: editingIse.source_id,
        url: editingIse.url,
        verifySsl: editingIse.verify_ssl,
        timeout: editingIse.timeout,
      }
    : null;

  const isDeletePending =
    deleteDialogOpen?.sourceType === "ise"
      ? deleteIseSource.isPending
      : deleteSetting.isPending;

  return (
    <>
      <div className="flex h-full items-center justify-center overflow-y-auto bg-slate-50 p-10">
        <div className="w-full max-w-3xl rounded-2xl border bg-card p-6 shadow-sm">
          <div className="mb-6 flex items-start gap-4">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Network className="size-6" />
            </div>
            <div>
              <p className="text-sm font-semibold">Sources</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Add multiple Nautobot, Git, and Cisco ISE connections. Each
                instance needs a unique source ID for workflow step references
                (e.g. <code className="rounded bg-muted px-1 text-xs">prod-lab</code>
                ).
              </p>
            </div>
          </div>

          <div className="space-y-8 rounded-xl border border-dashed bg-muted/30 p-6">
            <p className="text-sm text-muted-foreground">
              Nautobot and Git connections are stored in PostgreSQL via{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                /api/settings
              </code>{" "}
              as{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                sources.nautobot.&lt;id&gt;
              </code>{" "}
              and{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                sources.git.&lt;id&gt;
              </code>
              . Cisco ISE connections are stored the same way, with the
              password kept in the encrypted credentials store.
            </p>

            <SourceListSection
              title="Nautobot"
              description="Inventory and device API connections"
              icon={Network}
              isLoading={isLoading}
              emptyLabel="No Nautobot sources yet."
              addLabel="Add Nautobot"
              items={nautobot.map((item) => ({
                sourceId: item.sourceId,
                summary: item.url,
              }))}
              onAdd={() =>
                setDialog({ type: "nautobot", mode: "create" })
              }
              onEdit={(sourceId) =>
                setDialog({ type: "nautobot", mode: "edit", sourceId })
              }
              onDelete={(sourceId) =>
                setDialog({
                  type: "delete",
                  sourceType: "nautobot",
                  sourceId,
                  key: buildSourceSettingKey("nautobot", sourceId),
                })
              }
            />

            <SourceListSection
              title="Git repositories"
              description="Version-controlled configuration repositories"
              icon={GitBranch}
              isLoading={isLoading}
              emptyLabel="No Git repositories yet."
              addLabel="Add Git"
              items={git.map((item) => ({
                sourceId: item.sourceId,
                summary: item.url,
                detail: `branch: ${item.branch}`,
              }))}
              onAdd={() => setDialog({ type: "git", mode: "create" })}
              onEdit={(sourceId) =>
                setDialog({ type: "git", mode: "edit", sourceId })
              }
              onDelete={(sourceId) =>
                setDialog({
                  type: "delete",
                  sourceType: "git",
                  sourceId,
                  key: buildSourceSettingKey("git", sourceId),
                })
              }
              onPull={handlePullGit}
              onRemoveAndClone={(sourceId) =>
                setDialog({ type: "remove-and-clone", sourceId })
              }
            />

            <SourceListSection
              title="Cisco ISE"
              description="Identity Services Engine network device management"
              icon={ShieldCheck}
              isLoading={isIseLoading}
              emptyLabel="No Cisco ISE sources yet."
              addLabel="Add Cisco ISE"
              items={ise.map((item) => ({
                sourceId: item.source_id,
                summary: item.url,
                detail: item.verify_ssl ? undefined : "TLS verification disabled",
              }))}
              onAdd={() => setDialog({ type: "ise", mode: "create" })}
              onEdit={(sourceId) =>
                setDialog({ type: "ise", mode: "edit", sourceId })
              }
              onDelete={(sourceId) =>
                setDialog({
                  type: "delete",
                  sourceType: "ise",
                  sourceId,
                  key: "",
                })
              }
            />
          </div>
        </div>
      </div>

      <NautobotSourceDialog
        open={nautobotDialogOpen !== null}
        mode={nautobotDialogOpen?.mode ?? "create"}
        initialValue={editingNautobot}
        existingSourceIds={existingNautobotIds}
        isSaving={upsertSetting.isPending}
        onClose={() => setDialog({ type: "closed" })}
        onSave={saveNautobot}
      />

      <GitSourceDialog
        open={gitDialogOpen !== null}
        mode={gitDialogOpen?.mode ?? "create"}
        initialValue={editingGit}
        existingSourceIds={existingGitIds}
        isSaving={upsertSetting.isPending}
        onClose={() => setDialog({ type: "closed" })}
        onSave={saveGit}
      />

      <ISESourceDialog
        open={iseDialogOpen !== null}
        mode={iseDialogOpen?.mode ?? "create"}
        initialValue={editingIseValue}
        existingSourceIds={existingIseIds}
        isSaving={createIseSource.isPending || updateIseSource.isPending}
        onClose={() => setDialog({ type: "closed" })}
        onCreate={saveIse}
        onUpdate={updateIse}
      />

      <Dialog
        open={removeAndCloneDialogOpen !== null}
        onOpenChange={(open: boolean) => !open && setDialog({ type: "closed" })}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Remove and re-clone?</DialogTitle>
            <DialogDescription>
              {removeAndCloneDialogOpen
                ? `This will delete the local copy of "${removeAndCloneDialogOpen.sourceId}" and clone it fresh from the remote. Any uncommitted local changes will be lost.`
                : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDialog({ type: "closed" })}
            >
              Cancel
            </Button>
            <Button
              disabled={removeAndCloneGitSource.isPending}
              type="button"
              variant="destructive"
              onClick={confirmRemoveAndClone}
            >
              {removeAndCloneGitSource.isPending ? "Cloning…" : "Remove and Clone"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={deleteDialogOpen !== null}
        onOpenChange={(open: boolean) => !open && setDialog({ type: "closed" })}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete source?</DialogTitle>
            <DialogDescription>
              {deleteDialogOpen
                ? `Remove ${deleteDialogOpen.sourceType} source "${deleteDialogOpen.sourceId}"? Workflow steps referencing this ID will need to be updated.`
                : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDialog({ type: "closed" })}
            >
              Cancel
            </Button>
            <Button
              disabled={isDeletePending}
              type="button"
              variant="destructive"
              onClick={confirmDelete}
            >
              {isDeletePending ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
