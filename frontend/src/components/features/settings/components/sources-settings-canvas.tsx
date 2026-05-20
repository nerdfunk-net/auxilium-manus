"use client";

import { useCallback, useMemo, useState } from "react";
import { GitBranch, Network } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useSettingsMutations } from "@/hooks/queries/use-settings-mutations";
import { useSettingsListQuery } from "@/hooks/queries/use-settings-query";

import {
  SOURCES_KEY_PREFIX,
  buildSourceSettingKey,
} from "../constants/setting-keys";
import { GitSourceDialog } from "../dialogs/git-source-dialog";
import { NautobotSourceDialog } from "../dialogs/nautobot-source-dialog";
import type {
  GitSourceConfig,
  GitSourceValue,
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
  | { type: "delete"; sourceType: "nautobot" | "git"; sourceId: string; key: string };

export function SourcesSettingsCanvas() {
  const [dialog, setDialog] = useState<DialogState>({ type: "closed" });
  const { data, isLoading } = useSettingsListQuery({
    keyPrefix: SOURCES_KEY_PREFIX,
  });
  const { upsertSetting, deleteSetting } = useSettingsMutations();

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

  const confirmDelete = useCallback(async () => {
    if (dialog.type !== "delete") {
      return;
    }
    await deleteSetting.mutateAsync(dialog.key);
    setDialog({ type: "closed" });
  }, [dialog, deleteSetting]);

  const nautobotDialogOpen =
    dialog.type === "nautobot" ? dialog : null;
  const gitDialogOpen = dialog.type === "git" ? dialog : null;
  const deleteDialogOpen = dialog.type === "delete" ? dialog : null;

  const editingNautobot: NautobotSourceConfig | null =
    nautobotDialogOpen?.mode === "edit" && nautobotDialogOpen.sourceId
      ? (nautobotById.get(nautobotDialogOpen.sourceId) ?? null)
      : null;
  const editingGit: GitSourceConfig | null =
    gitDialogOpen?.mode === "edit" && gitDialogOpen.sourceId
      ? (gitById.get(gitDialogOpen.sourceId) ?? null)
      : null;

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
                Add multiple Nautobot and Git connections. Each instance needs a
                unique source ID for workflow step references (e.g.{" "}
                <code className="rounded bg-muted px-1 text-xs">prod-lab</code>
                ).
              </p>
            </div>
          </div>

          <div className="space-y-8 rounded-xl border border-dashed bg-muted/30 p-6">
            <p className="text-sm text-muted-foreground">
              Stored in PostgreSQL via{" "}
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
              .
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
              disabled={deleteSetting.isPending}
              type="button"
              variant="destructive"
              onClick={confirmDelete}
            >
              {deleteSetting.isPending ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
