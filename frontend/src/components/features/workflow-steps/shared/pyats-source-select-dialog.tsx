"use client";

import { usePyATSSourcesQuery } from "@/hooks/queries/use-pyats-sources-query";

import { SourceSelectDialog } from "./source-select-dialog";

interface PyATSSourceSelectDialogProps {
  open: boolean;
  selectedSourceId: string;
  onClose: () => void;
  onSave: (sourceId: string) => void;
}

const DESCRIPTION =
  "A configured pyATS shim source is required. Choose which saved source (from Settings → Sources) this step should use. Only the source ID is stored on the step; the shim URL and token are resolved from settings at runtime.";

export function PyATSSourceSelectDialog(props: PyATSSourceSelectDialogProps) {
  const { data, isLoading } = usePyATSSourcesQuery();
  const sources = (data?.sources ?? []).map((source) => ({
    id: source.source_id,
    detail: source.url,
  }));

  return (
    <SourceSelectDialog
      {...props}
      title="pyATS source"
      description={DESCRIPTION}
      sourceLabel="pyATS"
      idPrefix="pyats"
      sources={sources}
      isLoading={isLoading}
    />
  );
}
