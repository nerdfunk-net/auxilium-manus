"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { ACI_SOURCE_ID_KEY, aciSourceIdFromConfig } from "../shared/aci-source-config";
import { AciSourceSelectDialog } from "../shared/aci-source-select-dialog";
import { readString } from "../shared/catalyst-center-fact-fields";
import { GitRepositorySelectDialog } from "../shared/git-repository-select-dialog";
import { GitRepositoryValue } from "../shared/git-repository-value";
import { BackupAciConfigHelpPanel } from "./help-panel";

const REPOSITORY_KEY = "git_repository_id";
const SUBDIRECTORY_KEY = "repository_subdirectory";
const TENANTS_KEY = "tenants";
const ACCESS_KEY = "include_access_policies";
const COMMIT_KEY = "commit";
const PUSH_KEY = "push";
const MESSAGE_KEY = "commit_message";
const OUTPUT_KEY = "output_key";
const DEFAULT_SUBDIRECTORY = "aci";
const DEFAULT_MESSAGE = "ACI configuration backup of {source_id}";
const DEFAULT_OUTPUT_KEY = "aci_backup";

function repositoryFromConfig(config: Record<string, unknown>): number | null {
  const raw = config[REPOSITORY_KEY];
  return typeof raw === "number" ? raw : null;
}

function tenantsFromConfig(config: Record<string, unknown>): string[] {
  const raw = config[TENANTS_KEY];
  return Array.isArray(raw) ? raw.filter((v): v is string => typeof v === "string") : [];
}

function flag(config: Record<string, unknown>, key: string, fallback: boolean): boolean {
  const raw = config[key];
  return typeof raw === "boolean" ? raw : fallback;
}

interface SwitchRowProps {
  id: string;
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}

function SwitchRow({ id, label, checked, disabled, onChange }: SwitchRowProps) {
  return (
    <div className="flex items-center gap-2">
      <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onChange} />
      <Label className="font-mono text-xs" htmlFor={id}>
        {label}
      </Label>
    </div>
  );
}

function BackupAciConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceId = useMemo(() => aciSourceIdFromConfig(config), [config]);
  const repositoryId = useMemo(() => repositoryFromConfig(config), [config]);
  const tenants = useMemo(() => tenantsFromConfig(config), [config]);
  const subdirectory = readString(config, SUBDIRECTORY_KEY, DEFAULT_SUBDIRECTORY);
  const message = readString(config, MESSAGE_KEY, DEFAULT_MESSAGE);
  const outputKey = readString(config, OUTPUT_KEY, DEFAULT_OUTPUT_KEY);
  const includeAccess = flag(config, ACCESS_KEY, true);
  const commit = flag(config, COMMIT_KEY, true);
  const push = flag(config, PUSH_KEY, false);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [repositoryOpen, setRepositoryOpen] = useState(false);

  const set = useCallback(
    (key: string, value: unknown) => onChange({ ...config, [key]: value }),
    [config, onChange],
  );
  const handleCommit = useCallback(
    // A push needs a commit, so turning the commit off turns the push off too.
    (checked: boolean) =>
      onChange({ ...config, [COMMIT_KEY]: checked, ...(checked ? {} : { [PUSH_KEY]: false }) }),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{ACI_SOURCE_ID_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            aci
          </Badge>
        </div>
        {sourceId ? (
          <p className="font-mono text-[11px] text-muted-foreground">{sourceId}</p>
        ) : (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
        )}
        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setSourceOpen(true)}
        >
          {sourceId ? "Edit Source" : "Configure Source"}
        </Button>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{REPOSITORY_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            git
          </Badge>
        </div>
        <GitRepositoryValue repositoryId={repositoryId} />
        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setRepositoryOpen(true)}
        >
          {repositoryId !== null ? "Change repository" : "Choose repository"}
        </Button>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="aci-backup-subdirectory">
          {SUBDIRECTORY_KEY}
        </Label>
        <Input
          id="aci-backup-subdirectory"
          className="h-8 font-mono text-xs"
          value={subdirectory}
          placeholder={DEFAULT_SUBDIRECTORY}
          onChange={(event) => set(SUBDIRECTORY_KEY, event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          One fabric per folder: tenants/&lt;tenant&gt;.json and access-policies.json inside it.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="aci-backup-tenants">
          {TENANTS_KEY}
        </Label>
        <Textarea
          id="aci-backup-tenants"
          className="min-h-16 font-mono text-xs"
          placeholder="All tenants"
          // Blank lines stay while typing so the cursor is not pulled away after Enter.
          value={tenants.join("\n")}
          onChange={(event) => set(TENANTS_KEY, event.target.value.split("\n"))}
        />
        <p className="text-[11px] text-muted-foreground">
          One tenant per line. Empty backs up every tenant.
        </p>
      </div>

      <div className="space-y-2">
        <SwitchRow
          id="aci-backup-access"
          label={ACCESS_KEY}
          checked={includeAccess}
          onChange={(checked) => set(ACCESS_KEY, checked)}
        />
        <SwitchRow id="aci-backup-commit" label={COMMIT_KEY} checked={commit} onChange={handleCommit} />
        <SwitchRow
          id="aci-backup-push"
          label={PUSH_KEY}
          checked={push}
          disabled={!commit}
          onChange={(checked) => set(PUSH_KEY, checked)}
        />
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="aci-backup-message">
          {MESSAGE_KEY}
        </Label>
        <Input
          id="aci-backup-message"
          className="h-8 font-mono text-xs"
          value={message}
          placeholder={DEFAULT_MESSAGE}
          onChange={(event) => set(MESSAGE_KEY, event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          {"{source_id}"} is replaced by the ACI source id.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="aci-backup-output-key">
          {OUTPUT_KEY}
        </Label>
        <Input
          id="aci-backup-output-key"
          className="h-8 font-mono text-xs"
          value={outputKey}
          placeholder={DEFAULT_OUTPUT_KEY}
          onChange={(event) => set(OUTPUT_KEY, event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Result in the run metadata as &lt;node id&gt;.{outputKey || DEFAULT_OUTPUT_KEY}.
        </p>
      </div>

      <AciSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={(next) => set(ACI_SOURCE_ID_KEY, next)}
      />
      <GitRepositorySelectDialog
        open={repositoryOpen}
        selectedRepositoryId={repositoryId}
        onClose={() => setRepositoryOpen(false)}
        onSave={(next) => set(REPOSITORY_KEY, next)}
      />
    </div>
  );
}

export const BackupAciConfigPlugin: PluginUIComponent = {
  ConfigPanel: BackupAciConfigPanel,
  HelpPanel: BackupAciConfigHelpPanel,
};
