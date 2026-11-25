"use client";

import { useBatfishSourcesQuery } from "@/hooks/queries/use-batfish-sources-query";

import { SourceSelectDialog } from "./source-select-dialog";

interface BatfishSourceSelectDialogProps {
  open: boolean;
  selectedSourceId: string;
  onClose: () => void;
  onSave: (sourceId: string) => void;
}

const DESCRIPTION =
  "A configured Batfish source is required. Choose which saved source (from Settings → Sources) this step should use.";

export function BatfishSourceSelectDialog(props: BatfishSourceSelectDialogProps) {
  const { data, isLoading } = useBatfishSourcesQuery();
  const sources = (data?.sources ?? []).map((source) => ({
    id: source.source_id,
    detail: `${source.host}:${source.port}`,
  }));

  return (
    <SourceSelectDialog
      {...props}
      title="Batfish source"
      description={DESCRIPTION}
      sourceLabel="Batfish"
      idPrefix="batfish"
      sources={sources}
      isLoading={isLoading}
    />
  );
}
