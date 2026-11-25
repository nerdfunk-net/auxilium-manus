"use client";

import { useAciSourcesQuery } from "@/hooks/queries/use-aci-sources-query";

import { SourceSelectDialog } from "./source-select-dialog";

interface AciSourceSelectDialogProps {
  open: boolean;
  selectedSourceId: string;
  onClose: () => void;
  onSave: (sourceId: string) => void;
}

const DESCRIPTION =
  "A configured Cisco ACI source is required. Choose which saved source (from Settings → Sources) this step should use. Only the source ID is stored on the step; the URL and credentials are resolved from settings at runtime.";

export function AciSourceSelectDialog(props: AciSourceSelectDialogProps) {
  const { data, isLoading } = useAciSourcesQuery();
  const sources = (data?.sources ?? []).map((source) => ({
    id: source.source_id,
    detail: source.url,
  }));

  return (
    <SourceSelectDialog
      {...props}
      title="Cisco ACI source"
      description={DESCRIPTION}
      sourceLabel="Cisco ACI"
      idPrefix="aci"
      sources={sources}
      isLoading={isLoading}
    />
  );
}
