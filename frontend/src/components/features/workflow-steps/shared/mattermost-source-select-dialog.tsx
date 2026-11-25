"use client";

import { useMattermostSourcesQuery } from "@/hooks/queries/use-mattermost-sources-query";

import { SourceSelectDialog } from "./source-select-dialog";

interface MattermostSourceSelectDialogProps {
  open: boolean;
  selectedSourceId: string;
  onClose: () => void;
  onSave: (sourceId: string) => void;
}

const DESCRIPTION =
  "A configured Mattermost source is required. Choose which saved source (from Settings → Sources) this step should use. Only the source ID is stored on the step; the URL and token are resolved from settings at runtime.";

export function MattermostSourceSelectDialog(props: MattermostSourceSelectDialogProps) {
  const { data, isLoading } = useMattermostSourcesQuery();
  const sources = (data?.sources ?? []).map((source) => ({
    id: source.source_id,
    detail: source.url,
  }));

  return (
    <SourceSelectDialog
      {...props}
      title="Mattermost source"
      description={DESCRIPTION}
      sourceLabel="Mattermost"
      idPrefix="mattermost"
      sources={sources}
      isLoading={isLoading}
    />
  );
}
