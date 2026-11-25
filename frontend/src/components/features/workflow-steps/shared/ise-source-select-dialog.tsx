"use client";

import { useISESourcesQuery } from "@/hooks/queries/use-ise-sources-query";

import { SourceSelectDialog } from "./source-select-dialog";

interface ISESourceSelectDialogProps {
  open: boolean;
  selectedSourceId: string;
  onClose: () => void;
  onSave: (sourceId: string) => void;
}

const DESCRIPTION =
  "A configured Cisco ISE source is required. Choose which saved source (from Settings → Sources) this step should use. Only the source ID is stored on the step; the URL and credentials are resolved from settings at runtime.";

export function ISESourceSelectDialog(props: ISESourceSelectDialogProps) {
  const { data, isLoading } = useISESourcesQuery();
  const sources = (data?.sources ?? []).map((source) => ({
    id: source.source_id,
    detail: source.url,
  }));

  return (
    <SourceSelectDialog
      {...props}
      title="Cisco ISE source"
      description={DESCRIPTION}
      sourceLabel="Cisco ISE"
      idPrefix="ise"
      sources={sources}
      isLoading={isLoading}
    />
  );
}
