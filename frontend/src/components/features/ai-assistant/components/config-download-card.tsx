"use client";

import { Download } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import { useConfigDownload } from "../hooks/use-config-download";
import type { ConfigDownloadProposal } from "../types/ai-assistant";
import { describeSize } from "../utils/config-download";

interface ConfigDownloadCardProps {
  proposal: ConfigDownloadProposal;
}

/**
 * A backed-up configuration ready to download. Everything shown is plain text (never markup); the
 * file is fetched from the server on click, as the signed-in user, and is already redacted.
 */
export function ConfigDownloadCard({ proposal }: ConfigDownloadCardProps) {
  const download = useConfigDownload();

  return (
    <div
      className="space-y-2 rounded-md border bg-card p-3"
      data-testid="config-download-card"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium">
          {proposal.configKind || "Configuration"} config of{" "}
          <span className="font-semibold">{proposal.device}</span>
        </p>
        <Badge variant="outline" className="shrink-0">
          {describeSize(proposal.lineCount, proposal.sizeChars)}
        </Badge>
      </div>
      <p className="text-xs text-muted-foreground">
        From the git backup
        {proposal.repository ? ` (${proposal.repository})` : ""}
        {proposal.committedAt
          ? `, committed ${new Date(proposal.committedAt).toLocaleString()}`
          : ""}
        . It may differ from the live device. Secrets are redacted.
      </p>
      {proposal.partial && (
        <p className="text-xs text-muted-foreground">
          The file is longer than the size limit; only its start is included.
        </p>
      )}
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => download.mutate({ handle: proposal.handle })}
        disabled={download.isPending}
      >
        <Download className="size-4" />
        Download config
      </Button>
      <p className="text-xs text-muted-foreground">
        Download it now: the file is kept for a few hours, but this button is
        gone once you reload the page or reopen the chat.
      </p>
      {download.error && (
        <Alert variant="destructive">
          <AlertDescription>{download.error.message}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}
