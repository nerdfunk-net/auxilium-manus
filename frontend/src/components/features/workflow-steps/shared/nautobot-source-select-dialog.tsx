"use client";

import { SOURCE_KEY_PREFIXES } from "@/components/features/settings/constants/setting-keys";
import { useNautobotConfiguredSourcesQuery } from "@/hooks/queries/use-nautobot-configured-sources-query";

import { SourceSelectDialog } from "./source-select-dialog";

interface NautobotSourceSelectDialogProps {
  open: boolean;
  selectedSourceId: string;
  onClose: () => void;
  onSave: (sourceId: string) => void;
}

const DESCRIPTION =
  "A configured Nautobot connection is required. Choose which saved source (from Settings → Sources) this step should use. Only the source ID is stored on the step; URL and token are loaded from settings at runtime.";

function sourceHint(sourceId: string) {
  return (
    <p className="text-[11px] text-muted-foreground">
      Reference this ID when wiring sources in workflow steps (e.g.{" "}
      <code className="rounded bg-muted px-1">
        {SOURCE_KEY_PREFIXES.nautobot}
        {sourceId || "<id>"}
      </code>
      ).
    </p>
  );
}

export function NautobotSourceSelectDialog(props: NautobotSourceSelectDialogProps) {
  // The list is fetched only while the dialog is open.
  const { data, isLoading } = useNautobotConfiguredSourcesQuery({ enabled: props.open });
  const sources = (data ?? []).map((source) => ({ id: source.source_id, detail: source.url }));

  return (
    <SourceSelectDialog
      {...props}
      title="Nautobot source"
      description={DESCRIPTION}
      sourceLabel="Nautobot"
      idPrefix="nautobot"
      sources={sources}
      isLoading={isLoading}
      renderHint={sourceHint}
    />
  );
}
