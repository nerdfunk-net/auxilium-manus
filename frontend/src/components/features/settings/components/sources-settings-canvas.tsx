"use client";

import { FlaskConical, MessageSquare, Network, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { buildSourceSettingKey } from "../constants/setting-keys";
import { ISESourceDialog } from "../dialogs/ise-source-dialog";
import { MattermostSourceDialog } from "../dialogs/mattermost-source-dialog";
import { NautobotSourceDialog } from "../dialogs/nautobot-source-dialog";
import { PyATSSourceDialog } from "../dialogs/pyats-source-dialog";
import { useSourcesSettings } from "../hooks/use-sources-settings";
import { SourceListSection } from "./source-list-section";

export function SourcesSettingsCanvas() {
  const sources = useSourcesSettings();

  return (
    <>
      <div className="flex h-full flex-col overflow-y-auto bg-muted p-10">
        <div className="mx-auto w-full max-w-3xl rounded-2xl border bg-card p-6 shadow-sm">
          <div className="mb-6 flex items-start gap-4">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Network className="size-6" />
            </div>
            <div>
              <p className="text-sm font-semibold">Sources</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Add multiple Nautobot, Cisco ISE, and pyATS connections. Each
                instance needs a unique source ID for workflow step references
                (e.g.{" "}
                <code className="rounded bg-muted px-1 text-xs">prod-lab</code>
                ). Git repositories are configured under Settings → Git
                Repositories.
              </p>
            </div>
          </div>

          <div className="space-y-8 rounded-xl border border-dashed bg-muted/30 p-6">
            <p className="text-sm text-muted-foreground">
              Nautobot connections are stored in PostgreSQL via{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                /api/settings
              </code>{" "}
              as{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                sources.nautobot.&lt;id&gt;
              </code>
              . Cisco ISE connections are stored the same way, with the
              password kept in the encrypted credentials store.
            </p>

            <SourceListSection
              title="Nautobot"
              description="Inventory and device API connections"
              icon={Network}
              isLoading={sources.isLoading}
              emptyLabel="No Nautobot sources yet."
              addLabel="Add Nautobot"
              items={sources.nautobot.map((item) => ({
                sourceId: item.sourceId,
                summary: item.url,
                detail: item.verifySsl ? undefined : "TLS verification disabled",
              }))}
              onAdd={() =>
                sources.setDialog({ type: "nautobot", mode: "create" })
              }
              onEdit={(sourceId) =>
                sources.setDialog({ type: "nautobot", mode: "edit", sourceId })
              }
              onDelete={(sourceId) =>
                sources.setDialog({
                  type: "delete",
                  sourceType: "nautobot",
                  sourceId,
                  key: buildSourceSettingKey("nautobot", sourceId),
                })
              }
            />

            <SourceListSection
              title="Cisco ISE"
              description="Identity Services Engine network device management"
              icon={ShieldCheck}
              isLoading={sources.isIseLoading}
              emptyLabel="No Cisco ISE sources yet."
              addLabel="Add Cisco ISE"
              items={sources.ise.map((item) => ({
                sourceId: item.source_id,
                summary: item.url,
                detail: item.verify_ssl ? undefined : "TLS verification disabled",
              }))}
              onAdd={() => sources.setDialog({ type: "ise", mode: "create" })}
              onEdit={(sourceId) =>
                sources.setDialog({ type: "ise", mode: "edit", sourceId })
              }
              onDelete={(sourceId) =>
                sources.setDialog({
                  type: "delete",
                  sourceType: "ise",
                  sourceId,
                  key: "",
                })
              }
            />

            <SourceListSection
              title="pyATS"
              description="Cisco pyATS/Genie shim for network testing steps"
              icon={FlaskConical}
              isLoading={sources.isPyatsLoading}
              emptyLabel="No pyATS sources yet."
              addLabel="Add pyATS"
              items={sources.pyats.map((item) => ({
                sourceId: item.source_id,
                summary: item.url,
                detail: item.verify_ssl ? undefined : "TLS verification disabled",
              }))}
              onAdd={() => sources.setDialog({ type: "pyats", mode: "create" })}
              onEdit={(sourceId) =>
                sources.setDialog({ type: "pyats", mode: "edit", sourceId })
              }
              onDelete={(sourceId) =>
                sources.setDialog({
                  type: "delete",
                  sourceType: "pyats",
                  sourceId,
                  key: "",
                })
              }
            />

            <SourceListSection
              title="Mattermost"
              description="Chat notifications for workflow runs"
              icon={MessageSquare}
              isLoading={sources.isMattermostLoading}
              emptyLabel="No Mattermost sources yet."
              addLabel="Add Mattermost"
              items={sources.mattermost.map((item) => ({
                sourceId: item.source_id,
                summary: item.url,
                detail: item.verify_ssl ? undefined : "TLS verification disabled",
              }))}
              onAdd={() => sources.setDialog({ type: "mattermost", mode: "create" })}
              onEdit={(sourceId) =>
                sources.setDialog({ type: "mattermost", mode: "edit", sourceId })
              }
              onDelete={(sourceId) =>
                sources.setDialog({
                  type: "delete",
                  sourceType: "mattermost",
                  sourceId,
                  key: "",
                })
              }
            />
          </div>
        </div>
      </div>

      <NautobotSourceDialog
        open={sources.nautobotDialogOpen !== null}
        mode={sources.nautobotDialogOpen?.mode ?? "create"}
        initialValue={sources.editingNautobot}
        existingSourceIds={sources.existingNautobotIds}
        isSaving={sources.upsertSettingIsPending}
        onClose={() => sources.setDialog({ type: "closed" })}
        onSave={sources.saveNautobot}
      />

      <ISESourceDialog
        open={sources.iseDialogOpen !== null}
        mode={sources.iseDialogOpen?.mode ?? "create"}
        initialValue={sources.editingIseValue}
        existingSourceIds={sources.existingIseIds}
        isSaving={sources.createIseSourceIsPending || sources.updateIseSourceIsPending}
        onClose={() => sources.setDialog({ type: "closed" })}
        onCreate={sources.saveIse}
        onUpdate={sources.updateIse}
      />

      <PyATSSourceDialog
        open={sources.pyatsDialogOpen !== null}
        mode={sources.pyatsDialogOpen?.mode ?? "create"}
        initialValue={sources.editingPyatsValue}
        existingSourceIds={sources.existingPyatsIds}
        isSaving={sources.createPyatsSourceIsPending || sources.updatePyatsSourceIsPending}
        onClose={() => sources.setDialog({ type: "closed" })}
        onCreate={sources.savePyats}
        onUpdate={sources.updatePyats}
      />

      <MattermostSourceDialog
        open={sources.mattermostDialogOpen !== null}
        mode={sources.mattermostDialogOpen?.mode ?? "create"}
        initialValue={sources.editingMattermostValue}
        existingSourceIds={sources.existingMattermostIds}
        isSaving={
          sources.createMattermostSourceIsPending || sources.updateMattermostSourceIsPending
        }
        onClose={() => sources.setDialog({ type: "closed" })}
        onCreate={sources.saveMattermost}
        onUpdate={sources.updateMattermost}
      />

      <Dialog
        open={sources.deleteDialogOpen !== null}
        onOpenChange={(open: boolean) => !open && sources.setDialog({ type: "closed" })}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete source?</DialogTitle>
            <DialogDescription>
              {sources.deleteDialogOpen
                ? `Remove ${sources.deleteDialogOpen.sourceType} source "${sources.deleteDialogOpen.sourceId}"? Workflow steps referencing this ID will need to be updated.`
                : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => sources.setDialog({ type: "closed" })}
            >
              Cancel
            </Button>
            <Button
              disabled={sources.isDeletePending}
              type="button"
              variant="destructive"
              onClick={sources.confirmDelete}
            >
              {sources.isDeletePending ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
