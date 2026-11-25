"use client";

import { useCatalystCenterSourcesQuery } from "@/hooks/queries/use-catalyst-center-sources-query";

import { SourceSelectDialog } from "./source-select-dialog";

interface CatalystCenterSourceSelectDialogProps {
  open: boolean;
  selectedSourceId: string;
  onClose: () => void;
  onSave: (sourceId: string) => void;
}

const DESCRIPTION =
  "A configured Cisco Catalyst Center source is required. Choose which saved source (from Settings → Sources) this step should use. Only the source ID is stored on the step; the URL and credentials are resolved from settings at runtime.";

export function CatalystCenterSourceSelectDialog(props: CatalystCenterSourceSelectDialogProps) {
  const { data, isLoading } = useCatalystCenterSourcesQuery();
  const sources = (data?.sources ?? []).map((source) => ({
    id: source.source_id,
    detail: source.url,
  }));

  return (
    <SourceSelectDialog
      {...props}
      title="Cisco Catalyst Center source"
      description={DESCRIPTION}
      sourceLabel="Cisco Catalyst Center"
      idPrefix="catalyst-center"
      sources={sources}
      isLoading={isLoading}
    />
  );
}
